"""Seed placeholder content for development and testing.

Creates one Survey with 15 placeholder questions (first 5 flagged short),
covering all five question types, a Kiosk, and a small prize-code pool.
Idempotent: re-running clears and recreates the demo survey/kiosk.
"""

from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

from survey.models import Choice, Kiosk, PrizeCode, Question, Survey

DEMO_SURVEY = "Demo Survey (placeholder)"
DEMO_KIOSK = "Lobby Kiosk (demo)"


def _grid_image(rows, cols, size=600):
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)
    for r in range(rows + 1):
        y = int(r * size / rows)
        d.line([(0, y), (size, y)], fill="black", width=2)
    for c in range(cols + 1):
        x = int(c * size / cols)
        d.line([(x, 0), (x, size)], fill="black", width=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return ContentFile(buf.getvalue(), name="demo_grid.png")


def _choice_config(choice_texts):
    return {"choices": [{"text": text, "order": order} for order, text in enumerate(choice_texts)]}


def _likert_config(min_value, max_value, min_label="", max_label=""):
    return {
        "likert_min": min_value,
        "likert_max": max_value,
        "likert_min_label": min_label,
        "likert_max_label": max_label,
    }


def _grid_config(grid_image, rows, cols):
    return {"grid_image": grid_image, "grid_rows": rows, "grid_cols": cols}


class Command(BaseCommand):
    help = "Create placeholder survey content for development."

    def handle(self, *args, **options):
        # Update the demo survey in place rather than deleting it: Kiosk.survey and
        # SurveySession.survey are on_delete=PROTECT, so deleting a referenced Survey
        # raises ProtectedError. Clearing its questions (CASCADE) lets us re-seed
        # content without ever removing the protected Survey/Kiosk rows.
        survey, _ = Survey.objects.update_or_create(
            name=DEMO_SURVEY,
            defaults={
                "active": True,
                "consent_text": "[PLACEHOLDER IRB CONSENT TEXT — paste approved wording here.]",
            },
        )
        survey.questions.all().delete()

        order = 0

        def add(text, qtype, short=False, **kw):
            nonlocal order
            order += 1
            return Question.objects.create(
                survey=survey,
                text=text,
                type=qtype,
                order=order,
                included_in_short=short,
                **kw,
            )

        # First 5 -> included in short.
        q1 = add("Placeholder single-choice question 1?", Question.Type.SINGLE, short=True)
        for i, t in enumerate(["Option A", "Option B", "Option C"]):
            Choice.objects.create(question=q1, text=t, order=i)
        q1.config_json = _choice_config(["Option A", "Option B", "Option C"])
        q1.save(update_fields=["config_json"])

        q2 = add("Placeholder multiple-choice question 2?", Question.Type.MULTI, short=True)
        for i, t in enumerate(["Red", "Green", "Blue", "Yellow"]):
            Choice.objects.create(question=q2, text=t, order=i)
        q2.config_json = _choice_config(["Red", "Green", "Blue", "Yellow"])
        q2.save(update_fields=["config_json"])

        q3 = add(
            "Placeholder Likert question 3?",
            Question.Type.LIKERT,
            short=True,
        )
        q3.config_json = _likert_config(1, 5, "Strongly disagree", "Strongly agree")
        q3.save(update_fields=["config_json"])

        add("Placeholder short-text question 4?", Question.Type.SHORT_TEXT, short=True)

        q5 = add(
            "Placeholder image-grid question 5 — tap a cell.",
            Question.Type.IMAGE_GRID,
            short=True,
        )
        q5.grid_image.save("demo_grid.png", _grid_image(4, 6), save=True)
        q5.config_json = _grid_config("demo_grid.png", 4, 6)
        q5.save(update_fields=["config_json"])

        # Remaining 10 -> long only.
        for n in range(6, 16):
            qt = [
                Question.Type.SINGLE,
                Question.Type.MULTI,
                Question.Type.LIKERT,
                Question.Type.SHORT_TEXT,
            ][n % 4]
            q = add(f"Placeholder question {n}?", qt)
            if qt in (Question.Type.SINGLE, Question.Type.MULTI):
                for i, t in enumerate(["Choice 1", "Choice 2", "Choice 3"]):
                    Choice.objects.create(question=q, text=t, order=i)
                q.config_json = _choice_config(["Choice 1", "Choice 2", "Choice 3"])
            elif qt == Question.Type.LIKERT:
                q.config_json = _likert_config(1, 5, "Low", "High")
            q.save(update_fields=["config_json"])

        kiosk, _ = Kiosk.objects.update_or_create(
            name=DEMO_KIOSK, defaults={"survey": survey, "active": True}
        )

        # Small prize-code pool for testing.
        existing = set(PrizeCode.objects.values_list("code", flat=True))
        for i in range(1, 6):
            code = f"DEMO-CODE-{i:03d}"
            if code not in existing:
                PrizeCode.objects.create(code=code)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded '{survey.name}' (15 questions, 5 short), kiosk id={kiosk.id}, "
                f"and {PrizeCode.objects.filter(assigned=False).count()} unassigned prize codes."
            )
        )
