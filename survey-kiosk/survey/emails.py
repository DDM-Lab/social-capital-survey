from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse


def send_verify_email(claim):
    """Email the single-use magic link that verifies the mailbox and delivers the prize."""
    path = reverse("survey:verify", args=[claim.verify_token])
    link = f"{settings.BASE_URL}{path}"
    subject = "Confirm your email to get your survey prize"
    body = (
        "Thanks for completing the survey!\n\n"
        "Click the link below to confirm this is your email address and reveal "
        "your prize code:\n\n"
        f"{link}\n\n"
        f"This link expires in {settings.VERIFY_TTL_HOURS} hours and can only be used by you.\n"
        "If you didn't take this survey, you can ignore this message."
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [claim.email])
    return link
