from django.db import transaction

from .models import PaymentMethod, Role, ShopSettings
from .permissions import ROLE_DEFAULTS, ROLE_LABELS

DEFAULT_PAYMENT_METHODS = [
    ("Cash", "cash", True, 1),
    ("Card", "card", False, 2),
    ("Mobile Money", "mobile", False, 3),
    ("Bank Transfer", "bank", False, 4),
]

DEFAULT_EXPENSE_CATEGORIES = [
    "Rent",
    "Utilities",
    "Salaries",
    "Transport",
    "Shop supplies",
    "Marketing",
    "Other",
]


@transaction.atomic
def ensure_defaults():
    """Create the singleton settings and the default reference data once."""
    shop = ShopSettings.load()
    for slug, permissions in ROLE_DEFAULTS.items():
        Role.objects.get_or_create(
            slug=slug,
            defaults={
                "name": ROLE_LABELS[slug],
                "permissions": list(permissions),
                "is_system": True,
            },
        )
    for name, kind, is_default, order in DEFAULT_PAYMENT_METHODS:
        PaymentMethod.objects.get_or_create(
            name=name,
            defaults={"kind": kind, "is_default": is_default, "sort_order": order},
        )
    from finance.models import ExpenseCategory

    for name in DEFAULT_EXPENSE_CATEGORIES:
        ExpenseCategory.objects.get_or_create(name=name)
    return shop
