from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SurveySchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ChoiceSpec:
    text: str
    order: int


@dataclass(frozen=True)
class SurveyQuestion:
    type: str
    text: str
    order: int
    included_in_short: bool = False
    required: bool = True


@dataclass(frozen=True)
class SingleChoiceQuestion(SurveyQuestion):
    choices: list[ChoiceSpec] = field(default_factory=list)


@dataclass(frozen=True)
class MultiChoiceQuestion(SurveyQuestion):
    choices: list[ChoiceSpec] = field(default_factory=list)


@dataclass(frozen=True)
class LikertQuestion(SurveyQuestion):
    likert_min: int = 1
    likert_max: int = 5
    likert_min_label: str = ""
    likert_max_label: str = ""


@dataclass(frozen=True)
class ShortTextQuestion(SurveyQuestion):
    pass


@dataclass(frozen=True)
class ImageGridQuestion(SurveyQuestion):
    grid_image: str = ""
    grid_rows: int = 0
    grid_cols: int = 0


@dataclass(frozen=True)
class SurveySpec:
    name: str
    consent_text: str
    active: bool
    questions: list[SurveyQuestion]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SurveySpec":
        if not isinstance(raw, dict):
            raise SurveySchemaError("Survey payload must be an object.")

        name = raw.get("name")
        consent_text = raw.get("consent_text", "")
        active = raw.get("active", True)
        raw_questions = raw.get("questions", [])

        if not isinstance(name, str) or not name.strip():
            raise SurveySchemaError("Survey 'name' must be a non-empty string.")
        if not isinstance(consent_text, str):
            raise SurveySchemaError("Survey 'consent_text' must be a string.")
        if not isinstance(active, bool):
            raise SurveySchemaError("Survey 'active' must be a boolean.")
        if not isinstance(raw_questions, list):
            raise SurveySchemaError("Survey 'questions' must be a list.")

        questions = [_parse_question(q) for q in raw_questions]
        orders = [q.order for q in questions]
        if len(orders) != len(set(orders)):
            raise SurveySchemaError("Question 'order' values must be unique.")

        questions.sort(key=lambda q: q.order)
        return cls(
            name=name.strip(),
            consent_text=consent_text,
            active=active,
            questions=questions,
        )


def _parse_question(raw: dict[str, Any]) -> SurveyQuestion:
    if not isinstance(raw, dict):
        raise SurveySchemaError("Each question must be an object.")

    qtype = raw.get("type")
    text = raw.get("text")
    order = raw.get("order")
    included_in_short = raw.get("included_in_short", False)
    required = raw.get("required", True)

    if qtype not in {"single", "multi", "likert", "short_text", "image_grid"}:
        raise SurveySchemaError(f"Unsupported question type: {qtype!r}")
    if not isinstance(text, str) or not text.strip():
        raise SurveySchemaError("Question 'text' must be a non-empty string.")
    if not isinstance(order, int):
        raise SurveySchemaError("Question 'order' must be an integer.")
    if not isinstance(included_in_short, bool):
        raise SurveySchemaError("Question 'included_in_short' must be a boolean.")
    if not isinstance(required, bool):
        raise SurveySchemaError("Question 'required' must be a boolean.")

    common = {
        "type": qtype,
        "text": text.strip(),
        "order": order,
        "included_in_short": included_in_short,
        "required": required,
    }

    if qtype in {"single", "multi"}:
        raw_choices = raw.get("choices", [])
        if not isinstance(raw_choices, list) or not raw_choices:
            raise SurveySchemaError(f"Question type '{qtype}' requires a non-empty 'choices' list.")
        choices: list[ChoiceSpec] = []
        for idx, raw_choice in enumerate(raw_choices, start=1):
            if not isinstance(raw_choice, dict):
                raise SurveySchemaError("Each choice must be an object.")
            choice_text = raw_choice.get("text")
            choice_order = raw_choice.get("order", idx)
            if not isinstance(choice_text, str) or not choice_text.strip():
                raise SurveySchemaError("Choice 'text' must be a non-empty string.")
            if not isinstance(choice_order, int):
                raise SurveySchemaError("Choice 'order' must be an integer.")
            choices.append(ChoiceSpec(text=choice_text.strip(), order=choice_order))
        if qtype == "single":
            return SingleChoiceQuestion(**common, choices=choices)
        return MultiChoiceQuestion(**common, choices=choices)

    if qtype == "likert":
        likert_min = raw.get("likert_min")
        likert_max = raw.get("likert_max")
        likert_min_label = raw.get("likert_min_label", "")
        likert_max_label = raw.get("likert_max_label", "")
        if not isinstance(likert_min, int) or not isinstance(likert_max, int):
            raise SurveySchemaError("Likert questions require integer 'likert_min' and 'likert_max'.")
        if likert_min > likert_max:
            raise SurveySchemaError("Likert 'likert_min' must be <= 'likert_max'.")
        if not isinstance(likert_min_label, str) or not isinstance(likert_max_label, str):
            raise SurveySchemaError("Likert labels must be strings.")
        return LikertQuestion(
            **common,
            likert_min=likert_min,
            likert_max=likert_max,
            likert_min_label=likert_min_label,
            likert_max_label=likert_max_label,
        )

    if qtype == "short_text":
        return ShortTextQuestion(**common)

    grid_image = raw.get("grid_image")
    grid_rows = raw.get("grid_rows")
    grid_cols = raw.get("grid_cols")
    if not isinstance(grid_image, str) or not grid_image.strip():
        raise SurveySchemaError("Image-grid questions require non-empty 'grid_image'.")
    if not isinstance(grid_rows, int) or grid_rows <= 0:
        raise SurveySchemaError("Image-grid 'grid_rows' must be an integer > 0.")
    if not isinstance(grid_cols, int) or grid_cols <= 0:
        raise SurveySchemaError("Image-grid 'grid_cols' must be an integer > 0.")

    return ImageGridQuestion(
        **common,
        grid_image=grid_image,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
    )


def resolve_local_image(path_value: str, source_dir: Path | None = None) -> Path:
    path = Path(path_value)
    if not path.is_absolute() and source_dir is not None:
        path = source_dir / path
    return path.resolve()
