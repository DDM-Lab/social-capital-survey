"""Thermal-receipt printing behind a swappable backend.

There is no printer attached in dev (or on the Sprite), so the default backend
just renders the receipt and logs it. A real backend (browser print / ESC-POS
agent) can be dropped in later via the PRINTER_BACKEND setting.
"""

import logging

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

_WIDTH = 32


def render_receipt(receipt):
    """Plain-text receipt body — AndrewID + completion timestamp + a short ref."""
    completed = receipt.session.completed_at or receipt.created_at
    lines = [
        "SOCIAL CAPITAL SURVEY".center(_WIDTH),
        "Coffee receipt".center(_WIDTH),
        "-" * _WIDTH,
        f"Andrew ID : {receipt.andrew_id}",
        f"Completed : {timezone.localtime(completed):%Y-%m-%d %H:%M}",
        f"Ref       : {receipt.verify_token[:8]}",
        "-" * _WIDTH,
        "Redeem for one free coffee.",
    ]
    return "\n".join(lines)


class PrinterBackend:
    """Interface: turn a Receipt into a physical printout."""

    def print_receipt(self, receipt):
        raise NotImplementedError


class PreviewBackend(PrinterBackend):
    """Dev backend: 'prints' by logging and returning the rendered text so the
    confirmation screen can show exactly what a real printer would emit."""

    def print_receipt(self, receipt):
        text = render_receipt(receipt)
        logger.info("RECEIPT (preview) for %s:\n%s", receipt.andrew_id, text)
        return text


def get_printer():
    """Instantiate the configured PrinterBackend."""
    return import_string(settings.PRINTER_BACKEND)()
