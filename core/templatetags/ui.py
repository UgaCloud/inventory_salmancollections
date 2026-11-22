import json
from datetime import date, datetime
from decimal import Decimal

from django import template
from django.utils import timezone

register = template.Library()


def format_cell(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, datetime):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return local.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


@register.filter
def cellformat(value):
    return format_cell(value)


@register.filter
def money(value, symbol=None):
    try:
        amount = Decimal(value or 0)
    except Exception:
        return value
    prefix = symbol or ""
    return f"{prefix}{amount:,.2f}"


@register.filter
def quantity(value):
    try:
        amount = Decimal(value or 0)
    except Exception:
        return value
    if amount == amount.to_integral_value():
        return f"{amount:,.0f}"
    return f"{amount:,.3f}".rstrip("0").rstrip(".")


@register.filter
def json_script_value(value):
    return json.dumps(value)


@register.filter
def optional_fields(form):
    """Visible fields the user may leave empty, shown behind "Add more info"."""
    return [field for field in form.visible_fields() if not field.field.required]


@register.filter
def get_item(mapping, key):
    if hasattr(mapping, "get"):
        return mapping.get(key)
    return None


@register.filter
def is_true(value):
    return bool(value)


@register.simple_tag
def query_update(request, **kwargs):
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()
