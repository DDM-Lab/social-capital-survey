from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Choice, Kiosk, PrizeClaim, PrizeCode, Question, Survey, SurveySession
from .tokens import mint_kiosk_token, verify_kiosk_token


def make_survey():
    survey = Survey.objects.create(name="T", consent_text="consent")
    q1 = Question.objects.create(
        survey=survey, text="Single?", type=Question.Type.SINGLE, order=1, included_in_short=True
    )
    Choice.objects.create(question=q1, text="A")
    Choice.objects.create(question=q1, text="B")
    q2 = Question.objects.create(
        survey=survey, text="Text?", type=Question.Type.SHORT_TEXT, order=2, included_in_short=True
    )
    return survey, [q1, q2]


class TokenTests(TestCase):
    def test_fresh_and_stale(self):
        token = mint_kiosk_token(7)
        self.assertEqual(verify_kiosk_token(token, max_age=15), 7)
        self.assertIsNone(verify_kiosk_token(token, max_age=-1))

    def test_tampered(self):
        self.assertIsNone(verify_kiosk_token(mint_kiosk_token(7) + "x", max_age=15))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RATELIMIT_ENABLE=False,
)
class FlowTests(TestCase):
    def setUp(self):
        self.survey, self.questions = make_survey()
        self.kiosk = Kiosk.objects.create(name="K", survey=self.survey)
        for i in range(3):
            PrizeCode.objects.create(code=f"C{i}")

    def _complete(self, username="jdoe"):
        r = self.client.get(f"/s/{mint_kiosk_token(self.kiosk.id)}")
        sid = r.headers["Location"].split("/")[2]
        self.client.post(f"/survey/{sid}/start", {"length": "short", "consent": "on"})
        self.client.post(f"/survey/{sid}/q/1", {"choice": self.questions[0].choices.first().id})
        self.client.post(f"/survey/{sid}/q/2", {"text": "hi"})
        self.client.post(f"/survey/{sid}/claim", {"username": username})
        return PrizeClaim.objects.get(session_id=sid)

    def test_scan_mints_unique_sessions(self):
        token = mint_kiosk_token(self.kiosk.id)
        self.client.get(f"/s/{token}")
        self.client.get(f"/s/{token}")
        self.assertEqual(SurveySession.objects.count(), 2)

    def test_expired_token_gone(self):
        with override_settings(TOKEN_TTL_SECONDS=-1):
            self.assertEqual(self.client.get(f"/s/{mint_kiosk_token(self.kiosk.id)}").status_code, 410)

    def test_qr_fragment_shows_target_url(self):
        from django.conf import settings

        r = self.client.get(f"/kiosk/{self.kiosk.id}/qr")
        self.assertEqual(r.status_code, 200)
        # The destination URL is shown below the QR so scanners can see it.
        self.assertContains(r, f"{settings.BASE_URL}/s/")

    def test_full_flow_assigns_code(self):
        claim = self._complete()
        self.assertEqual(claim.status, PrizeClaim.Status.PENDING)
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.get(f"/claim/verify/{claim.verify_token}")
        claim.refresh_from_db()
        self.assertEqual(claim.status, PrizeClaim.Status.VERIFIED)
        self.assertIsNotNone(claim.prize_code)
        self.assertContains(r, claim.prize_code.code)

    def test_verify_is_idempotent(self):
        claim = self._complete()
        self.client.get(f"/claim/verify/{claim.verify_token}")
        claim.refresh_from_db()
        first = claim.prize_code.code
        free_after = PrizeCode.objects.filter(assigned=False).count()
        self.client.get(f"/claim/verify/{claim.verify_token}")
        claim.refresh_from_db()
        self.assertEqual(claim.prize_code.code, first)
        self.assertEqual(PrizeCode.objects.filter(assigned=False).count(), free_after)

    def test_mailbox_dedup(self):
        claim = self._complete("alice")
        self.client.get(f"/claim/verify/{claim.verify_token}")  # verified
        # New session, same username -> blocked at claim
        r = self.client.get(f"/s/{mint_kiosk_token(self.kiosk.id)}")
        sid = r.headers["Location"].split("/")[2]
        self.client.post(f"/survey/{sid}/start", {"length": "short", "consent": "on"})
        self.client.post(f"/survey/{sid}/q/1", {"choice": self.questions[0].choices.first().id})
        self.client.post(f"/survey/{sid}/q/2", {"text": "hi"})
        resp = self.client.post(f"/survey/{sid}/claim", {"username": "alice"})
        self.assertContains(resp, "already claimed")
        self.assertFalse(PrizeClaim.objects.filter(session_id=sid).exists())

    def test_pool_empty(self):
        PrizeCode.objects.all().delete()
        claim = self._complete("bob")
        r = self.client.get(f"/claim/verify/{claim.verify_token}")
        claim.refresh_from_db()
        self.assertEqual(claim.status, PrizeClaim.Status.POOL_EMPTY)
        self.assertContains(r, "pool is currently empty")

    def test_session_expiry_blocks_survey(self):
        r = self.client.get(f"/s/{mint_kiosk_token(self.kiosk.id)}")
        sid = r.headers["Location"].split("/")[2]
        s = SurveySession.objects.get(pk=sid)
        s.expires_at = timezone.now() - timedelta(seconds=1)
        s.save()
        self.assertEqual(self.client.get(f"/survey/{sid}/start").status_code, 410)
        s.refresh_from_db()
        self.assertEqual(s.status, SurveySession.Status.EXPIRED)


class AdminExportTests(TestCase):
    """Admin CSV export of all sessions, optionally filtered by date range."""

    EXPORT_URL = "/admin/survey/surveysession/export/"

    def setUp(self):
        from django.contrib.auth.models import User

        self.survey, self.questions = make_survey()
        self.kiosk = Kiosk.objects.create(name="K", survey=self.survey)
        User.objects.create_superuser("boss", "boss@example.com", "pw")
        self.client.login(username="boss", password="pw")

    def _session_on(self, dt):
        s = SurveySession.objects.create(
            kiosk=self.kiosk, survey=self.survey, length="short", status="completed"
        )
        # created_at is auto_now_add; override via update() to backdate.
        SurveySession.objects.filter(pk=s.pk).update(created_at=dt)
        return s

    def test_export_all_sessions(self):
        from datetime import datetime, timezone as tz

        s_old = self._session_on(datetime(2026, 1, 1, tzinfo=tz.utc))
        s_new = self._session_on(datetime(2026, 6, 1, tzinfo=tz.utc))
        r = self.client.get(self.EXPORT_URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        body = r.content.decode()
        self.assertIn(str(s_old.id), body)
        self.assertIn(str(s_new.id), body)

    def test_export_filters_by_date_range(self):
        from datetime import datetime, timezone as tz

        s_old = self._session_on(datetime(2026, 1, 1, tzinfo=tz.utc))
        s_new = self._session_on(datetime(2026, 6, 1, tzinfo=tz.utc))
        r = self.client.get(self.EXPORT_URL + "?start=2026-05-01&end=2026-06-30")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn(str(s_old.id), body)
        self.assertIn(str(s_new.id), body)

    def test_export_requires_login(self):
        self.client.logout()
        r = self.client.get(self.EXPORT_URL)
        # Admin redirects anonymous users to the login page.
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])
