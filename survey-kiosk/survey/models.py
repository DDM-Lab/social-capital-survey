import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .question_types import QUESTION_TYPES


class Kiosk(models.Model):
    """A physical always-on screen that displays the rotating QR code."""

    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    survey = models.ForeignKey(
        "Survey",
        on_delete=models.PROTECT,
        related_name="kiosks",
        help_text="Survey served when this kiosk is scanned.",
    )
    # Optional per-kiosk overrides; fall back to project settings when null.
    rotate_seconds = models.PositiveIntegerField(null=True, blank=True)
    token_ttl_seconds = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def effective_rotate_seconds(self):
        return self.rotate_seconds or settings.QR_ROTATE_SECONDS

    @property
    def effective_token_ttl_seconds(self):
        return self.token_ttl_seconds or settings.TOKEN_TTL_SECONDS


class Survey(models.Model):
    """A question bank. The 'short' variant is the questions flagged included_in_short."""

    name = models.CharField(max_length=200)
    active = models.BooleanField(default=True)
    consent_text = models.TextField(
        blank=True,
        help_text="IRB-approved consent language shown before the survey. "
        "PLACEHOLDER until the approved wording is pasted in.",
    )

    def __str__(self):
        return self.name

    def questions_for(self, length):
        qs = self.questions.all()
        if length == SurveySession.Length.SHORT:
            qs = qs.filter(included_in_short=True)
        return qs.order_by("order", "id")


class Question(models.Model):
    class Type(models.TextChoices):
        SINGLE = "single", "Single choice"
        MULTI = "multi", "Multiple choice"
        LIKERT = "likert", "Likert scale"
        SHORT_TEXT = "short_text", "Short text"
        IMAGE_GRID = "image_grid", "Image grid (single cell)"

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="questions")
    text = models.CharField(max_length=500)
    type = models.CharField(max_length=20, choices=Type.choices)
    order = models.PositiveIntegerField(default=0)
    included_in_short = models.BooleanField(
        default=False, help_text="Include in the 5-question short survey."
    )
    required = models.BooleanField(default=True)
    config_json = models.JSONField(default=dict, blank=True)

    grid_image = models.ImageField(upload_to="grids/", null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"[{self.get_type_display()}] {self.text[:60]}"

    @property
    def likert_range(self):
        config = self.config_json or {}
        return range(config.get("likert_min", 1), config.get("likert_max", 5) + 1)


class Choice(models.Model):
    """Selectable option for single/multi questions."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class SurveySession(models.Model):
    class Length(models.TextChoices):
        SHORT = "short", "Short (5 questions)"
        LONG = "long", "Long (15 questions)"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kiosk = models.ForeignKey(Kiosk, on_delete=models.PROTECT, related_name="sessions")
    survey = models.ForeignKey(Survey, on_delete=models.PROTECT, related_name="sessions")
    length = models.CharField(max_length=10, choices=Length.choices, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    consented = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=settings.SURVEY_TTL_MINUTES)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_live(self):
        return self.status == self.Status.ACTIVE and not self.is_expired

    def __str__(self):
        return f"Session {self.id} ({self.status})"


class Answer(models.Model):
    session = models.ForeignKey(SurveySession, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")

    # Used per question type:
    choices = models.ManyToManyField(Choice, blank=True)  # single (1) / multi (N)
    value_json = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "question"], name="one_answer_per_question_per_session"
            )
        ]

    def display_value(self):
        return QUESTION_TYPES[self.question.type].display_answer(self)

    def __str__(self):
        return f"Answer to {self.question_id} in {self.session_id}"


class PrizeCode(models.Model):
    """Pool of unique redemption codes uploaded by admins."""

    code = models.CharField(max_length=100, unique=True)
    assigned = models.BooleanField(default=False)
    assigned_to = models.OneToOneField(
        "PrizeClaim",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_code",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code


class PrizeClaim(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending verification"
        VERIFIED = "verified", "Verified"
        POOL_EMPTY = "pool_empty", "Verified but pool empty"

    session = models.OneToOneField(SurveySession, on_delete=models.CASCADE, related_name="claim")
    email = models.EmailField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    verify_token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    verify_expires_at = models.DateTimeField()
    prize_code = models.ForeignKey(
        PrizeCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One prize per mailbox: enforced only across verified/delivered claims.
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(status__in=["verified", "pool_empty"]),
                name="one_verified_claim_per_email",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.verify_expires_at:
            self.verify_expires_at = timezone.now() + timedelta(hours=settings.VERIFY_TTL_HOURS)
        super().save(*args, **kwargs)

    @property
    def verify_expired(self):
        return timezone.now() >= self.verify_expires_at

    def __str__(self):
        return f"{self.email} ({self.status})"
