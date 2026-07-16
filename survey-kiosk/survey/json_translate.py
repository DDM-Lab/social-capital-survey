from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from django.db import transaction

from .models import Choice, Question, Survey
from .question_schema import (
    SurveySpec,
)
from .question_types import ImageGridQuestion, MultiChoiceQuestion, QUESTION_TYPES, SingleChoiceQuestion
from .question_types import MultiMatrixQuestion


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
            definition = QUESTION_TYPES[q.type]
            question = Question.objects.create(
                survey=survey,
                text=q.text,
                type=q.type,
                order=q.order,
                included_in_short=q.included_in_short,
                required=q.required,
                **definition.question_model_fields(q),
            )
            question_count += 1

            if isinstance(q, (SingleChoiceQuestion, MultiChoiceQuestion, MultiMatrixQuestion)):
                for choice in sorted(q.choices, key=lambda c: c.order):
                    Choice.objects.create(question=question, text=choice.text, order=choice.order)
                    choice_count += 1

            if isinstance(q, ImageGridQuestion):
                definition.persist_question(question, q, source_dir)

        return TranslationResult(
            survey_id=survey.id,
            question_count=question_count,
            choice_count=choice_count,
        )
