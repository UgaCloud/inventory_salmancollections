"""Configurable list pagination.

Every paginated table asks for a size by section name. The value comes from the
shop's pagination settings and always falls back to the default, so a missing or
out-of-range value can never break a list.
"""
from .models import ShopSettings

PAGINATION_SECTIONS = [
    ("default", "Default for every table"),
    ("products", "Products & perfumes"),
    ("stock", "Stock overview"),
    ("purchases", "Purchases & receiving"),
    ("sales", "Sales & receipts"),
    ("customers", "Customers"),
    ("payments", "Customer payments"),
    ("expenses", "Expenses"),
    ("audit", "Audit log"),
    ("pos", "Point of sale catalogue"),
]

MIN_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100


def page_size_for(section="default") -> int:
    shop = ShopSettings.load()
    default = shop.page_size_default or 10
    value = getattr(shop, f"page_size_{section}", None)
    if not value:
        value = default
    return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, int(value)))
