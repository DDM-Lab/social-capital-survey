import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from survey.json_translate import SurveyTranslationError, import_survey_spec
from survey.question_schema import SurveySchemaError, SurveySpec


class Command(BaseCommand):
    help = "Import survey content from a local JSON file."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str)

    def handle(self, *args, **options):
        file_path = Path(options["file_path"]).expanduser().resolve()
        if not file_path.exists() or not file_path.is_file():
            raise CommandError(f"JSON file not found: {file_path}")

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            spec = SurveySpec.from_dict(payload)
            result = import_survey_spec(spec, source_dir=file_path.parent)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc.msg}") from exc
        except (SurveySchemaError, SurveyTranslationError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported survey '{spec.name}' (id={result.survey_id}) with "
                f"{result.question_count} question(s) and {result.choice_count} choice(s)."
            )
        )
