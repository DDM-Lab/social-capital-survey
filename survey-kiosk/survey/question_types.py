from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.core.files.base import ContentFile


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

        questions = [parse_question(raw_question) for raw_question in raw_questions]
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


def resolve_local_image(path_value: str, source_dir: Path | None = None) -> Path:
    path = Path(path_value)
    if not path.is_absolute() and source_dir is not None:
        path = source_dir / path
    return path.resolve()


def parse_question(raw: dict[str, Any]) -> SurveyQuestion:
    if not isinstance(raw, dict):
        raise SurveySchemaError("Each question must be an object.")

    qtype = raw.get("type")
    definition = QUESTION_TYPES.get(qtype)
    if definition is None:
        raise SurveySchemaError(f"Unsupported question type: {qtype!r}")
    return definition.parse_question(raw)


class QuestionTypeDefinition:
    type_name: str
    question_class: type[SurveyQuestion]
    template_name: str = ""
    script_path: str | None = None

    def parse_question(self, raw: dict[str, Any]) -> SurveyQuestion:
        common = parse_common_fields(raw, expected_type=self.type_name)
        return self.build_question(common, raw)

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        raise NotImplementedError

    def question_model_fields(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        return {"config_json": self.question_config(question_spec)}

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        return {}

    def persist_question(self, question, question_spec: SurveyQuestion, source_dir: Path | None = None):
        return None

    def save_answer(self, answer, question, request) -> str | None:
        raise NotImplementedError

    def display_answer(self, answer) -> str:
        return ""

    def get_question_config(self, question) -> dict[str, Any]:
        return question.config_json or {}

    def get_answer_value(self, answer) -> dict[str, Any]:
        return answer.value_json or {}


def parse_common_fields(raw: dict[str, Any], expected_type: str) -> dict[str, Any]:
    text = raw.get("text")
    order = raw.get("order")
    included_in_short = raw.get("included_in_short", False)
    required = raw.get("required", True)

    if raw.get("type") != expected_type:
        raise SurveySchemaError(f"Expected question type '{expected_type}'.")
    if not isinstance(text, str) or not text.strip():
        raise SurveySchemaError("Question 'text' must be a non-empty string.")
    if not isinstance(order, int):
        raise SurveySchemaError("Question 'order' must be an integer.")
    if not isinstance(included_in_short, bool):
        raise SurveySchemaError("Question 'included_in_short' must be a boolean.")
    if not isinstance(required, bool):
        raise SurveySchemaError("Question 'required' must be a boolean.")

    return {
        "type": expected_type,
        "text": text.strip(),
        "order": order,
        "included_in_short": included_in_short,
        "required": required,
    }


class SingleChoiceDefinition(QuestionTypeDefinition):
    type_name = "single"
    question_class = SingleChoiceQuestion
    template_name = "survey/question_types/single.html"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        return SingleChoiceQuestion(**common, choices=parse_choices(raw, self.type_name))

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, SingleChoiceQuestion)
        return {
            "choices": [
                {"text": choice.text, "order": choice.order}
                for choice in sorted(question_spec.choices, key=lambda item: item.order)
            ]
        }

    def save_answer(self, answer, question, request) -> str | None:
        choice_id = request.POST.get("choice")
        choice = question.choices.filter(pk=choice_id).first() if choice_id else None
        if choice is None:
            return "Please select an option." if question.required else None
        answer.choices.set([choice])
        answer.value_json = {"choice_ids": [choice.id]}
        answer.save(update_fields=["value_json"])
        return None

    def display_answer(self, answer) -> str:
        return "; ".join(choice.text for choice in answer.choices.all())


class MultiChoiceDefinition(QuestionTypeDefinition):
    type_name = "multi"
    question_class = MultiChoiceQuestion
    template_name = "survey/question_types/multi.html"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        return MultiChoiceQuestion(**common, choices=parse_choices(raw, self.type_name))

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, MultiChoiceQuestion)
        return {
            "choices": [
                {"text": choice.text, "order": choice.order}
                for choice in sorted(question_spec.choices, key=lambda item: item.order)
            ]
        }

    def save_answer(self, answer, question, request) -> str | None:
        ids = request.POST.getlist("choices")
        chosen = list(question.choices.filter(pk__in=ids))
        if not chosen and question.required:
            return "Please select at least one option."
        answer.choices.set(chosen)
        answer.value_json = {"choice_ids": [choice.id for choice in chosen]}
        answer.save(update_fields=["value_json"])
        return None

    def display_answer(self, answer) -> str:
        return "; ".join(choice.text for choice in answer.choices.all())


class LikertDefinition(QuestionTypeDefinition):
    type_name = "likert"
    question_class = LikertQuestion
    template_name = "survey/question_types/likert.html"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
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

    def question_model_fields(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, LikertQuestion)
        return {"config_json": self.question_config(question_spec)}

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, LikertQuestion)
        return {
            "likert_min": question_spec.likert_min,
            "likert_max": question_spec.likert_max,
            "likert_min_label": question_spec.likert_min_label,
            "likert_max_label": question_spec.likert_max_label,
        }

    def save_answer(self, answer, question, request) -> str | None:
        raw = request.POST.get("likert")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return "Please choose a rating." if question.required else None
        config = self.get_question_config(question)
        if value not in range(config.get("likert_min", 0), config.get("likert_max", -1) + 1):
            return "Please choose a valid rating."
        answer.value_json = {"value": value}
        answer.save(update_fields=["value_json"])
        return None

    def display_answer(self, answer) -> str:
        value = self.get_answer_value(answer).get("value")
        return str(value) if value is not None else ""


class ShortTextDefinition(QuestionTypeDefinition):
    type_name = "short_text"
    question_class = ShortTextQuestion
    template_name = "survey/question_types/short_text.html"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        return ShortTextQuestion(**common)

    def save_answer(self, answer, question, request) -> str | None:
        text = (request.POST.get("text") or "").strip()
        if not text and question.required:
            return "Please enter a response."
        answer.value_json = {"text": text}
        answer.save(update_fields=["value_json"])
        return None

    def display_answer(self, answer) -> str:
        return self.get_answer_value(answer).get("text", "")


class ImageGridDefinition(QuestionTypeDefinition):
    type_name = "image_grid"
    question_class = ImageGridQuestion
    template_name = "survey/question_types/image_grid.html"
    script_path = "survey/grid.js"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
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

    def question_model_fields(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, ImageGridQuestion)
        return {"config_json": self.question_config(question_spec)}

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, ImageGridQuestion)
        return {
            "grid_image": question_spec.grid_image,
            "grid_rows": question_spec.grid_rows,
            "grid_cols": question_spec.grid_cols,
        }

    def persist_question(self, question, question_spec: SurveyQuestion, source_dir: Path | None = None):
        question_spec = ensure_question_type(question_spec, ImageGridQuestion)
        image_path = resolve_local_image(question_spec.grid_image, source_dir)
        if not image_path.exists() or not image_path.is_file():
            raise SurveySchemaError(f"Image file not found: {image_path}")
        question.grid_image.save(image_path.name, ContentFile(image_path.read_bytes()), save=True)

    def save_answer(self, answer, question, request) -> str | None:
        try:
            row = int(request.POST.get("grid_row"))
            col = int(request.POST.get("grid_col"))
        except (TypeError, ValueError):
            return "Please tap a cell on the image." if question.required else None
        config = self.get_question_config(question)
        if not (0 <= row < (config.get("grid_rows") or 0)) or not (0 <= col < (config.get("grid_cols") or 0)):
            return "That cell is out of range — please tap a cell on the image."
        answer.value_json = {"row": row, "col": col}
        answer.save(update_fields=["value_json"])
        return None

    def display_answer(self, answer) -> str:
        value = self.get_answer_value(answer)
        row = value.get("row")
        col = value.get("col")
        if row is None:
            return ""
        return f"{row},{col}"


def get_question_runtime_config(question) -> dict[str, Any]:
    return QUESTION_TYPES[question.type].get_question_config(question)


def get_answer_runtime_value(question, answer) -> dict[str, Any]:
    if answer is None:
        return {}
    return QUESTION_TYPES[question.type].get_answer_value(answer)


def parse_choices(raw: dict[str, Any], qtype: str) -> list[ChoiceSpec]:
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
    return choices


def ensure_question_type(question_spec: SurveyQuestion, expected_type: type[SurveyQuestion]):
    if not isinstance(question_spec, expected_type):
        raise SurveySchemaError(
            f"Expected {expected_type.__name__}, got {type(question_spec).__name__}."
        )
    return question_spec


QUESTION_TYPES: dict[str, QuestionTypeDefinition] = {
    definition.type_name: definition
    for definition in [
        SingleChoiceDefinition(),
        MultiChoiceDefinition(),
        LikertDefinition(),
        ShortTextDefinition(),
        ImageGridDefinition(),
    ]
}