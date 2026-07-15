import base64
from io import BytesIO

import qrcode
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from django.db import IntegrityError, transaction
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from .emails import send_verify_email
from .forms import ClaimForm
from .models import (
    Answer,
    Choice,
    Kiosk,
    PrizeClaim,
    PrizeCode,
    Question,
    SurveySession,
)
from .tokens import mint_kiosk_token, verify_kiosk_token


# --- Root ------------------------------------------------------------------

def home(request):
    """Send the bare root somewhere useful.

    With exactly one active kiosk, go straight to its screen; otherwise fall
    back to the admin (where kiosks are managed).
    """
    active = Kiosk.objects.filter(active=True)
    if active.count() == 1:
        return redirect("survey:kiosk", kiosk_id=active.get().id)
    return redirect("admin:index")


# --- Kiosk + rotating QR ----------------------------------------------------

def _qr_data_uri(url):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def kiosk_page(request, kiosk_id):
    kiosk = get_object_or_404(Kiosk, pk=kiosk_id, active=True)
    return render(
        request,
        "survey/kiosk.html",
        {"kiosk": kiosk, "rotate_seconds": kiosk.effective_rotate_seconds},
    )


@ratelimit(key="ip", rate="120/m", block=True)
def kiosk_qr(request, kiosk_id):
    """HTMX fragment: a freshly signed QR, re-fetched every rotate_seconds."""
    kiosk = get_object_or_404(Kiosk, pk=kiosk_id, active=True)
    token = mint_kiosk_token(kiosk.id)
    scan_path = reverse("survey:scan", args=[token])
    scan_url = f"{settings.BASE_URL}{scan_path}"
    return render(
        request,
        "survey/_qr.html",
        {"qr_data_uri": _qr_data_uri(scan_url), "scan_url": scan_url},
    )


# --- Scan -> mint session ---------------------------------------------------

@ratelimit(key="ip", rate="30/m", block=True)
def scan(request, token):
    """Validate a rotating token and mint a brand-new session per scan."""
    kiosk_id = verify_kiosk_token(token, max_age=settings.TOKEN_TTL_SECONDS)
    if kiosk_id is None:
        return render(request, "survey/expired_token.html", status=410)
    kiosk = get_object_or_404(Kiosk, pk=kiosk_id, active=True)
    session = SurveySession.objects.create(kiosk=kiosk, survey=kiosk.survey)
    return redirect("survey:start", session_id=session.id)


# --- Session helpers --------------------------------------------------------

def _live_session_or_response(request, session_id):
    """Return (session, None) if live, else (None, rendered expired response)."""
    session = get_object_or_404(SurveySession, pk=session_id)
    if session.status == SurveySession.Status.COMPLETED:
        return session, redirect("survey:claim", session_id=session.id)
    if not session.is_live:
        if session.status == SurveySession.Status.ACTIVE:
            session.status = SurveySession.Status.EXPIRED
            session.save(update_fields=["status"])
        return None, render(request, "survey/expired_session.html", status=410)
    return session, None


# --- Start: IRB consent + short/long pick -----------------------------------

def start(request, session_id):
    session, blocked = _live_session_or_response(request, session_id)
    if blocked is not None:
        return blocked

    if request.method == "POST":
        length = request.POST.get("length")
        consented = request.POST.get("consent") == "on"
        errors = []
        if length not in SurveySession.Length.values:
            errors.append("Please choose a survey length.")
        if not consented:
            errors.append("You must consent to participate to continue.")
        if errors:
            return render(
                request,
                "survey/consent.html",
                {"session": session, "errors": errors},
                status=400,
            )
        session.length = length
        session.consented = True
        session.save(update_fields=["length", "consented"])
        return redirect("survey:question", session_id=session.id, step=1)

    return render(request, "survey/consent.html", {"session": session, "errors": []})


# --- Question rendering + submission ----------------------------------------

def _save_answer(session, q, request):
    """Validate and persist one answer. Returns an error string or None."""
    answer, _ = Answer.objects.get_or_create(session=session, question=q)

    if q.type == Question.Type.SINGLE:
        choice_id = request.POST.get("choice")
        choice = q.choices.filter(pk=choice_id).first() if choice_id else None
        if choice is None:
            return "Please select an option." if q.required else None
        answer.choices.set([choice])

    elif q.type == Question.Type.MULTI:
        ids = request.POST.getlist("choices")
        chosen = list(q.choices.filter(pk__in=ids))
        if not chosen and q.required:
            return "Please select at least one option."
        answer.choices.set(chosen)

    elif q.type == Question.Type.LIKERT:
        raw = request.POST.get("likert")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return "Please choose a rating." if q.required else None
        if value not in q.likert_range:
            return "Please choose a valid rating."
        answer.likert_value = value
        answer.save(update_fields=["likert_value"])

    elif q.type == Question.Type.SHORT_TEXT:
        text = (request.POST.get("text") or "").strip()
        if not text and q.required:
            return "Please enter a response."
        answer.text_value = text
        answer.save(update_fields=["text_value"])

    elif q.type == Question.Type.IMAGE_GRID:
        try:
            row = int(request.POST.get("grid_row"))
            col = int(request.POST.get("grid_col"))
        except (TypeError, ValueError):
            return "Please tap a cell on the image." if q.required else None
        if not (0 <= row < (q.grid_rows or 0)) or not (0 <= col < (q.grid_cols or 0)):
            return "That cell is out of range — please tap a cell on the image."
        answer.grid_row, answer.grid_col = row, col
        answer.save(update_fields=["grid_row", "grid_col"])

    return None


def question(request, session_id, step):
    session, blocked = _live_session_or_response(request, session_id)
    if blocked is not None:
        return blocked
    if not session.length or not session.consented:
        return redirect("survey:start", session_id=session.id)

    questions = list(session.survey.questions_for(session.length))
    total = len(questions)
    if step < 1 or step > total:
        return redirect("survey:question", session_id=session.id, step=1)
    q = questions[step - 1]

    error = None
    if request.method == "POST":
        error = _save_answer(session, q, request)
        if error is None:
            if step >= total:
                session.status = SurveySession.Status.COMPLETED
                session.completed_at = timezone.now()
                session.save(update_fields=["status", "completed_at"])
                return redirect("survey:claim", session_id=session.id)
            return redirect("survey:question", session_id=session.id, step=step + 1)

    existing = Answer.objects.filter(session=session, question=q).first()
    return render(
        request,
        "survey/question.html",
        {
            "session": session,
            "question": q,
            "step": step,
            "total": total,
            "answer": existing,
            "error": error,
            "selected_choice_ids": (
                list(existing.choices.values_list("id", flat=True)) if existing else []
            ),
        },
    )


# --- Claim: username -> magic-link email ------------------------------------

@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def claim(request, session_id):
    session = get_object_or_404(SurveySession, pk=session_id)

    # Must have finished the survey to claim.
    if session.status != SurveySession.Status.COMPLETED:
        if session.is_live:
            return redirect("survey:question", session_id=session.id, step=1)
        return render(request, "survey/expired_session.html", status=410)

    # One claim per session. If it already exists, route to the right page.
    claim_obj = getattr(session, "claim", None)
    if claim_obj is not None:
        if claim_obj.status == PrizeClaim.Status.PENDING:
            return render(request, "survey/claim_pending.html", {"claim": claim_obj})
        return redirect("survey:verify", token=claim_obj.verify_token)

    form = ClaimForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.email

        # One prize per mailbox (already delivered / verified).
        if PrizeClaim.objects.filter(
            email=email, status__in=[PrizeClaim.Status.VERIFIED, PrizeClaim.Status.POOL_EMPTY]
        ).exists():
            form.add_error("username", "This email has already claimed a prize.")
        else:
            # A live pending claim for this mailbox? Don't re-send.
            pending = PrizeClaim.objects.filter(
                email=email, status=PrizeClaim.Status.PENDING
            ).first()
            if pending and not pending.verify_expired:
                return render(request, "survey/claim_pending.html", {"claim": pending})

            new_claim = PrizeClaim.objects.create(session=session, email=email)
            send_verify_email(new_claim)
            return render(request, "survey/claim_pending.html", {"claim": new_claim})

    return render(
        request,
        "survey/claim.html",
        {"session": session, "form": form, "target_domain": settings.TARGET_DOMAIN},
    )


def _assign_prize(claim):
    """Atomically verify the claim and assign the next free code, or mark pool-empty.

    Idempotent: a claim that is already verified/pool_empty is returned unchanged.
    """
    with transaction.atomic():
        claim = PrizeClaim.objects.select_for_update().get(pk=claim.pk)
        if claim.status != PrizeClaim.Status.PENDING:
            return claim  # already processed — re-click shows the same result

        code = (
            PrizeCode.objects.select_for_update(skip_locked=True)
            .filter(assigned=False)
            .order_by("id")
            .first()
        )
        claim.verified_at = timezone.now()
        if code is None:
            claim.status = PrizeClaim.Status.POOL_EMPTY
            claim.save(update_fields=["status", "verified_at"])
        else:
            code.assigned = True
            code.assigned_to = claim
            code.save(update_fields=["assigned", "assigned_to"])
            claim.prize_code = code
            claim.status = PrizeClaim.Status.VERIFIED
            claim.save(update_fields=["status", "verified_at", "prize_code"])
    return claim


def verify(request, token):
    claim = PrizeClaim.objects.filter(verify_token=token).first()
    if claim is None:
        return render(request, "survey/verify_invalid.html", status=404)

    if claim.status == PrizeClaim.Status.PENDING and claim.verify_expired:
        return render(request, "survey/verify_invalid.html", {"expired": True}, status=410)

    try:
        claim = _assign_prize(claim)
    except IntegrityError:
        # Another claim for this mailbox was verified first.
        return render(request, "survey/verify_invalid.html", {"duplicate": True}, status=409)

    return render(request, "survey/prize.html", {"claim": claim})
