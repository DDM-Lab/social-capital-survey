import re

from django import forms
from django.conf import settings

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ClaimForm(forms.Form):
    """Collects a username only; the target domain is appended server-side."""

    username = forms.CharField(max_length=64, strip=True)

    def clean_username(self):
        raw = self.cleaned_data["username"].strip().lower()
        domain = settings.TARGET_DOMAIN.lower()

        # Tolerate a pasted full address as long as it's the right domain.
        if "@" in raw:
            local, _, typed_domain = raw.partition("@")
            if typed_domain != domain:
                raise forms.ValidationError(
                    f"Please enter only your username — the @{domain} part is added for you."
                )
            raw = local

        if not raw:
            raise forms.ValidationError("Please enter your username.")
        if not USERNAME_RE.match(raw):
            raise forms.ValidationError("That username contains unsupported characters.")
        return raw

    @property
    def email(self):
        return f"{self.cleaned_data['username']}@{settings.TARGET_DOMAIN.lower()}"
