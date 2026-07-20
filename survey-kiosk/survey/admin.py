import csv
import json
from datetime import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone

from .models import (
    Answer,
    Choice,
    Kiosk,
    PrizeClaim,
    PrizeCode,
    Question,
    Survey,
    SurveySession,
)
from .json_translate import SurveyTranslationError, import_survey_spec
from .question_types import QUESTION_TYPES, get_question_runtime_config
from .question_schema import SurveySchemaError, SurveySpec


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 0


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ("order", "text", "type", "included_in_short", "required")
    show_change_link = True


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "question_count")
    inlines = [QuestionInline]
    change_list_template = "admin/survey/survey/change_list.html"
    change_form_template = "admin/survey/survey/change_form.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/preview/",
                self.admin_site.admin_view(self.preview_chooser),
                name="survey_survey_preview_chooser",
            ),
            path(
                "<path:object_id>/preview/open/",
                self.admin_site.admin_view(self.preview_open),
                name="survey_survey_preview_open",
            ),
            path(
                "<path:object_id>/preview/all/<str:length>/",
                self.admin_site.admin_view(self.preview_all),
                name="survey_survey_preview_all",
            ),
            path(
                "<path:object_id>/preview/flow/<str:length>/<int:step>/",
                self.admin_site.admin_view(self.preview_flow),
                name="survey_survey_preview_flow",
            ),
            path(
                "upload/",
                self.admin_site.admin_view(self.upload_survey_json),
                name="survey_survey_upload",
            )
        ]
        return custom + urls

    def upload_survey_json(self, request):
        if request.method == "POST":
            upload = request.FILES.get("json_file")
            if upload is None:
                self.message_user(request, "Please choose a JSON file.", level=messages.ERROR)
            else:
                try:
                    payload = json.loads(upload.read().decode("utf-8"))
                    spec = SurveySpec.from_dict(payload)
                    result = import_survey_spec(spec, source_dir=settings.BASE_DIR / "imports")
                except UnicodeDecodeError:
                    self.message_user(
                        request,
                        "JSON file must be UTF-8 encoded.",
                        level=messages.ERROR,
                    )
                except json.JSONDecodeError as exc:
                    self.message_user(
                        request,
                        f"Invalid JSON: {exc.msg}",
                        level=messages.ERROR,
                    )
                except (SurveySchemaError, SurveyTranslationError) as exc:
                    self.message_user(request, str(exc), level=messages.ERROR)
                else:
                    self.message_user(
                        request,
                        (
                            f"Imported survey '{spec.name}' (id={result.survey_id}) with "
                            f"{result.question_count} question(s) and "
                            f"{result.choice_count} choice(s)."
                        ),
                        level=messages.SUCCESS,
                    )
                    return redirect("admin:survey_survey_changelist")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Upload survey JSON",
        }
        return render(request, "admin/survey/survey/upload.html", context)

    def _get_preview_survey(self, request, object_id):
        survey = self.get_object(request, object_id)
        if survey is None:
            raise PermissionDenied
        if not self.has_view_or_change_permission(request, obj=survey):
            raise PermissionDenied
        return survey

    def _preview_mode(self, request):
        mode = (request.GET.get("mode") or "all").strip().lower()
        return mode if mode in {"all", "flow"} else "all"

    def _preview_length(self, request):
        length = (request.GET.get("length") or SurveySession.Length.LONG).strip().lower()
        return length if length in SurveySession.Length.values else SurveySession.Length.LONG

    def _preview_questions(self, survey, length):
        return list(survey.questions_for(length).prefetch_related("choices"))

    def _renderable_questions(self, questions):
        renderable = []
        for q in questions:
            definition = QUESTION_TYPES[q.type]
            renderable.append(
                {
                    "question": q,
                    "question_template": definition.template_name,
                    "question_script": definition.script_path,
                    "question_config": get_question_runtime_config(q),
                }
            )
        return renderable

    def _preview_context(self, request, survey, mode, length):
        all_url = reverse("admin:survey_survey_preview_all", args=[survey.pk, length])
        flow_url = reverse("admin:survey_survey_preview_flow", args=[survey.pk, length, 1])
        open_params = urlencode({"mode": mode, "length": length})
        return {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": survey,
            "survey": survey,
            "mode": mode,
            "length": length,
            "mode_label": "All questions" if mode == "all" else "Participant flow",
            "length_label": "Short" if length == SurveySession.Length.SHORT else "Long",
            "open_url": reverse("admin:survey_survey_preview_open", args=[survey.pk]),
            "open_params": open_params,
            "all_url": all_url,
            "flow_url": flow_url,
            "question_changelist_url": reverse("admin:survey_question_changelist"),
            "change_url": reverse("admin:survey_survey_change", args=[survey.pk]),
            "empty_answer_value": {},
            "empty_selected_choice_ids": [],
        }

    def preview_chooser(self, request, object_id):
        survey = self._get_preview_survey(request, object_id)
        mode = self._preview_mode(request)
        length = self._preview_length(request)
        context = self._preview_context(request, survey, mode, length)
        context["title"] = f"Preview survey: {survey.name}"
        return render(request, "admin/survey/survey/preview_chooser.html", context)

    def preview_open(self, request, object_id):
        survey = self._get_preview_survey(request, object_id)
        mode = self._preview_mode(request)
        length = self._preview_length(request)
        if mode == "flow":
            return redirect("admin:survey_survey_preview_flow", survey.pk, length, 1)
        return redirect("admin:survey_survey_preview_all", survey.pk, length)

    def preview_all(self, request, object_id, length):
        survey = self._get_preview_survey(request, object_id)
        if length not in SurveySession.Length.values:
            raise PermissionDenied

        questions = self._preview_questions(survey, length)
        rendered_questions = self._renderable_questions(questions)
        scripts = sorted({item["question_script"] for item in rendered_questions if item["question_script"]})

        context = self._preview_context(request, survey, mode="all", length=length)
        context.update(
            {
                "title": f"Preview ({context['length_label']}) - {survey.name}",
                "questions": rendered_questions,
                "question_count": len(rendered_questions),
                "scripts": scripts,
            }
        )
        return render(request, "admin/survey/survey/preview_all.html", context)

    def preview_flow(self, request, object_id, length, step):
        survey = self._get_preview_survey(request, object_id)
        if length not in SurveySession.Length.values:
            raise PermissionDenied

        questions = self._preview_questions(survey, length)
        total = len(questions)
        if total == 0:
            context = self._preview_context(request, survey, mode="flow", length=length)
            context.update({"title": f"Preview ({context['length_label']}) - {survey.name}", "total": 0})
            return render(request, "admin/survey/survey/preview_flow.html", context)

        if step < 1 or step > total:
            return redirect("admin:survey_survey_preview_flow", survey.pk, length, 1)

        q = questions[step - 1]
        definition = QUESTION_TYPES[q.type]
        question_item = {
            "question": q,
            "question_template": definition.template_name,
            "question_script": definition.script_path,
            "question_config": get_question_runtime_config(q),
        }

        context = self._preview_context(request, survey, mode="flow", length=length)
        context.update(
            {
                "title": f"Preview ({context['length_label']}) - {survey.name}",
                "step": step,
                "total": total,
                "question_item": question_item,
            }
        )
        return render(request, "admin/survey/survey/preview_flow.html", context)

    @admin.display(description="Questions")
    def question_count(self, obj):
        return obj.questions.count()


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "survey", "type", "order", "included_in_short", "required")
    list_filter = ("survey", "type", "included_in_short")
    list_editable = ("order", "included_in_short")
    inlines = [ChoiceInline]


@admin.register(Kiosk)
class KioskAdmin(admin.ModelAdmin):
    list_display = ("name", "survey", "active", "rotate_seconds", "token_ttl_seconds")
    list_filter = ("active",)


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    readonly_fields = ("question", "rendered")
    fields = ("question", "rendered")
    can_delete = False

    @admin.display(description="Answer")
    def rendered(self, obj):
        return obj.display_value()

    def has_add_permission(self, request, obj=None):
        return False


def sessions_csv_response(queryset, filename="survey_sessions.csv"):
    """Render a SurveySession queryset to a CSV HttpResponse.

    One row per session; a stable column per question across the sessions'
    surveys. Shared by the bulk admin action and the date-range export view.
    """
    queryset = queryset.select_related("kiosk", "survey").prefetch_related(
        "answers__question", "answers__choices"
    )
    # Stable column set: all questions across the selected sessions' surveys.
    questions = list(
        Question.objects.filter(survey__sessions__in=queryset)
        .distinct()
        .order_by("survey_id", "order", "id")
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    base_cols = ["session_id", "kiosk", "survey", "length", "status", "created_at", "completed_at"]
    writer.writerow(base_cols + [f"Q{q.order}: {q.text}" for q in questions])

    for s in queryset:
        by_q = {a.question_id: a.display_value() for a in s.answers.all()}
        row = [
            str(s.id),
            s.kiosk.name,
            s.survey.name,
            s.length,
            s.status,
            s.created_at.isoformat(),
            s.completed_at.isoformat() if s.completed_at else "",
        ]
        row += [by_q.get(q.id, "") for q in questions]
        writer.writerow(row)
    return response


@admin.action(description="Export selected sessions to CSV")
def export_sessions_csv(modeladmin, request, queryset):
    return sessions_csv_response(queryset)


@admin.register(SurveySession)
class SurveySessionAdmin(admin.ModelAdmin):
    list_display = ("id", "kiosk", "length", "status", "consented", "created_at", "expires_at")
    list_filter = ("status", "length", "kiosk")
    readonly_fields = ("id", "created_at", "expires_at", "completed_at")
    inlines = [AnswerInline]
    date_hierarchy = "created_at"
    actions = [export_sessions_csv]
    change_list_template = "admin/survey/surveysession/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "export/",
                self.admin_site.admin_view(self.export_csv_view),
                name="survey_surveysession_export",
            )
        ]
        return custom + urls

    def export_csv_view(self, request):
        """Download all sessions as CSV, optionally limited to a created-at
        date range via ?start=YYYY-MM-DD&end=YYYY-MM-DD (either bound optional)."""
        qs = SurveySession.objects.all()
        start = (request.GET.get("start") or "").strip()
        end = (request.GET.get("end") or "").strip()
        name = "survey_sessions"
        try:
            if start:
                d = datetime.strptime(start, "%Y-%m-%d").date()
                qs = qs.filter(created_at__date__gte=d)
                name += f"_from_{start}"
            if end:
                d = datetime.strptime(end, "%Y-%m-%d").date()
                qs = qs.filter(created_at__date__lte=d)
                name += f"_to_{end}"
        except ValueError:
            self.message_user(
                request, "Invalid date; use YYYY-MM-DD.", level=messages.ERROR
            )
            return redirect("admin:survey_surveysession_changelist")
        return sessions_csv_response(qs.order_by("created_at"), filename=f"{name}.csv")

    def changelist_view(self, request, extra_context=None):
        stats = SurveySession.objects.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            active=Count("id", filter=Q(status="active")),
            expired=Count("id", filter=Q(status="expired")),
        )
        claims = PrizeClaim.objects.aggregate(
            total=Count("id"),
            verified=Count("id", filter=Q(status="verified")),
            pending=Count("id", filter=Q(status="pending")),
            pool_empty=Count("id", filter=Q(status="pool_empty")),
        )
        codes = {
            "total": PrizeCode.objects.count(),
            "assigned": PrizeCode.objects.filter(assigned=True).count(),
            "free": PrizeCode.objects.filter(assigned=False).count(),
        }
        total = stats["total"] or 0
        stats["completion_rate"] = (
            round(100 * stats["completed"] / total, 1) if total else 0.0
        )
        extra_context = extra_context or {}
        extra_context["summary"] = {"sessions": stats, "claims": claims, "codes": codes}
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(PrizeCode)
class PrizeCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "assigned", "assigned_to", "created_at")
    list_filter = ("assigned",)
    search_fields = ("code",)
    change_list_template = "admin/survey/prizecode/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "upload/",
                self.admin_site.admin_view(self.upload_codes),
                name="survey_prizecode_upload",
            )
        ]
        return custom + urls

    def upload_codes(self, request):
        if request.method == "POST":
            raw = request.POST.get("codes", "")
            candidates = [line.strip() for line in raw.splitlines() if line.strip()]
            existing = set(PrizeCode.objects.values_list("code", flat=True))
            created, skipped = 0, 0
            seen = set()
            for code in candidates:
                if code in existing or code in seen:
                    skipped += 1
                    continue
                PrizeCode.objects.create(code=code)
                seen.add(code)
                created += 1
            self.message_user(
                request,
                f"Added {created} new code(s); skipped {skipped} duplicate(s).",
                level=messages.SUCCESS,
            )
            return redirect("admin:survey_prizecode_changelist")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Upload prize codes",
        }
        return render(request, "admin/survey/prizecode/upload.html", context)


@admin.register(PrizeClaim)
class PrizeClaimAdmin(admin.ModelAdmin):
    list_display = ("email", "status", "prize_code", "created_at", "verified_at")
    list_filter = ("status",)
    search_fields = ("email",)
    readonly_fields = ("verify_token", "created_at", "verified_at")
