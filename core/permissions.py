"""Feature permissions shared by the backend and the interface."""

DASHBOARD_VIEW = "dashboard.view"
POS_USE = "pos.use"
PRODUCTS_MANAGE = "inventory.manage"
STOCK_ADJUST = "stock.adjust"
PURCHASES_MANAGE = "purchases.manage"
CUSTOMERS_MANAGE = "customers.manage"
FINANCE_MANAGE = "finance.manage"
REPORTS_VIEW = "reports.view"
SALES_CANCEL = "sales.cancel"
MIXTURES_MANAGE = "mixtures.manage"
SETTINGS_MANAGE = "settings.manage"
USERS_MANAGE = "users.manage"
BACKUP_MANAGE = "backup.manage"
AUDIT_VIEW = "audit.view"
COSTS_EDIT = "costs.edit"

PERMISSION_GROUPS = [
    (
        "General",
        [
            (DASHBOARD_VIEW, "View dashboard"),
            (REPORTS_VIEW, "View reports and exports"),
            (AUDIT_VIEW, "View audit log"),
        ],
    ),
    (
        "Sales",
        [
            (POS_USE, "Use the point of sale"),
            (SALES_CANCEL, "Cancel sales and issue refunds"),
            (MIXTURES_MANAGE, "Prepare perfume mixtures"),
        ],
    ),
    (
        "Inventory",
        [
            (PRODUCTS_MANAGE, "Manage products and perfumes"),
            (PURCHASES_MANAGE, "Manage suppliers and receive stock"),
            (STOCK_ADJUST, "Adjust stock levels"),
            (COSTS_EDIT, "Change buying costs"),
        ],
    ),
    (
        "Business",
        [
            (CUSTOMERS_MANAGE, "Manage customers and payments"),
            (FINANCE_MANAGE, "Manage expenses and cash reconciliation"),
            (SETTINGS_MANAGE, "Change business settings"),
            (USERS_MANAGE, "Manage user accounts and roles"),
            (BACKUP_MANAGE, "Create and restore backups"),
        ],
    ),
]

PERMISSION_LABELS = {
    code: label for _, items in PERMISSION_GROUPS for code, label in items
}
ALL_PERMISSIONS = list(PERMISSION_LABELS)

ROLE_DEFAULTS = {
    "owner": ALL_PERMISSIONS,
    "manager": [
        DASHBOARD_VIEW,
        POS_USE,
        PRODUCTS_MANAGE,
        STOCK_ADJUST,
        PURCHASES_MANAGE,
        CUSTOMERS_MANAGE,
        FINANCE_MANAGE,
        REPORTS_VIEW,
        SALES_CANCEL,
        MIXTURES_MANAGE,
        COSTS_EDIT,
        AUDIT_VIEW,
    ],
    "cashier": [DASHBOARD_VIEW, POS_USE, CUSTOMERS_MANAGE],
    "storekeeper": [
        DASHBOARD_VIEW,
        PRODUCTS_MANAGE,
        STOCK_ADJUST,
        PURCHASES_MANAGE,
        REPORTS_VIEW,
        COSTS_EDIT,
    ],
    "accountant": [
        DASHBOARD_VIEW,
        CUSTOMERS_MANAGE,
        FINANCE_MANAGE,
        REPORTS_VIEW,
        AUDIT_VIEW,
    ],
}

ROLE_LABELS = {
    "owner": "Owner",
    "manager": "Manager",
    "cashier": "Cashier",
    "storekeeper": "Storekeeper",
    "accountant": "Accountant",
}


def user_permissions(user) -> set:
    """Return the effective permission codes for an authenticated user."""
    if not getattr(user, "is_authenticated", False):
        return set()
    cached = getattr(user, "_permission_cache", None)
    if cached is not None:
        return cached
    if user.is_superuser:
        perms = set(ALL_PERMISSIONS)
    else:
        profile = getattr(user, "profile", None)
        if not profile or not profile.is_active or not profile.role:
            perms = set()
        else:
            perms = set(profile.role.permissions or [])
    user._permission_cache = perms
    return perms


def user_has_perm(user, code: str) -> bool:
    return code in user_permissions(user)
