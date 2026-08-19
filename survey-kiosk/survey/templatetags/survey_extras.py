import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# Inline markers supported in survey-authored text: **bold**, *italic*, {{sm|md|lg|xl:text}}.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"\*(.+?)\*", re.DOTALL)
_SIZE_RE = re.compile(r"\{\{(sm|md|lg|xl):(.+?)\}\}", re.DOTALL)


@register.filter
def get_item(value, key):
    if isinstance(value, dict):
        return value.get(key)
    if isinstance(value, list):
        try:
            return value[key]
        except (TypeError, IndexError, ValueError):
            return None
    return None


@register.filter(is_safe=True)
def richtext(value):
    """Escape survey-authored text, then apply **bold**/*italic*/{{size:text}} markers and line breaks."""
    if value is None:
        return ""
    text = escape(str(value))
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = _SIZE_RE.sub(r'<span class="text-\1">\2</span>', text)
    text = text.replace("\n", "<br>")
    return mark_safe(text)
