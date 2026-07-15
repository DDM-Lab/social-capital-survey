from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction

from .models import Choice, Question, Survey
from .question_schema import (
    ImageGridQuestion,
    LikertQuestion,
    MultiChoiceQuestion,
    ShortTextQuestion,
    SingleChoiceQuestion,
    SurveySpec,
    resolve_local_image,
)


class SurveyTranslationError(ValueError):
    pass


@dataclass(frozen=True)
class TranslationResult:
    survey_id: int
    question_count: int
    choice_count: int


def import_survey_spec(spec: SurveySpec, source_dir: Path | None = None) -> TranslationResult:
    """Write SurveySpec into the same tables admin GUI authoring uses."""
    with transaction.atomic():
        survey, _ = Survey.objects.update_or_create(
            name=spec.name,
            defaults={"active": spec.active, "consent_text": spec.consent_text},
        )

        # Replace authored question bank for this survey in one operation.
        survey.questions.all().delete()

        question_count = 0
        choice_count = 0

        for q in spec.questions:
            question = Question.objects.create(
                survey=survey,
                text=q.text,
                type=q.type,
                order=q.order,
                included_in_short=q.included_in_short,
                required=q.required,
                **_question_type_fields(q),
            )
            question_count += 1

            if isinstance(q, (SingleChoiceQuestion, MultiChoiceQuestion)):
                for choice in sorted(q.choices, key=lambda c: c.order):
                    Choice.objects.create(question=question, text=choice.text, order=choice.order)
                    choice_count += 1

            if isinstance(q, ImageGridQuestion):
                _attach_image(question, q, source_dir)

        return TranslationResult(
            survey_id=survey.id,
            question_count=question_count,
            choice_count=choice_count,
        )


def _question_type_fields(q):
    if isinstance(q, LikertQuestion):
        return {
            "likert_min": q.likert_min,
            "likert_max": q.likert_max,
            "likert_min_label": q.likert_min_label,
            "likert_max_label": q.likert_max_label,
        }
    if isinstance(q, ImageGridQuestion):
        return {
            "grid_rows": q.grid_rows,
            "grid_cols": q.grid_cols,
        }
    if isinstance(q, (SingleChoiceQuestion, MultiChoiceQuestion, ShortTextQuestion)):
        return {}
    raise SurveyTranslationError(f"Unsupported question class: {type(q).__name__}")


def _attach_image(question: Question, q: ImageGridQuestion, source_dir: Path | None):
    image_path = resolve_local_image(q.grid_image, source_dir)
    if not image_path.exists() or not image_path.is_file():
        raise SurveyTranslationError(f"Image file not found: {image_path}")
    question.grid_image.save(image_path.name, ContentFile(image_path.read_bytes()), save=True)
