from django import template

from cloud_accounts.models import PROVIDER_LABELS

register = template.Library()


@register.filter
def money(value, currency="USD"):
    """Format a number as money. Formatting only - no arithmetic happens here."""
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    sign = "-" if number < 0 else ""
    if currency == "USD":
        return f"{sign}${abs(number):,.2f}"
    return f"{sign}{abs(number):,.2f} {currency}"


@register.filter
def provider_label(value):
    return PROVIDER_LABELS.get(value, value)


@register.filter
def pretty_key(value):
    return str(value).replace("_", " ").capitalize()


@register.filter
def pretty_value(value):
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return value
