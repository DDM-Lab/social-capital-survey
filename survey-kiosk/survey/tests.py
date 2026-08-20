from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .json_translate import import_survey_spec
from .models import (
    Choice,
    Kiosk,
    PrizeClaim,
    PrizeCode,
    Question,
    Receipt,
    Survey,
    SurveySession,
)
from .question_schema import SurveySchemaError, SurveySpec
from .question_types import get_answer_runtime_value, get_question_runtime_config
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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RATELIMIT_ENABLE=False,
)
class EntryFlowTests(TestCase):
    """New AndrewID-gated entry: enter AndrewID -> choose kiosk vs phone."""

    def setUp(self):
        self.survey, self.questions = make_survey()
        self.kiosk = Kiosk.objects.create(name="K", survey=self.survey)

    def _enter(self, andrew="jdoe"):
        return self.client.post(f"/kiosk/{self.kiosk.id}/enter", {"username": andrew})

    def test_kiosk_landing_shows_andrewid_form(self):
        r = self.client.get(f"/kiosk/{self.kiosk.id}/")
        self.assertEqual(r.status_code, 200)
        # The entry form shows the domain suffix so people know what's appended.
        self.assertContains(r, "andrew.cmu.edu")

    def test_entry_creates_identified_session(self):
        r = self._enter("jdoe")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SurveySession.objects.count(), 1)
        s = SurveySession.objects.get()
        self.assertEqual(s.andrew_id, "jdoe")
        self.assertEqual(s.email, "jdoe@andrew.cmu.edu")
        self.assertTrue(s.is_identified)
        self.assertIn(f"/survey/{s.id}/channel", r.headers["Location"])

    def test_andrewid_is_normalized(self):
        self._enter("  JDoe@andrew.cmu.edu ")
        s = SurveySession.objects.get()
        self.assertEqual(s.andrew_id, "jdoe")

    def test_invalid_andrewid_rejected(self):
        r = self.client.post(f"/kiosk/{self.kiosk.id}/enter", {"username": "bad id!"})
        self.assertEqual(SurveySession.objects.count(), 0)
        self.assertContains(r, "unsupported characters", status_code=400)

    def test_reentry_resumes_live_session(self):
        self._enter("jdoe")
        self._enter("jdoe")
        # Re-entering the same AndrewID reuses the live session; no duplicate.
        self.assertEqual(SurveySession.objects.count(), 1)

    def test_kiosk_channel_starts_survey(self):
        self._enter("jdoe")
        s = SurveySession.objects.get()
        r = self.client.post(f"/survey/{s.id}/channel", {"channel": "kiosk"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"/survey/{s.id}/start", r.headers["Location"])

    def test_phone_channel_emails_link_and_shows_qr(self):
        self._enter("jdoe")
        s = SurveySession.objects.get()
        r = self.client.post(f"/survey/{s.id}/channel", {"channel": "phone"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("jdoe@andrew.cmu.edu", mail.outbox[0].to)
        # The personal survey link appears in the email and on the screen.
        self.assertIn(f"/survey/{s.id}/start", mail.outbox[0].body)
        self.assertContains(r, f"/survey/{s.id}/start")

    def test_channel_requires_a_choice(self):
        self._enter("jdoe")
        s = SurveySession.objects.get()
        r = self.client.post(f"/survey/{s.id}/channel", {})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_anonymous_scan_still_works(self):
        # The legacy anonymous entry is kept as a fallback and stays identity-less.
        r = self.client.get(f"/s/{mint_kiosk_token(self.kiosk.id)}")
        sid = r.headers["Location"].split("/")[2]
        s = SurveySession.objects.get(pk=sid)
        self.assertEqual(s.andrew_id, "")
        self.assertFalse(s.is_identified)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RATELIMIT_ENABLE=False,
)
class ReceiptVerifyTests(TestCase):
    """Verify-every-session: completing an identified survey emails a magic link
    that must be clicked before a receipt is granted."""

    def setUp(self):
        self.survey, self.questions = make_survey()
        self.kiosk = Kiosk.objects.create(name="K", survey=self.survey)

    def _complete_identified(self, andrew="jdoe"):
        self.client.post(f"/kiosk/{self.kiosk.id}/enter", {"username": andrew})
        s = SurveySession.objects.get(andrew_id=andrew)
        self.client.post(f"/survey/{s.id}/channel", {"channel": "kiosk"})
        self.client.post(f"/survey/{s.id}/start", {"length": "short", "consent": "on"})
        self.client.post(f"/survey/{s.id}/q/1", {"choice": self.questions[0].choices.first().id})
        r = self.client.post(f"/survey/{s.id}/q/2", {"text": "hi"})
        s.refresh_from_db()
        return s, r

    def test_completion_creates_receipt_and_emails_link(self):
        s, r = self._complete_identified()
        self.assertEqual(s.status, SurveySession.Status.COMPLETED)
        receipt = Receipt.objects.get(session=s)
        self.assertEqual(receipt.status, Receipt.Status.PENDING)
        self.assertEqual(receipt.email, "jdoe@andrew.cmu.edu")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"/receipt/verify/{receipt.verify_token}", mail.outbox[0].body)
        self.assertRedirects(r, f"/survey/{s.id}/verify-sent")

    def test_verify_sent_screen_shows_email(self):
        s, _ = self._complete_identified()
        r = self.client.get(f"/survey/{s.id}/verify-sent")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "jdoe@andrew.cmu.edu")

    def test_magic_link_verifies_receipt(self):
        s, _ = self._complete_identified()
        receipt = Receipt.objects.get(session=s)
        r = self.client.get(f"/receipt/verify/{receipt.verify_token}")
        self.assertEqual(r.status_code, 200)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.VERIFIED)
        self.assertIsNotNone(receipt.verified_at)

    def test_verify_is_idempotent(self):
        s, _ = self._complete_identified()
        receipt = Receipt.objects.get(session=s)
        self.client.get(f"/receipt/verify/{receipt.verify_token}")
        first = Receipt.objects.get(pk=receipt.pk).verified_at
        self.client.get(f"/receipt/verify/{receipt.verify_token}")
        self.assertEqual(Receipt.objects.get(pk=receipt.pk).verified_at, first)

    def test_invalid_token(self):
        self.assertEqual(self.client.get("/receipt/verify/nope").status_code, 404)

    def test_expired_token(self):
        s, _ = self._complete_identified()
        receipt = Receipt.objects.get(session=s)
        receipt.verify_expires_at = timezone.now() - timedelta(seconds=1)
        receipt.save(update_fields=["verify_expires_at"])
        r = self.client.get(f"/receipt/verify/{receipt.verify_token}")
        self.assertEqual(r.status_code, 410)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.PENDING)

    def test_anonymous_completion_still_uses_claim(self):
        r = self.client.get(f"/s/{mint_kiosk_token(self.kiosk.id)}")
        sid = r.headers["Location"].split("/")[2]
        self.client.post(f"/survey/{sid}/start", {"length": "short", "consent": "on"})
        self.client.post(f"/survey/{sid}/q/1", {"choice": self.questions[0].choices.first().id})
        r2 = self.client.post(f"/survey/{sid}/q/2", {"text": "hi"})
        self.assertRedirects(r2, f"/survey/{sid}/claim")
        self.assertFalse(Receipt.objects.filter(session_id=sid).exists())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RATELIMIT_ENABLE=False,
)
class ReceiptPrintTests(TestCase):
    """Returning to a kiosk with a verified receipt prints it (via the preview
    backend), subject to the configurable daily cap."""

    def setUp(self):
        self.survey, self.questions = make_survey()
        self.kiosk = Kiosk.objects.create(name="K", survey=self.survey)

    def _enter(self, andrew):
        return self.client.post(f"/kiosk/{self.kiosk.id}/enter", {"username": andrew})

    def _newest_session(self, andrew):
        return SurveySession.objects.filter(andrew_id=andrew).order_by("-created_at").first()

    def _complete(self, andrew):
        self._enter(andrew)
        s = self._newest_session(andrew)
        self.client.post(f"/survey/{s.id}/channel", {"channel": "kiosk"})
        self.client.post(f"/survey/{s.id}/start", {"length": "short", "consent": "on"})
        self.client.post(f"/survey/{s.id}/q/1", {"choice": self.questions[0].choices.first().id})
        self.client.post(f"/survey/{s.id}/q/2", {"text": "hi"})
        return Receipt.objects.get(session=s)

    def _verified_receipt(self, andrew="jdoe"):
        receipt = self._complete(andrew)
        self.client.get(f"/receipt/verify/{receipt.verify_token}")
        receipt.refresh_from_db()
        return receipt

    def test_verified_receipt_prints_on_return(self):
        receipt = self._verified_receipt("jdoe")
        r = self._enter("jdoe")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "printed")
        receipt.refresh_from_db()
        self.assertIsNotNone(receipt.printed_at)

    def test_receipt_shows_andrewid(self):
        self._verified_receipt("jdoe")
        r = self._enter("jdoe")
        self.assertContains(r, "jdoe")

    def test_unverified_receipt_does_not_print(self):
        receipt = self._complete("amy")  # completed but not verified
        s = receipt.session
        r = self._enter("amy")
        self.assertRedirects(r, f"/survey/{s.id}/verify-sent")
        receipt.refresh_from_db()
        self.assertIsNone(receipt.printed_at)

    @override_settings(DAILY_PRIZE_LIMIT=1)
    def test_daily_cap_blocks_second_receipt(self):
        r1 = self._verified_receipt("bob")
        self._enter("bob")
        r1.refresh_from_db()
        self.assertIsNotNone(r1.printed_at)
        r2 = self._verified_receipt("bob")
        resp = self._enter("bob")
        self.assertContains(resp, "limit")
        r2.refresh_from_db()
        self.assertIsNone(r2.printed_at)

    @override_settings(DAILY_PRIZE_LIMIT=2)
    def test_daily_cap_is_configurable(self):
        r1 = self._verified_receipt("carol")
        self._enter("carol")
        r2 = self._verified_receipt("carol")
        self._enter("carol")
        self.assertIsNotNone(Receipt.objects.get(pk=r1.pk).printed_at)
        self.assertIsNotNone(Receipt.objects.get(pk=r2.pk).printed_at)

    def test_already_printed_receipt_not_reprinted(self):
        receipt = self._verified_receipt("dave")
        self._enter("dave")
        printed_at = Receipt.objects.get(pk=receipt.pk).printed_at
        self._enter("dave")  # no unprinted verified receipt remains
        self.assertEqual(Receipt.objects.get(pk=receipt.pk).printed_at, printed_at)


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


class JsonImportTests(TestCase):
    def test_valid_import_creates_expected_rows(self):
        payload = {
            "name": "JSON Survey",
            "consent_text": "Consent text",
            "active": True,
            "questions": [
                {
                    "type": "single",
                    "order": 1,
                    "text": "Pick one",
                    "included_in_short": True,
                    "required": True,
                    "choices": [
                        {"text": "A", "order": 1},
                        {"text": "B", "order": 2},
                    ],
                },
                {
                    "type": "likert",
                    "order": 2,
                    "text": "Rate this",
                    "included_in_short": True,
                    "required": True,
                    "likert_min": 1,
                    "likert_max": 5,
                    "likert_min_label": "Low",
                    "likert_max_label": "High",
                },
                {
                    "type": "short_text",
                    "order": 3,
                    "text": "Tell us more",
                    "included_in_short": False,
                    "required": False,
                },
                {
                    "type": "multi_matrix",
                    "order": 4,
                    "text": "Duration planned vs actual",
                    "included_in_short": False,
                    "required": True,
                    "choices": [
                        {"text": "Less than 30 min", "order": 1},
                        {"text": "30 min to 1 hour", "order": 2},
                    ],
                    "columns": [
                        {"key": "planned", "label": "Planned", "select_mode": "single"},
                        {"key": "actual", "label": "Actual", "select_mode": "multi"},
                    ],
                },
            ],
        }

        spec = SurveySpec.from_dict(payload)
        result = import_survey_spec(spec)

        survey = Survey.objects.get(pk=result.survey_id)
        self.assertEqual(survey.name, "JSON Survey")
        self.assertEqual(survey.questions.count(), 4)
        self.assertEqual(result.question_count, 4)
        self.assertEqual(result.choice_count, 4)

        matrix = survey.questions.get(type=Question.Type.MULTI_MATRIX)
        self.assertEqual(matrix.choices.count(), 2)
        self.assertEqual(
            matrix.config_json["columns"],
            [
                {
                    "key": "planned",
                    "label": "Planned",
                    "kind": "choice",
                    "select_mode": "single",
                    "text_mode": "string",
                    "required": False,
                    "rank": False,
                },
                {
                    "key": "actual",
                    "label": "Actual",
                    "kind": "choice",
                    "select_mode": "multi",
                    "text_mode": "string",
                    "required": False,
                    "rank": False,
                },
            ],
        )
        self.assertEqual(matrix.config_json["row_required"], [True, True])
        self.assertFalse(matrix.config_json["require_complete_started_row"])
        self.assertFalse(matrix.config_json["require_single_choice_per_row"])

    def test_invalid_question_type_fails(self):
        payload = {
            "name": "Bad Survey",
            "consent_text": "Consent",
            "active": True,
            "questions": [
                {
                    "type": "matrix",
                    "order": 1,
                    "text": "Unsupported",
                }
            ],
        }

        with self.assertRaises(SurveySchemaError):
            SurveySpec.from_dict(payload)

    def test_invalid_matrix_column_mode_fails(self):
        payload = {
            "name": "Bad Matrix Survey",
            "consent_text": "Consent",
            "active": True,
            "questions": [
                {
                    "type": "multi_matrix",
                    "order": 1,
                    "text": "Duration planned vs actual",
                    "choices": [
                        {"text": "Less than 30 min", "order": 1},
                    ],
                    "columns": [
                        {"key": "planned", "label": "Planned", "select_mode": "invalid"},
                    ],
                }
            ],
        }

        with self.assertRaises(SurveySchemaError):
            SurveySpec.from_dict(payload)

    def test_rank_column_requires_short_text_integer(self):
        payload = {
            "name": "Bad Rank Survey",
            "consent_text": "Consent",
            "active": True,
            "questions": [
                {
                    "type": "multi_matrix",
                    "order": 1,
                    "text": "Duration planned vs actual",
                    "choices": [
                        {"text": "Less than 30 min", "order": 1},
                    ],
                    "columns": [
                        {"key": "planned", "label": "Planned", "select_mode": "single", "rank": True},
                    ],
                }
            ],
        }

        with self.assertRaises(SurveySchemaError):
            SurveySpec.from_dict(payload)

    def test_invalid_matrix_row_mode_fails(self):
        payload = {
            "name": "Bad Matrix Survey",
            "consent_text": "Consent",
            "active": True,
            "questions": [
                {
                    "type": "multi_matrix",
                    "order": 1,
                    "text": "Duration planned vs actual",
                    "row_select_mode": "invalid",
                    "choices": [
                        {"text": "Less than 30 min", "order": 1},
                    ],
                    "columns": [
                        {"key": "planned", "label": "Planned", "select_mode": "single"},
                    ],
                }
            ],
        }

        with self.assertRaises(SurveySchemaError):
            SurveySpec.from_dict(payload)


class MultiMatrixTests(TestCase):
    def setUp(self):
        self.survey = Survey.objects.create(name="Matrix survey", consent_text="consent")
        self.question = Question.objects.create(
            survey=self.survey,
            text="Duration planned vs actual",
            type=Question.Type.MULTI_MATRIX,
            order=1,
            included_in_short=True,
            required=True,
            config_json={
                "row_select_mode": "multi",
                "columns": [
                    {"key": "planned", "label": "Planned", "select_mode": "single"},
                    {"key": "actual", "label": "Actual", "select_mode": "multi"},
                ]
            },
        )
        self.opt1 = Choice.objects.create(question=self.question, text="Less than 30 min", order=1)
        self.opt2 = Choice.objects.create(question=self.question, text="30 min to 1 hour", order=2)
        self.opt3 = Choice.objects.create(question=self.question, text="1 to 2 hours", order=3)
        self.kiosk = Kiosk.objects.create(name="Matrix kiosk", survey=self.survey)

    def _new_session(self):
        return SurveySession.objects.create(
            kiosk=self.kiosk,
            survey=self.survey,
            length=SurveySession.Length.SHORT,
            consented=True,
            status=SurveySession.Status.ACTIVE,
        )

    def test_required_requires_each_column(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": str(self.opt1.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select at least one option in Actual.")

    def test_single_column_rejects_multiple_values(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": [str(self.opt1.id), str(self.opt2.id)],
                "matrix_actual": [str(self.opt3.id)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select only one option in Planned.")

    def test_multi_column_accepts_multiple_values(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": str(self.opt2.id),
                "matrix_actual": [str(self.opt1.id), str(self.opt3.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {
                "columns": {
                    "planned": [self.opt2.id],
                    "actual": [self.opt1.id, self.opt3.id],
                }
            },
        )

    def test_display_value_groups_by_column(self):
        session = self._new_session()
        answer = self.question.answers.create(
            session=session,
            value_json={
                "columns": {
                    "planned": [self.opt2.id],
                    "actual": [self.opt1.id, self.opt2.id],
                }
            },
        )

        self.assertEqual(
            answer.display_value(),
            "Planned: 30 min to 1 hour; Actual: Less than 30 min, 30 min to 1 hour",
        )

    def test_row_single_rejects_same_row_across_columns(self):
        self.question.config_json = {
            "row_select_mode": "single",
            "columns": [
                {"key": "planned", "label": "Planned", "select_mode": "multi"},
                {"key": "actual", "label": "Actual", "select_mode": "multi"},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": [str(self.opt1.id)],
                "matrix_actual": [str(self.opt1.id)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select only one column for row Less than 30 min.")

    def test_row_multi_allows_same_row_across_columns(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "columns": [
                {"key": "planned", "label": "Planned", "select_mode": "single"},
                {"key": "actual", "label": "Actual", "select_mode": "single"},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": str(self.opt2.id),
                "matrix_actual": str(self.opt2.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {
                "columns": {
                    "planned": [self.opt2.id],
                    "actual": [self.opt2.id],
                }
            },
        )

    def test_require_complete_started_row_rejects_partial_row(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "require_complete_started_row": True,
            "columns": [
                {"key": "planned", "label": "Planned", "kind": "choice", "select_mode": "multi", "required": True},
                {"key": "actual", "label": "Actual", "kind": "choice", "select_mode": "multi", "required": True},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": [str(self.opt1.id)],
                "matrix_actual": [str(self.opt2.id)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please complete all required columns for row Less than 30 min.")

    def test_require_complete_started_row_allows_untouched_rows(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "require_complete_started_row": True,
            "columns": [
                {"key": "planned", "label": "Planned", "kind": "choice", "select_mode": "multi", "required": True},
                {"key": "actual", "label": "Actual", "kind": "choice", "select_mode": "multi", "required": True},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_planned": [str(self.opt1.id)],
                "matrix_actual": [str(self.opt1.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {"columns": {"planned": [self.opt1.id], "actual": [self.opt1.id]}},
        )

    def test_require_single_choice_per_row_enforces_exactly_one(self):
        self.question.config_json = {
            "row_select_mode": "single",
            "require_single_choice_per_row": True,
            "row_required": [True, True, True],
            "columns": [
                {"key": "none", "label": "None", "kind": "choice", "select_mode": "multi", "required": True},
                {"key": "some", "label": "Some", "kind": "choice", "select_mode": "multi", "required": True},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        missing_response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "matrix_none": [str(self.opt2.id)],
                "matrix_some": [str(self.opt3.id)],
            },
        )
        self.assertEqual(missing_response.status_code, 200)
        self.assertContains(missing_response, "Please select one option for row Less than 30 min.")

    def test_require_single_choice_per_row_renders_row_radios(self):
        self.question.config_json = {
            "row_select_mode": "single",
            "require_single_choice_per_row": True,
            "row_required": [True, True, True],
            "columns": [
                {"key": "none", "label": "None", "kind": "choice", "select_mode": "multi", "required": True},
                {"key": "some", "label": "Some", "kind": "choice", "select_mode": "multi", "required": True},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.get(f"/survey/{session.id}/q/1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="matrix_row_{self.opt1.id}"')
        self.assertContains(response, f'name="matrix_row_{self.opt2.id}"')
        self.assertContains(response, f'name="matrix_row_{self.opt3.id}"')
        self.assertNotContains(response, 'name="matrix_none"')
        self.assertNotContains(response, 'name="matrix_some"')

    def test_require_single_choice_per_row_accepts_row_radio_payload(self):
        self.question.config_json = {
            "row_select_mode": "single",
            "require_single_choice_per_row": True,
            "row_required": [True, True, True],
            "columns": [
                {"key": "none", "label": "None", "kind": "choice", "select_mode": "multi", "required": True},
                {"key": "some", "label": "Some", "kind": "choice", "select_mode": "multi", "required": True},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                f"matrix_row_{self.opt1.id}": "none",
                f"matrix_row_{self.opt2.id}": "some",
                f"matrix_row_{self.opt3.id}": "none",
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {
                "columns": {
                    "none": [self.opt1.id, self.opt3.id],
                    "some": [self.opt2.id],
                }
            },
        )

    def test_short_text_integer_column_rejects_negative_value(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "columns": [
                {"key": "count", "label": "Count", "kind": "short_text", "text_mode": "integer", "required": False},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {f"matrix_text_count_{self.opt1.id}": "-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a whole number of 0 or greater for Count: Less than 30 min.")

    def test_rank_column_rejects_zero(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "columns": [
                {"key": "rank", "label": "Rank", "kind": "short_text", "text_mode": "integer", "rank": True, "required": False},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {f"matrix_text_rank_{self.opt1.id}": "0"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a rank of 1 or greater for Rank: Less than 30 min.")

    def test_rank_column_rejects_duplicate_values(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "columns": [
                {"key": "rank", "label": "Rank", "kind": "short_text", "text_mode": "integer", "rank": True, "required": False},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                f"matrix_text_rank_{self.opt1.id}": "1",
                f"matrix_text_rank_{self.opt2.id}": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rank 1 is used more than once in Rank.")

    def test_rank_column_rejects_value_above_filled_row_count(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "columns": [
                {"key": "rank", "label": "Rank", "kind": "short_text", "text_mode": "integer", "rank": True, "required": False},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {f"matrix_text_rank_{self.opt1.id}": "2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Rank 2 in Rank is higher than the number of rows you filled in (1)."
        )

    def test_rank_column_accepts_valid_ranks(self):
        self.question.config_json = {
            "row_select_mode": "multi",
            "columns": [
                {"key": "rank", "label": "Rank", "kind": "short_text", "text_mode": "integer", "rank": True, "required": False},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                f"matrix_text_rank_{self.opt1.id}": "2",
                f"matrix_text_rank_{self.opt2.id}": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {
                "columns": {},
                "text_cells": {"rank": {str(self.opt1.id): 2, str(self.opt2.id): 1}},
            },
        )


class MatrixWithGridTests(TestCase):
    def setUp(self):
        self.survey = Survey.objects.create(name="Matrix+Grid survey", consent_text="consent")
        self.question = Question.objects.create(
            survey=self.survey,
            text="Map and describe",
            type=Question.Type.MATRIX_WITH_GRID,
            order=1,
            included_in_short=True,
            required=True,
            config_json={
                "grid_rows": 4,
                "grid_cols": 6,
                "char_limit": 80,
                "row_required": [True, False],
                "columns": [
                    {"key": "mark", "label": "Mark on map", "kind": "map", "required": True},
                    {
                        "key": "notes",
                        "label": "Notes",
                        "kind": "short_text",
                        "text_mode": "string",
                        "required": True,
                    },
                ],
            },
        )
        self.opt1 = Choice.objects.create(question=self.question, text="Row 1", order=1)
        self.opt2 = Choice.objects.create(question=self.question, text="Row 2", order=2)
        self.kiosk = Kiosk.objects.create(name="Matrix+Grid kiosk", survey=self.survey)

    def _new_session(self):
        return SurveySession.objects.create(
            kiosk=self.kiosk,
            survey=self.survey,
            length=SurveySession.Length.SHORT,
            consented=True,
            status=SurveySession.Status.ACTIVE,
        )

    def test_accepts_required_row_map_and_text(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                f"map_toggle_{self.opt1.id}": "on",
                f"map_row_{self.opt1.id}": "1",
                f"map_col_{self.opt1.id}": "3",
                f"matrix_text_notes_{self.opt1.id}": "Near outlets",
                f"matrix_text_notes_{self.opt2.id}": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {
                "map_points_by_row": {str(self.opt1.id): {"row": 1, "col": 3}},
                "column_text_by_row": {"notes": {str(self.opt1.id): "Near outlets"}},
            },
        )

    def test_rejects_missing_required_map_row(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                f"matrix_text_notes_{self.opt1.id}": "Near outlets",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please mark a map location for row Row 1.")

    def test_short_text_integer_column_rejects_negative_value(self):
        self.question.config_json = {
            "grid_rows": 4,
            "grid_cols": 6,
            "row_required": [False, False],
            "columns": [
                {"key": "mark", "label": "Mark on map", "kind": "map", "required": False},
                {"key": "count", "label": "Count", "kind": "short_text", "text_mode": "integer", "required": False},
            ],
        }
        self.question.save(update_fields=["config_json"])

        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {f"matrix_text_count_{self.opt1.id}": "-3"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a whole number of 0 or greater for Count: Row 1.")


class GridPreferenceFlowTests(TestCase):
    def setUp(self):
        self.survey = Survey.objects.create(name="Preference flow survey", consent_text="consent")
        self.question = Question.objects.create(
            survey=self.survey,
            text="Preference flow",
            type=Question.Type.GRID_PREFERENCE_FLOW,
            order=1,
            included_in_short=True,
            required=True,
            config_json={
                "grid_rows": 4,
                "grid_cols": 6,
                "prompts": {
                    "initial_grid": "Initial",
                    "preferred_yes_no": "Preferred?",
                    "yes_reason": "Why yes?",
                    "no_grid": "Where instead?",
                    "no_reason": "Why there?",
                },
                "yes_reason_char_limit": 120,
                "no_reason_char_limit": 120,
                "require_no_branch_fields": True,
            },
        )
        self.kiosk = Kiosk.objects.create(name="Preference kiosk", survey=self.survey)

    def _new_session(self):
        return SurveySession.objects.create(
            kiosk=self.kiosk,
            survey=self.survey,
            length=SurveySession.Length.SHORT,
            consented=True,
            status=SurveySession.Status.ACTIVE,
        )

    def test_yes_branch_saves_expected_shape(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "initial_row": "2",
                "initial_col": "1",
                "preferred_today": "yes",
                "yes_reason": "Best light",
            },
        )

        self.assertEqual(response.status_code, 302)
        answer = self.question.answers.get(session=session)
        self.assertEqual(
            answer.value_json,
            {
                "initial_cell": {"row": 2, "col": 1},
                "preferred_today": True,
                "preferred_reason": "Best light",
                "alternative_cell": None,
                "alternative_reason": None,
            },
        )

    def test_no_branch_requires_alternative_fields(self):
        session = self._new_session()
        response = self.client.post(
            f"/survey/{session.id}/q/1",
            {
                "initial_row": "2",
                "initial_col": "1",
                "preferred_today": "no",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please tap a preferred alternative location.")


class CanonicalPayloadTests(TestCase):
    def test_likert_runtime_prefers_config_json(self):
        survey = Survey.objects.create(name="Config survey", consent_text="consent")
        question = Question.objects.create(
            survey=survey,
            text="Rate this",
            type=Question.Type.LIKERT,
            order=1,
            config_json={
                "likert_min": 2,
                "likert_max": 6,
                "likert_min_label": "new low",
                "likert_max_label": "new high",
            },
        )

        config = get_question_runtime_config(question)

        self.assertEqual(config["likert_min"], 2)
        self.assertEqual(config["likert_max"], 6)
        self.assertEqual(config["likert_min_label"], "new low")
        self.assertEqual(config["likert_max_label"], "new high")

    def test_short_text_runtime_uses_value_json(self):
        survey = Survey.objects.create(name="Answer survey", consent_text="consent")
        question = Question.objects.create(
            survey=survey,
            text="Tell us more",
            type=Question.Type.SHORT_TEXT,
            order=1,
        )
        kiosk = Kiosk.objects.create(name="K", survey=survey)
        session = SurveySession.objects.create(kiosk=kiosk, survey=survey, length="short")
        answer = question.answers.create(session=session, value_json={"text": "json text"})

        value = get_answer_runtime_value(question, answer)

        self.assertEqual(value["text"], "json text")

    def test_short_text_multi_field_runtime_uses_fields(self):
        survey = Survey.objects.create(name="Answer survey 2", consent_text="consent")
        question = Question.objects.create(
            survey=survey,
            text="Tell us more",
            type=Question.Type.SHORT_TEXT,
            order=1,
            config_json={"field_count": 2, "char_limit": 20, "field_required": [True, False]},
        )
        kiosk = Kiosk.objects.create(name="K2", survey=survey)
        session = SurveySession.objects.create(kiosk=kiosk, survey=survey, length="short")
        answer = question.answers.create(session=session, value_json={"fields": ["first", "second"]})

        value = get_answer_runtime_value(question, answer)

        self.assertEqual(value["fields"], ["first", "second"])

    def test_image_grid_display_uses_value_json(self):
        survey = Survey.objects.create(name="Grid survey", consent_text="consent")
        question = Question.objects.create(
            survey=survey,
            text="Pick a cell",
            type=Question.Type.IMAGE_GRID,
            order=1,
            config_json={"grid_rows": 4, "grid_cols": 5, "grid_image": "grid.png"},
        )
        kiosk = Kiosk.objects.create(name="Grid kiosk", survey=survey)
        session = SurveySession.objects.create(kiosk=kiosk, survey=survey, length="short")
        answer = question.answers.create(
            session=session,
            value_json={"row": 2, "col": 4},
        )

        self.assertEqual(get_question_runtime_config(question)["grid_rows"], 4)
        self.assertEqual(answer.display_value(), "2,4")

    def test_invalid_likert_bounds_fail(self):
        payload = {
            "name": "Bad Likert",
            "consent_text": "Consent",
            "active": True,
            "questions": [
                {
                    "type": "likert",
                    "order": 1,
                    "text": "Rate this",
                    "likert_min": 5,
                    "likert_max": 1,
                }
            ],
        }

        with self.assertRaises(SurveySchemaError):
            SurveySpec.from_dict(payload)

    def test_invalid_matrix_with_grid_short_text_select_mode_fails(self):
        payload = {
            "name": "Bad matrix+grid",
            "consent_text": "Consent",
            "active": True,
            "questions": [
                {
                    "type": "matrix_with_grid",
                    "order": 1,
                    "text": "Map and describe",
                    "grid_image": "../images/map.png",
                    "grid_rows": 4,
                    "grid_cols": 5,
                    "choices": [
                        {"text": "Row A", "order": 1},
                    ],
                    "columns": [
                        {"key": "mark", "label": "Mark", "kind": "map", "required": True},
                        {
                            "key": "note",
                            "label": "Note",
                            "kind": "short_text",
                            "text_mode": "string",
                            "select_mode": "multi",
                            "required": False,
                        },
                    ],
                    "row_required": [True],
                }
            ],
        }

        with self.assertRaises(SurveySchemaError):
            SurveySpec.from_dict(payload)
