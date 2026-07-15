"""Flip lingering active sessions whose 20-minute window has passed to expired.

Intended to run frequently from cron, e.g. every minute:
    * * * * * cd /app && uv run python manage.py expire_sessions
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from survey.models import SurveySession


class Command(BaseCommand):
    help = "Mark active sessions past their expiry as expired."

    def handle(self, *args, **options):
        count = SurveySession.objects.filter(
            status=SurveySession.Status.ACTIVE, expires_at__lte=timezone.now()
        ).update(status=SurveySession.Status.EXPIRED)
        self.stdout.write(self.style.SUCCESS(f"Expired {count} session(s)."))
