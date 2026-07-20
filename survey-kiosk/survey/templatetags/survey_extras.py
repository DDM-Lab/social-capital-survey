from django import template

register = template.Library()


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
