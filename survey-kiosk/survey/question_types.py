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
class MatrixColumnSpec:
    key: str
    label: str
    kind: str = "choice"
    select_mode: str = "single"
    text_mode: str = "string"
    required: bool = False


@dataclass(frozen=True)
class MultiMatrixQuestion(SurveyQuestion):
    choices: list[ChoiceSpec] = field(default_factory=list)
    columns: list[MatrixColumnSpec] = field(default_factory=list)
    row_select_mode: str = "multi"
    char_limit: int | None = None


@dataclass(frozen=True)
class LikertQuestion(SurveyQuestion):
    likert_min: int = 1
    likert_max: int = 5
    likert_min_label: str = ""
    likert_max_label: str = ""


@dataclass(frozen=True)
class ShortTextQuestion(SurveyQuestion):
    field_count: int = 1
    char_limit: int | None = None
    field_required: list[bool] = field(default_factory=list)


@dataclass(frozen=True)
class ImageGridQuestion(SurveyQuestion):
    grid_image: str = ""
    grid_rows: int = 0
    grid_cols: int = 0


@dataclass(frozen=True)
class MatrixWithGridColumnSpec:
    key: str
    label: str
    kind: str
    text_mode: str = "string"
    required: bool = False


@dataclass(frozen=True)
class MatrixWithGridQuestion(SurveyQuestion):
    choices: list[ChoiceSpec] = field(default_factory=list)
    columns: list[MatrixWithGridColumnSpec] = field(default_factory=list)
    grid_image: str = ""
    grid_rows: int = 0
    grid_cols: int = 0
    char_limit: int | None = None
    row_required: list[bool] = field(default_factory=list)


@dataclass(frozen=True)
class GridPreferenceFlowQuestion(SurveyQuestion):
    grid_image: str = ""
    grid_rows: int = 0
    grid_cols: int = 0
    prompts: dict[str, str] = field(default_factory=dict)
    yes_reason_char_limit: int = 120
    no_reason_char_limit: int = 120
    require_no_branch_fields: bool = True


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
        field_count = raw.get("field_count", 1)
        char_limit = raw.get("char_limit")
        field_required = raw.get("field_required")
        if not isinstance(field_count, int) or field_count <= 0:
            raise SurveySchemaError("Short-text 'field_count' must be an integer > 0.")
        if char_limit is not None and (not isinstance(char_limit, int) or char_limit <= 0):
            raise SurveySchemaError("Short-text 'char_limit' must be an integer > 0 when provided.")
        if field_required is None:
            field_required = [common["required"]] * field_count
        if not isinstance(field_required, list) or len(field_required) != field_count:
            raise SurveySchemaError("Short-text 'field_required' must be a list with one value per field.")
        if any(not isinstance(item, bool) for item in field_required):
            raise SurveySchemaError("Short-text 'field_required' values must be booleans.")
        return ShortTextQuestion(
            **common,
            field_count=field_count,
            char_limit=char_limit,
            field_required=field_required,
        )

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, ShortTextQuestion)
        return {
            "field_count": question_spec.field_count,
            "char_limit": question_spec.char_limit,
            "field_required": question_spec.field_required,
        }

    def save_answer(self, answer, question, request) -> str | None:
        config = self.get_question_config(question)
        field_count = config.get("field_count", 1)
        char_limit = config.get("char_limit")
        field_required = config.get("field_required") or []

        values: list[str] = []
        for index in range(1, field_count + 1):
            raw_value = (request.POST.get("text") if field_count == 1 else request.POST.get(f"text_{index}")) or ""
            text = raw_value.strip()
            required = field_required[index - 1] if index - 1 < len(field_required) else question.required
            if not text and required:
                return f"Please enter a response for field {index}."
            if char_limit is not None and len(text) > char_limit:
                return f"Please keep field {index} to {char_limit} characters or fewer."
            values.append(text)

        answer.value_json = {"text": values[0] if field_count == 1 else None, "fields": values}
        answer.save(update_fields=["value_json"])
        return None

    def display_answer(self, answer) -> str:
        value = self.get_answer_value(answer)
        if value.get("fields"):
            return "; ".join(str(item) for item in value["fields"] if item not in (None, ""))
        return value.get("text", "")


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


class MatrixWithGridDefinition(QuestionTypeDefinition):
    type_name = "matrix_with_grid"
    question_class = MatrixWithGridQuestion
    template_name = "survey/question_types/matrix_with_grid.html"
    script_path = "survey/matrix_grid.js"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        choices = parse_choices(raw, self.type_name)
        columns = parse_matrix_with_grid_columns(raw)
        grid_image = raw.get("grid_image")
        grid_rows = raw.get("grid_rows")
        grid_cols = raw.get("grid_cols")
        char_limit = raw.get("char_limit")
        row_required = raw.get("row_required")

        if not isinstance(grid_image, str) or not grid_image.strip():
            raise SurveySchemaError("matrix_with_grid requires non-empty 'grid_image'.")
        if not isinstance(grid_rows, int) or grid_rows <= 0:
            raise SurveySchemaError("matrix_with_grid 'grid_rows' must be an integer > 0.")
        if not isinstance(grid_cols, int) or grid_cols <= 0:
            raise SurveySchemaError("matrix_with_grid 'grid_cols' must be an integer > 0.")
        if char_limit is not None and (not isinstance(char_limit, int) or char_limit <= 0):
            raise SurveySchemaError("matrix_with_grid 'char_limit' must be an integer > 0 when provided.")
        if row_required is None:
            row_required = [common["required"]] * len(choices)
        if not isinstance(row_required, list) or len(row_required) != len(choices):
            raise SurveySchemaError("matrix_with_grid 'row_required' must match choices length.")
        if any(not isinstance(item, bool) for item in row_required):
            raise SurveySchemaError("matrix_with_grid 'row_required' entries must be booleans.")

        return MatrixWithGridQuestion(
            **common,
            choices=choices,
            columns=columns,
            grid_image=grid_image,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            char_limit=char_limit,
            row_required=row_required,
        )

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, MatrixWithGridQuestion)
        return {
            "choices": [
                {"text": choice.text, "order": choice.order}
                for choice in sorted(question_spec.choices, key=lambda item: item.order)
            ],
            "columns": [
                {
                    "key": column.key,
                    "label": column.label,
                    "kind": column.kind,
                    "text_mode": column.text_mode,
                    "required": column.required,
                }
                for column in question_spec.columns
            ],
            "grid_image": question_spec.grid_image,
            "grid_rows": question_spec.grid_rows,
            "grid_cols": question_spec.grid_cols,
            "char_limit": question_spec.char_limit,
            "row_required": question_spec.row_required,
        }

    def persist_question(self, question, question_spec: SurveyQuestion, source_dir: Path | None = None):
        question_spec = ensure_question_type(question_spec, MatrixWithGridQuestion)
        image_path = resolve_local_image(question_spec.grid_image, source_dir)
        if not image_path.exists() or not image_path.is_file():
            raise SurveySchemaError(f"Image file not found: {image_path}")
        question.grid_image.save(image_path.name, ContentFile(image_path.read_bytes()), save=True)

    def save_answer(self, answer, question, request) -> str | None:
        config = self.get_question_config(question)
        columns = config.get("columns", [])
        row_required = config.get("row_required", [])
        char_limit = config.get("char_limit")
        grid_rows = config.get("grid_rows") or 0
        grid_cols = config.get("grid_cols") or 0

        rows = list(question.choices.all())
        required_by_row: dict[int, bool] = {}
        for index, choice in enumerate(rows):
            required_by_row[choice.id] = bool(row_required[index]) if index < len(row_required) else bool(question.required)

        map_columns = [column for column in columns if column.get("kind") == "map"]
        if len(map_columns) != 1:
            raise SurveySchemaError("matrix_with_grid requires exactly one map column.")
        map_column = map_columns[0]

        map_points_by_row: dict[str, dict[str, int]] = {}
        for choice in rows:
            row_id = choice.id
            enabled = request.POST.get(f"map_toggle_{row_id}") == "on"
            row_is_required = required_by_row[row_id] and bool(map_column.get("required", question.required))
            if row_is_required and not enabled:
                return f"Please mark a map location for row {choice.text}."
            if not enabled:
                continue

            try:
                row_value = int(request.POST.get(f"map_row_{row_id}"))
                col_value = int(request.POST.get(f"map_col_{row_id}"))
            except (TypeError, ValueError):
                return f"Please tap a map cell for row {choice.text}."

            if not (0 <= row_value < grid_rows and 0 <= col_value < grid_cols):
                return f"Map selection is out of range for row {choice.text}."

            map_points_by_row[str(row_id)] = {"row": row_value, "col": col_value}

        column_text_by_row: dict[str, dict[str, str | int]] = {}
        for column in columns:
            if column.get("kind") != "short_text":
                continue
            key = column.get("key")
            label = column.get("label") or key
            text_mode = column.get("text_mode", "string")
            column_required = bool(column.get("required", question.required))
            values_for_column: dict[str, str | int] = {}

            for choice in rows:
                raw_value = (request.POST.get(f"matrix_text_{key}_{choice.id}") or "").strip()
                row_is_required = required_by_row[choice.id]
                if not raw_value:
                    if row_is_required and column_required:
                        return f"Please enter a response for {label}: {choice.text}."
                    continue
                if char_limit is not None and len(raw_value) > char_limit:
                    return f"Please keep responses in {label} to {char_limit} characters or fewer."

                if text_mode == "integer":
                    try:
                        values_for_column[str(choice.id)] = int(raw_value)
                    except ValueError:
                        return f"Please enter a whole number for {label}: {choice.text}."
                else:
                    values_for_column[str(choice.id)] = raw_value

            column_text_by_row[key] = values_for_column

        answer.choices.clear()
        answer.value_json = {
            "map_points_by_row": map_points_by_row,
            "column_text_by_row": column_text_by_row,
        }
        answer.save(update_fields=["value_json"])
        return None

    def get_answer_value(self, answer) -> dict[str, Any]:
        value = answer.value_json or {}
        return {
            "map_points_by_row": value.get("map_points_by_row") or {},
            "column_text_by_row": value.get("column_text_by_row") or {},
        }

    def display_answer(self, answer) -> str:
        value = self.get_answer_value(answer)
        map_points = value.get("map_points_by_row", {})
        if not map_points:
            return ""
        labels_by_id = {str(choice.id): choice.text for choice in answer.question.choices.all()}
        parts: list[str] = []
        for row_id, point in map_points.items():
            row_label = labels_by_id.get(row_id, row_id)
            parts.append(f"{row_label}: ({point.get('row')},{point.get('col')})")
        return "; ".join(parts)


class GridPreferenceFlowDefinition(QuestionTypeDefinition):
    type_name = "grid_preference_flow"
    question_class = GridPreferenceFlowQuestion
    template_name = "survey/question_types/grid_preference_flow.html"
    script_path = "survey/grid_preference_flow.js"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        grid_image = raw.get("grid_image")
        grid_rows = raw.get("grid_rows")
        grid_cols = raw.get("grid_cols")
        prompts = raw.get("prompts") or {}
        yes_reason_char_limit = raw.get("yes_reason_char_limit", 120)
        no_reason_char_limit = raw.get("no_reason_char_limit", 120)
        require_no_branch_fields = raw.get("require_no_branch_fields", True)

        if not isinstance(grid_image, str) or not grid_image.strip():
            raise SurveySchemaError("grid_preference_flow requires non-empty 'grid_image'.")
        if not isinstance(grid_rows, int) or grid_rows <= 0:
            raise SurveySchemaError("grid_preference_flow 'grid_rows' must be an integer > 0.")
        if not isinstance(grid_cols, int) or grid_cols <= 0:
            raise SurveySchemaError("grid_preference_flow 'grid_cols' must be an integer > 0.")
        if not isinstance(prompts, dict):
            raise SurveySchemaError("grid_preference_flow 'prompts' must be an object.")
        for key in ["initial_grid", "preferred_yes_no", "yes_reason", "no_grid", "no_reason"]:
            value = prompts.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SurveySchemaError(f"grid_preference_flow prompt '{key}' must be a non-empty string.")
        if not isinstance(yes_reason_char_limit, int) or yes_reason_char_limit <= 0:
            raise SurveySchemaError("grid_preference_flow 'yes_reason_char_limit' must be an integer > 0.")
        if not isinstance(no_reason_char_limit, int) or no_reason_char_limit <= 0:
            raise SurveySchemaError("grid_preference_flow 'no_reason_char_limit' must be an integer > 0.")
        if not isinstance(require_no_branch_fields, bool):
            raise SurveySchemaError("grid_preference_flow 'require_no_branch_fields' must be a boolean.")

        return GridPreferenceFlowQuestion(
            **common,
            grid_image=grid_image,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            prompts=prompts,
            yes_reason_char_limit=yes_reason_char_limit,
            no_reason_char_limit=no_reason_char_limit,
            require_no_branch_fields=require_no_branch_fields,
        )

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, GridPreferenceFlowQuestion)
        return {
            "grid_image": question_spec.grid_image,
            "grid_rows": question_spec.grid_rows,
            "grid_cols": question_spec.grid_cols,
            "prompts": question_spec.prompts,
            "yes_reason_char_limit": question_spec.yes_reason_char_limit,
            "no_reason_char_limit": question_spec.no_reason_char_limit,
            "require_no_branch_fields": question_spec.require_no_branch_fields,
        }

    def persist_question(self, question, question_spec: SurveyQuestion, source_dir: Path | None = None):
        question_spec = ensure_question_type(question_spec, GridPreferenceFlowQuestion)
        image_path = resolve_local_image(question_spec.grid_image, source_dir)
        if not image_path.exists() or not image_path.is_file():
            raise SurveySchemaError(f"Image file not found: {image_path}")
        question.grid_image.save(image_path.name, ContentFile(image_path.read_bytes()), save=True)

    def save_answer(self, answer, question, request) -> str | None:
        config = self.get_question_config(question)
        rows = config.get("grid_rows") or 0
        cols = config.get("grid_cols") or 0

        try:
            initial_row = int(request.POST.get("initial_row"))
            initial_col = int(request.POST.get("initial_col"))
        except (TypeError, ValueError):
            return "Please tap a cell for your initial location."
        if not (0 <= initial_row < rows and 0 <= initial_col < cols):
            return "Initial location is out of range."

        preferred_today_raw = request.POST.get("preferred_today")
        if preferred_today_raw not in {"yes", "no"}:
            return "Please answer whether that spot was preferred today."
        preferred_today = preferred_today_raw == "yes"

        yes_reason = (request.POST.get("yes_reason") or "").strip()
        no_reason = (request.POST.get("no_reason") or "").strip()
        alternative_cell: dict[str, int] | None = None

        if preferred_today:
            if not yes_reason:
                return "Please explain why it was your preferred spot."
            if len(yes_reason) > (config.get("yes_reason_char_limit") or 120):
                return f"Please keep your response to {config.get('yes_reason_char_limit')} characters or fewer."
            no_reason = ""
        else:
            yes_reason = ""
            if config.get("require_no_branch_fields", True):
                try:
                    alt_row = int(request.POST.get("alternative_row"))
                    alt_col = int(request.POST.get("alternative_col"))
                except (TypeError, ValueError):
                    return "Please tap a preferred alternative location."
                if not (0 <= alt_row < rows and 0 <= alt_col < cols):
                    return "Preferred alternative location is out of range."
                if not no_reason:
                    return "Please explain why you preferred that location."
                if len(no_reason) > (config.get("no_reason_char_limit") or 120):
                    return f"Please keep your response to {config.get('no_reason_char_limit')} characters or fewer."
                alternative_cell = {"row": alt_row, "col": alt_col}

        answer.choices.clear()
        answer.value_json = {
            "initial_cell": {"row": initial_row, "col": initial_col},
            "preferred_today": preferred_today,
            "preferred_reason": yes_reason or None,
            "alternative_cell": alternative_cell,
            "alternative_reason": no_reason or None,
        }
        answer.save(update_fields=["value_json"])
        return None

    def get_answer_value(self, answer) -> dict[str, Any]:
        value = answer.value_json or {}
        return {
            "initial_cell": value.get("initial_cell"),
            "preferred_today": value.get("preferred_today"),
            "preferred_reason": value.get("preferred_reason") or "",
            "alternative_cell": value.get("alternative_cell"),
            "alternative_reason": value.get("alternative_reason") or "",
        }

    def display_answer(self, answer) -> str:
        value = self.get_answer_value(answer)
        initial = value.get("initial_cell") or {}
        preferred = value.get("preferred_today")
        preferred_label = "Yes" if preferred else "No"
        return f"Initial ({initial.get('row')},{initial.get('col')}), Preferred: {preferred_label}"


class MultiMatrixDefinition(QuestionTypeDefinition):
    type_name = "multi_matrix"
    question_class = MultiMatrixQuestion
    template_name = "survey/question_types/multi_matrix.html"

    def build_question(self, common: dict[str, Any], raw: dict[str, Any]) -> SurveyQuestion:
        char_limit = raw.get("char_limit")
        if char_limit is not None and (not isinstance(char_limit, int) or char_limit <= 0):
            raise SurveySchemaError("Multi-matrix 'char_limit' must be an integer > 0 when provided.")
        return MultiMatrixQuestion(
            **common,
            choices=parse_choices(raw, self.type_name),
            columns=parse_matrix_columns(raw),
            row_select_mode=parse_matrix_select_mode(raw, "row_select_mode", default="multi"),
            char_limit=char_limit,
        )

    def question_config(self, question_spec: SurveyQuestion) -> dict[str, Any]:
        question_spec = ensure_question_type(question_spec, MultiMatrixQuestion)
        return {
            "choices": [
                {"text": choice.text, "order": choice.order}
                for choice in sorted(question_spec.choices, key=lambda item: item.order)
            ],
            "columns": [
                {
                    "key": column.key,
                    "label": column.label,
                    "kind": column.kind,
                    "select_mode": column.select_mode,
                    "text_mode": column.text_mode,
                    "required": column.required,
                }
                for column in question_spec.columns
            ],
            "row_select_mode": question_spec.row_select_mode,
            "char_limit": question_spec.char_limit,
        }

    def save_answer(self, answer, question, request) -> str | None:
        config = self.get_question_config(question)
        columns = config.get("columns", [])
        row_select_mode = config.get("row_select_mode", "multi")
        char_limit = config.get("char_limit")
        allowed_choice_ids = set(question.choices.values_list("id", flat=True))
        labels_by_id = {choice.id: choice.text for choice in question.choices.all()}

        selected_by_column: dict[str, list[int]] = {}
        text_cells_by_column: dict[str, dict[str, str | int]] = {}
        selected_choice_ids: set[int] = set()

        for column in columns:
            key = column.get("key")
            label = column.get("label") or key
            kind = column.get("kind", "choice")
            select_mode = column.get("select_mode", "single")
            column_required = bool(column.get("required", question.required))

            if kind == "choice":
                posted_ids = request.POST.getlist(f"matrix_{key}")
                if not posted_ids:
                    if column_required:
                        return f"Please select at least one option in {label}."
                    selected_by_column[key] = []
                    continue

                try:
                    parsed_ids = [int(raw_id) for raw_id in posted_ids]
                except (TypeError, ValueError):
                    return f"Invalid selection in {label}."

                normalized_ids = list(dict.fromkeys(parsed_ids))
                if select_mode == "single" and len(normalized_ids) > 1:
                    return f"Please select only one option in {label}."

                invalid_ids = [choice_id for choice_id in normalized_ids if choice_id not in allowed_choice_ids]
                if invalid_ids:
                    return f"Invalid selection in {label}."

                selected_by_column[key] = normalized_ids
                selected_choice_ids.update(normalized_ids)
                continue

            if kind == "short_text":
                cell_values: dict[str, str | int] = {}
                for choice in question.choices.all():
                    field_name = f"matrix_text_{key}_{choice.id}"
                    raw_value = (request.POST.get(field_name) or "").strip()
                    if not raw_value:
                        if column_required:
                            return f"Please enter a response for {label}: {choice.text}."
                        continue
                    if char_limit is not None and len(raw_value) > char_limit:
                        return f"Please keep responses in {label} to {char_limit} characters or fewer."
                    text_mode = column.get("text_mode", "string")
                    if text_mode == "integer":
                        try:
                            cell_values[str(choice.id)] = int(raw_value)
                        except ValueError:
                            return f"Please enter a whole number for {label}: {choice.text}."
                    else:
                        cell_values[str(choice.id)] = raw_value
                text_cells_by_column[key] = cell_values
                continue

            raise SurveySchemaError(f"Unsupported matrix column kind: {kind!r}.")

        row_occurrence_count: dict[int, int] = {}
        for selected_ids in selected_by_column.values():
            for choice_id in selected_ids:
                row_occurrence_count[choice_id] = row_occurrence_count.get(choice_id, 0) + 1
        if row_select_mode == "single":
            violating_ids = [choice_id for choice_id, count in row_occurrence_count.items() if count > 1]
            if violating_ids:
                row_label = labels_by_id.get(violating_ids[0], "a row")
                return f"Please select only one column for row {row_label}."

        answer.choices.set(question.choices.filter(pk__in=selected_choice_ids))
        answer.value_json = {"columns": selected_by_column}
        if text_cells_by_column:
            answer.value_json["text_cells"] = text_cells_by_column
        answer.save(update_fields=["value_json"])
        return None

    def get_answer_value(self, answer) -> dict[str, Any]:
        value = answer.value_json or {}
        columns = value.get("columns") or {}
        text_cells = value.get("text_cells") or {}
        selected_keys: list[str] = []
        for column_key, choice_ids in columns.items():
            if not isinstance(column_key, str) or not isinstance(choice_ids, list):
                continue
            for choice_id in choice_ids:
                if isinstance(choice_id, int):
                    selected_keys.append(f"{column_key}:{choice_id}")
        return {"columns": columns, "text_cells": text_cells, "selected_keys": selected_keys}

    def display_answer(self, answer) -> str:
        config = self.get_question_config(answer.question)
        value = self.get_answer_value(answer)
        selected_by_column = value.get("columns", {})
        text_cells = value.get("text_cells", {})
        labels_by_id = {choice.id: choice.text for choice in answer.question.choices.all()}

        rendered_columns: list[str] = []
        for column in config.get("columns", []):
            key = column.get("key")
            label = column.get("label") or key
            if column.get("kind", "choice") == "short_text":
                cell_map = text_cells.get(key, {})
                if not isinstance(cell_map, dict):
                    continue
                rendered_cells: list[str] = []
                for choice in answer.question.choices.all():
                    raw_value = cell_map.get(str(choice.id))
                    if raw_value in (None, ""):
                        continue
                    rendered_cells.append(f"{choice.text}: {raw_value}")
                if rendered_cells:
                    rendered_columns.append(f"{label}: {', '.join(rendered_cells)}")
                continue

            selected_ids = selected_by_column.get(key, [])
            selected_labels = [labels_by_id[choice_id] for choice_id in selected_ids if choice_id in labels_by_id]
            if selected_labels:
                rendered_columns.append(f"{label}: {', '.join(selected_labels)}")
        return "; ".join(rendered_columns)


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


def parse_matrix_columns(raw: dict[str, Any]) -> list[MatrixColumnSpec]:
    raw_columns = raw.get("columns", [])
    if not isinstance(raw_columns, list) or not raw_columns:
        raise SurveySchemaError("Question type 'multi_matrix' requires a non-empty 'columns' list.")

    columns: list[MatrixColumnSpec] = []
    keys_seen: set[str] = set()
    for raw_column in raw_columns:
        if not isinstance(raw_column, dict):
            raise SurveySchemaError("Each column must be an object.")
        key = raw_column.get("key")
        label = raw_column.get("label")
        select_mode = raw_column.get("select_mode", "single")

        if not isinstance(key, str) or not key.strip():
            raise SurveySchemaError("Column 'key' must be a non-empty string.")
        key = key.strip()
        if not isinstance(label, str) or not label.strip():
            raise SurveySchemaError("Column 'label' must be a non-empty string.")
        if key in keys_seen:
            raise SurveySchemaError("Column 'key' values must be unique.")

        kind = raw_column.get("kind", "choice")
        text_mode = raw_column.get("text_mode", "string")
        required = raw_column.get("required", False)
        if not isinstance(kind, str) or kind not in {"choice", "short_text"}:
            raise SurveySchemaError("Column 'kind' must be 'choice' or 'short_text'.")
        if not isinstance(required, bool):
            raise SurveySchemaError("Column 'required' must be a boolean.")
        if kind == "choice":
            if not isinstance(select_mode, str) or select_mode not in {"single", "multi"}:
                raise SurveySchemaError("Column 'select_mode' must be 'single' or 'multi'.")
            text_mode = "string"
        else:
            if select_mode not in {None, "", "single"}:
                raise SurveySchemaError("Short-text columns do not use 'select_mode'.")
            if not isinstance(text_mode, str) or text_mode not in {"string", "integer"}:
                raise SurveySchemaError("Short-text columns require 'text_mode' of 'string' or 'integer'.")
            select_mode = "single"

        keys_seen.add(key)
        columns.append(
            MatrixColumnSpec(
                key=key,
                label=label.strip(),
                kind=kind,
                select_mode=select_mode,
                text_mode=text_mode,
                required=required,
            )
        )
    return columns


def parse_matrix_select_mode(raw: dict[str, Any], field_name: str, default: str) -> str:
    value = raw.get(field_name, default)
    if not isinstance(value, str) or value not in {"single", "multi"}:
        raise SurveySchemaError(
            f"{field_name!r} must be 'single' or 'multi'."
        )
    return value


def parse_matrix_with_grid_columns(raw: dict[str, Any]) -> list[MatrixWithGridColumnSpec]:
    raw_columns = raw.get("columns", [])
    if not isinstance(raw_columns, list) or not raw_columns:
        raise SurveySchemaError("matrix_with_grid requires a non-empty 'columns' list.")

    columns: list[MatrixWithGridColumnSpec] = []
    keys_seen: set[str] = set()
    map_count = 0
    for raw_column in raw_columns:
        if not isinstance(raw_column, dict):
            raise SurveySchemaError("Each matrix_with_grid column must be an object.")
        key = raw_column.get("key")
        label = raw_column.get("label")
        kind = raw_column.get("kind")
        text_mode = raw_column.get("text_mode", "string")
        required = raw_column.get("required", False)
        select_mode = raw_column.get("select_mode")

        if not isinstance(key, str) or not key.strip():
            raise SurveySchemaError("matrix_with_grid column 'key' must be a non-empty string.")
        key = key.strip()
        if key in keys_seen:
            raise SurveySchemaError("matrix_with_grid column 'key' values must be unique.")
        if not isinstance(label, str) or not label.strip():
            raise SurveySchemaError("matrix_with_grid column 'label' must be a non-empty string.")
        if not isinstance(kind, str) or kind not in {"map", "short_text"}:
            raise SurveySchemaError("matrix_with_grid column 'kind' must be 'map' or 'short_text'.")
        if not isinstance(required, bool):
            raise SurveySchemaError("matrix_with_grid column 'required' must be a boolean.")

        if kind == "map":
            map_count += 1
            text_mode = "string"
            if select_mode not in {None, ""}:
                raise SurveySchemaError("map columns do not use 'select_mode'.")
        else:
            if select_mode not in {None, "", "single"}:
                raise SurveySchemaError("short_text columns do not use 'select_mode'.")
            if not isinstance(text_mode, str) or text_mode not in {"string", "integer"}:
                raise SurveySchemaError("short_text columns require text_mode 'string' or 'integer'.")

        keys_seen.add(key)
        columns.append(
            MatrixWithGridColumnSpec(
                key=key,
                label=label.strip(),
                kind=kind,
                text_mode=text_mode,
                required=required,
            )
        )

    if map_count != 1:
        raise SurveySchemaError("matrix_with_grid requires exactly one column with kind 'map'.")
    return columns


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
        MultiMatrixDefinition(),
        MatrixWithGridDefinition(),
        GridPreferenceFlowDefinition(),
        LikertDefinition(),
        ShortTextDefinition(),
        ImageGridDefinition(),
    ]
}