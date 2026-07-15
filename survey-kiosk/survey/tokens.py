"""Signed, short-lived tokens for the rotating kiosk QR code.

The rotating token carries the kiosk id plus a nonce and is signed with an
HMAC + timestamp (Django's TimestampSigner). No DB row is needed: freshness is
enforced by the embedded timestamp at scan time.
"""

import secrets

from django.core import signing

_SALT = "survey.kiosk.qr"
_signer = signing.TimestampSigner(salt=_SALT)


def mint_kiosk_token(kiosk_id):
    """Return a fresh signed token for this kiosk (unique per call via nonce)."""
    payload = {"k": kiosk_id, "n": secrets.token_hex(4)}
    return _signer.sign_object(payload, compress=True)


def verify_kiosk_token(token, max_age):
    """Return the kiosk id if the token is valid and fresh, else None."""
    try:
        payload = _signer.unsign_object(token, max_age=max_age)
    except (signing.SignatureExpired, signing.BadSignature):
        return None
    return payload.get("k")
