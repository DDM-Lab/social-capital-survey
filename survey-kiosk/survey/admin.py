import csv
from datetime import datetime

from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path
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
