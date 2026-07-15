"""Delete survey data older than a retention window.

Retention is INDEFINITE by default for this deployment, so this command is NOT
scheduled. It exists so retention can be enforced later without code changes.

Examples:
    uv run python manage.py purge_data --days 90 --yes     # delete sessions older than 90 days
    uv run python manage.py purge_data --days 30 --emails-only --yes  # scrub emails only
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from survey.models import PrizeClaim, SurveySession


class Command(BaseCommand):
    help = "Purge sessions/claims older than --days (or scrub just emails)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, required=True, help="Age threshold in days.")
        parser.add_argument(
            "--emails-only",
            action="store_true",
            help="Only blank out claim email addresses; keep responses.",
        )
        parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")

    def handle(self, *args, **options):
        days = options["days"]
        if days < 0:
            raise CommandError("--days must be >= 0")
        cutoff = timezone.now() - timedelta(days=days)

        if options["emails_only"]:
            qs = PrizeClaim.objects.filter(created_at__lt=cutoff).exclude(email="")
            n = qs.count()
            if not self._confirm(options, f"scrub {n} email address(es)"):
                return
            updated = qs.update(email="")
            self.stdout.write(self.style.SUCCESS(f"Scrubbed {updated} email(s)."))
            return

        qs = SurveySession.objects.filter(created_at__lt=cutoff)
        n = qs.count()
        if not self._confirm(options, f"delete {n} session(s) and all their answers/claims"):
            return
        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {n} session(s) ({deleted} rows total)."))

    def _confirm(self, options, action):
        if options["yes"]:
            return True
        answer = input(f"About to {action}. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            self.stdout.write("Aborted.")
            return False
        return True
