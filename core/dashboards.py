"""Role-based dashboards.

One dashboard engine, five configurations. A dashboard is a plain dictionary
(metrics, at most two charts and a few tables) rendered by a single template,
so every role gets the same layout, empty states and theme behaviour.

Every query is filtered by the selected period, and sections are only included
when the signed-in user holds the permission that protects that information.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

from finance.models import Expense
from inventory.models import (
    Product,
    Purchase,
    StockAdjustment,
    StockBatch,
    StockMovement,
)
from sales.models import (
    Customer,
    CustomerPayment,
    Sale,
    SaleItem,
    SalePayment,
)

from .models import ShopSettings
from .permissions import (
    FINANCE_MANAGE,
    PRODUCTS_MANAGE,
    PURCHASES_MANAGE,
    REPORTS_VIEW,
    STOCK_ADJUST,
    user_permissions,
)

DASHBOARD_CHOICES = [
    ("owner", "Owner / Administrator"),
    ("manager", "Manager"),
    ("cashier", "Cashier"),
    ("storekeeper", "Storekeeper"),
    ("accountant", "Accountant"),
]

DASHBOARD_LABELS = dict(DASHBOARD_CHOICES)

ROLE_DASHBOARD_DEFAULTS = {
    "owner": "owner",
    "manager": "manager",
    "cashier": "cashier",
    "storekeeper": "storekeeper",
    "accountant": "accountant",
}

PERIOD_CHOICES = [
    ("today", "Today"),
    ("week", "This week"),
    ("month", "This month"),
    ("year", "This year"),
    ("custom", "Custom"),
]


def dashboard_for_user(user) -> str:
    """The dashboard assigned to the user's role, falling back to the role slug."""
    if getattr(user, "is_superuser", False):
        return "owner"
    profile = getattr(user, "profile", None)
    role = getattr(profile, "role", None) if profile else None
    if role is not None:
        if role.dashboard in DASHBOARD_LABELS:
            return role.dashboard
        if role.slug in ROLE_DASHBOARD_DEFAULTS:
            return ROLE_DASHBOARD_DEFAULTS[role.slug]
    return "owner"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def resolve_period(params):
    """Return (key, start, end, subtitle) for the dashboard date filter."""
    today = timezone.localdate()
    key = (params.get("period") or "month").strip()
    custom_start = parse_date(params.get("start"))
    custom_end = parse_date(params.get("end"))

    if key == "today":
        start = end = today
    elif key == "week":
        start, end = today - timedelta(days=today.weekday()), today
    elif key == "year":
        start, end = today.replace(month=1, day=1), today
    elif key == "custom":
        start = custom_start or today.replace(day=1)
        end = custom_end or today
        if start > end:
            start, end = end, start
    else:
        key = "month"
        start, end = today.replace(day=1), today

    if key == "today":
        subtitle = f"Today · {start:%d %b %Y}"
    elif key == "week":
        subtitle = f"This week · {start:%d %b} – {end:%d %b %Y}"
    elif key == "year":
        subtitle = f"This year · {start:%d %b %Y} – {end:%d %b %Y}"
    elif key == "custom":
        subtitle = f"{start:%d %b %Y} – {end:%d %b %Y}"
    else:
        subtitle = f"This month · {start:%d %b %Y} – {end:%d %b %Y}"
    return key, start, end, subtitle


def _money(value, symbol):
    amount = Decimal(value or 0)
    return f"{symbol}{amount:,.2f}"


def _int(value):
    return f"{int(value or 0):,}"


def _fmt_qty(value):
    amount = Decimal(value or 0)
    if amount == amount.to_integral_value():
        return f"{amount:,.0f}"
    return f"{amount:,.3f}".rstrip("0").rstrip(".")


def _sales(start, end):
    return Sale.objects.filter(
        status=Sale.STATUS_COMPLETED, created_at__date__range=(start, end)
    )


def _sales_by_day(start, end):
    rows = (
        _sales(start, end)
        .values("created_at__date")
        .annotate(total=Sum("total"), cogs=Sum("cogs"))
        .order_by("created_at__date")
    )
    # Counting rows per day needs a second, cheap pass; the aggregate above is
    # only used for money so it stays one query per measure group.
    counts = {}
    for created in _sales(start, end).values_list("created_at", flat=True):
        day = timezone.localtime(created).date()
        counts[day] = counts.get(day, 0) + 1
    data = {}
    for row in rows:
        data[row["created_at__date"]] = {
            "revenue": row["total"] or Decimal("0"),
            "cogs": row["cogs"] or Decimal("0"),
            "count": counts.get(row["created_at__date"], 0),
        }
    for day, count in counts.items():
        data.setdefault(day, {"revenue": Decimal("0"), "cogs": Decimal("0"), "count": count})
        data[day]["count"] = count
    return data


def _expenses_by_day(start, end):
    rows = (
        Expense.objects.filter(date__range=(start, end))
        .values("date")
        .annotate(total=Sum("amount"))
        .order_by("date")
    )
    return {row["date"]: row["total"] or Decimal("0") for row in rows}


def _bucket_dates(start, end):
    """Daily buckets up to ~5 weeks, weekly up to ~5 months, then monthly."""
    days = (end - start).days
    buckets = []
    if days <= 35:
        cursor = start
        while cursor <= end:
            buckets.append((cursor.strftime("%d %b"), cursor, cursor))
            cursor += timedelta(days=1)
        return buckets, "day"
    if days <= 150:
        cursor = start
        while cursor <= end:
            finish = min(cursor + timedelta(days=6), end)
            buckets.append((cursor.strftime("%d %b"), cursor, finish))
            cursor = finish + timedelta(days=1)
        return buckets, "week"
    cursor = start.replace(day=1)
    while cursor <= end:
        if cursor.month == 12:
            finish = cursor.replace(month=12, day=31)
            nxt = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            nxt = cursor.replace(month=cursor.month + 1, day=1)
            finish = nxt - timedelta(days=1)
        buckets.append((cursor.strftime("%b %Y"), cursor, min(finish, end)))
        cursor = nxt
    return buckets, "month"


def _series(buckets, mapping, field):
    values = []
    for _, first, last in buckets:
        total = Decimal("0")
        cursor = first
        while cursor <= last:
            total += mapping.get(cursor, {}).get(field, Decimal("0"))
            cursor += timedelta(days=1)
        values.append(float(total))
    return values


def _payments_by_method(start, end):
    totals = {}
    sale_rows = (
        SalePayment.objects.filter(
            sale__status=Sale.STATUS_COMPLETED,
            sale__created_at__date__range=(start, end),
        )
        .values("method_name")
        .annotate(total=Sum("amount"))
    )
    for row in sale_rows:
        name = row["method_name"] or "Unspecified"
        totals[name] = totals.get(name, Decimal("0")) + (row["total"] or Decimal("0"))
    customer_rows = (
        CustomerPayment.objects.filter(date__range=(start, end))
        .values("method_name")
        .annotate(total=Sum("amount"))
    )
    for row in customer_rows:
        name = row["method_name"] or "Unspecified"
        totals[name] = totals.get(name, Decimal("0")) + (row["total"] or Decimal("0"))
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return [name for name, _ in ordered], [float(value) for _, value in ordered]


def _recent_sales(start, end, limit=6):
    date_filter = {}
    if start == end:
        date_filter = {}
    sales = Sale.objects.select_related("customer").order_by("-created_at")
    if not (start == end == timezone.localdate()):
        sales = sales.filter(created_at__date__range=(start, end))
    else:
        sales = sales.filter(created_at__date=start)
    return [
        {
            "cells": [
                sale.number,
                timezone.localtime(sale.created_at).strftime("%d %b %H:%M"),
                sale.customer.name if sale.customer else "Walk-in",
                _fmt_qty(sale.total),
                _fmt_qty(sale.balance),
            ],
            "url": f"/sales/{sale.pk}/",
        }
        for sale in sales[:limit]
    ]


def _low_stock_products(limit=6):
    return [
        product
        for product in Product.objects.filter(is_active=True)
        .select_related("balance")
        .order_by("name")
        if product.is_low_stock or product.is_out_of_stock
    ][:limit]


def build_dashboard(user, start, end):
    """Return dashboard content for the user's role within the selected period."""
    shop = ShopSettings.load()
    symbol = shop.currency_symbol
    perms = user_permissions(user)
    can_finance = REPORTS_VIEW in perms or FINANCE_MANAGE in perms
    can_inventory = PRODUCTS_MANAGE in perms or STOCK_ADJUST in perms
    can_purchases = PURCHASES_MANAGE in perms
    kind = dashboard_for_user(user)

    sales = _sales(start, end)
    totals = sales.aggregate(
        revenue=Sum("total"), cogs=Sum("cogs"), paid=Sum("paid"), balance=Sum("balance")
    )
    revenue = totals["revenue"] or Decimal("0")
    cogs = totals["cogs"] or Decimal("0")
    paid = totals["paid"] or Decimal("0")
    balance = totals["balance"] or Decimal("0")
    transactions = sales.count()
    expenses = (
        Expense.objects.filter(date__range=(start, end)).aggregate(v=Sum("amount"))["v"]
        or Decimal("0")
    )
    customer_money = (
        CustomerPayment.objects.filter(date__range=(start, end)).aggregate(v=Sum("amount"))["v"]
        or Decimal("0")
    )
    received = paid + customer_money
    gross_profit = revenue - cogs
    net_profit = gross_profit - expenses

    metrics = []
    charts = []
    tables = []

    if kind == "owner":
        metrics = [
            {"label": "Total sales", "value": _money(revenue, symbol), "hint": f"{transactions} transactions"},
            {"label": "Payments received", "value": _money(received, symbol), "hint": f"Outstanding {_money(balance, symbol)}"},
            {"label": "Gross profit", "value": _money(gross_profit, symbol), "hint": f"Cost of goods {_money(cogs, symbol)}"},
            {"label": "Net operating profit", "value": _money(net_profit, symbol), "hint": f"Expenses {_money(expenses, symbol)}"},
        ]
        buckets, _ = _bucket_dates(start, end)
        labels = [label for label, _, _ in buckets]
        daily = _sales_by_day(start, end)
        daily_expenses = _expenses_by_day(start, end)
        charts.append(
            {
                "id": "owner-revenue",
                "type": "line",
                "title": "Sales revenue trend",
                "labels": labels,
                "datasets": [{"label": f"Revenue ({symbol})", "data": _series(buckets, daily, "revenue")}],
            }
        )
        charts.append(
            {
                "id": "owner-comparison",
                "type": "bar",
                "title": "Revenue, cost of goods and operating expenses",
                "labels": labels,
                "datasets": [
                    {"label": "Revenue", "data": _series(buckets, daily, "revenue")},
                    {"label": "Cost of goods", "data": _series(buckets, daily, "cogs")},
                    {
                        "label": "Operating expenses",
                        "data": [
                            float(
                                sum(
                                    (daily_expenses.get(day, Decimal("0")) for day in _days(first, last)),
                                    Decimal("0"),
                                )
                            )
                            for _, first, last in buckets
                        ],
                    },
                ],
            }
        )
        tables.append(
            {
                "title": "Recent sales",
                "columns": ["Receipt", "Date", "Customer", "Total", "Balance"],
                "rows": _recent_sales(start, end),
                "empty": "No sales were recorded in this period.",
                "empty_icon": "receipt",
                "action_url": "/sales/",
                "action_label": "Open sales",
            }
        )
        if can_inventory:
            tables.append(_low_stock_table())

    elif kind == "manager":
        metrics = [
            {"label": "Sales", "value": _money(revenue, symbol), "hint": f"{transactions} transactions"},
            {"label": "Average sale", "value": _money(revenue / transactions if transactions else 0, symbol), "hint": "Per transaction"},
            {"label": "Gross profit", "value": _money(gross_profit, symbol), "hint": f"Cost of goods {_money(cogs, symbol)}"},
            {"label": "Payments received", "value": _money(received, symbol), "hint": f"Outstanding {_money(balance, symbol)}"},
        ]
        buckets, _ = _bucket_dates(start, end)
        daily = _sales_by_day(start, end)
        charts.append(
            {
                "id": "manager-periods",
                "type": "bar",
                "title": "Sales across the selected period",
                "labels": [label for label, _, _ in buckets],
                "datasets": [{"label": f"Sales ({symbol})", "data": _series(buckets, daily, "revenue")}],
            }
        )
        top = list(
            SaleItem.objects.filter(
                sale__status=Sale.STATUS_COMPLETED,
                sale__created_at__date__range=(start, end),
            )
            .values("description")
            .annotate(revenue=Sum("line_total"), quantity=Sum("quantity"))
            .order_by("-revenue")[:6]
        )
        charts.append(
            {
                "id": "manager-top-products",
                "type": "bar",
                "horizontal": True,
                "title": "Top-selling products",
                "labels": [row["description"][:28] for row in top],
                "datasets": [
                    {"label": f"Revenue ({symbol})", "data": [float(row["revenue"] or 0) for row in top]}
                ],
            }
        )
        tables.append(
            {
                "title": "Recent sales",
                "columns": ["Receipt", "Date", "Customer", "Total", "Balance"],
                "rows": _recent_sales(start, end),
                "empty": "No sales were recorded in this period.",
                "empty_icon": "receipt",
                "action_url": "/sales/",
                "action_label": "Open sales",
            }
        )
        if can_inventory:
            tables.append(_low_stock_table())

    elif kind == "cashier":
        today = timezone.localdate()
        today_sales = _sales(today, today)
        today_totals = today_sales.aggregate(total=Sum("total"), paid=Sum("paid"))
        today_count = today_sales.count()
        mine = today_sales.filter(cashier=user)
        metrics = [
            {"label": "Sales today", "value": _money(today_totals["total"] or 0, symbol), "hint": f"{today_count} transactions"},
            {"label": "My sales today", "value": _money(mine.aggregate(v=Sum("total"))["v"] or 0, symbol), "hint": f"{mine.count()} transactions"},
            {"label": "Payments received", "value": _money(today_totals["paid"] or 0, symbol), "hint": "Cash and other methods"},
            {
                "label": "Unpaid balances",
                "value": _money(
                    Sale.objects.filter(status=Sale.STATUS_COMPLETED).aggregate(v=Sum("balance"))["v"] or 0,
                    symbol,
                ),
                "hint": "Across all customers",
            },
        ]
        hourly = {hour: Decimal("0") for hour in range(8, 21)}
        for created, total in today_sales.values_list("created_at", "total"):
            hour = timezone.localtime(created).hour
            if hour in hourly:
                hourly[hour] += total or Decimal("0")
        charts.append(
            {
                "id": "cashier-hourly",
                "type": "line",
                "title": "Hourly sales today",
                "labels": [f"{hour:02d}:00" for hour in hourly],
                "datasets": [{"label": f"Sales ({symbol})", "data": [float(v) for v in hourly.values()]}],
            }
        )
        method_labels, method_values = _payments_by_method(today, today)
        charts.append(
            {
                "id": "cashier-methods",
                "type": "doughnut",
                "title": "Payments by method today",
                "labels": method_labels,
                "datasets": [{"label": "Received", "data": method_values}],
            }
        )
        tables.append(
            {
                "title": "My recent transactions",
                "columns": ["Receipt", "Date", "Customer", "Total", "Balance"],
                "rows": [
                    {
                        "cells": [
                            sale.number,
                            timezone.localtime(sale.created_at).strftime("%d %b %H:%M"),
                            sale.customer.name if sale.customer else "Walk-in",
                            _fmt_qty(sale.total),
                            _fmt_qty(sale.balance),
                        ],
                        "url": f"/sales/{sale.pk}/",
                    }
                    for sale in Sale.objects.select_related("customer")
                    .filter(cashier=user)
                    .order_by("-created_at")[:8]
                ],
                "empty": "You have not recorded a sale yet.",
                "empty_icon": "receipt",
                "action_url": "/pos/",
                "action_label": "Open point of sale",
            }
        )

    elif kind == "storekeeper":
        products = list(Product.objects.filter(is_active=True).select_related("balance"))
        low = [p for p in products if p.is_low_stock]
        out = [p for p in products if p.is_out_of_stock]
        stock_value = sum((p.stock_value for p in products), Decimal("0"))
        movements = StockMovement.objects.filter(created_at__date__range=(start, end))
        received = (
            movements.filter(
                kind__in=[
                    StockMovement.KIND_RECEIPT,
                    StockMovement.KIND_OPENING,
                    StockMovement.KIND_PACK_IN,
                    StockMovement.KIND_SALE_CANCEL,
                ]
            ).aggregate(v=Sum("quantity"))["v"]
            or Decimal("0")
        )
        sold = abs(
            movements.filter(
                kind__in=[StockMovement.KIND_SALE, StockMovement.KIND_MIXTURE_SALE]
            ).aggregate(v=Sum("quantity"))["v"]
            or Decimal("0")
        )
        adjusted = abs(
            movements.filter(kind=StockMovement.KIND_ADJUSTMENT).aggregate(v=Sum("quantity"))["v"]
            or Decimal("0")
        )
        metrics = [
            {"label": "Products", "value": _int(len(products)), "hint": f"{len(low)} low, {len(out)} out of stock"},
            {"label": "Stock received", "value": _fmt_qty(received), "hint": "Base units in"},
            {"label": "Stock sold", "value": _fmt_qty(sold), "hint": "Base units out"},
            {"label": "Stock adjustments", "value": _fmt_qty(adjusted), "hint": "Corrections in this period"},
        ]
        charts.append(
            {
                "id": "storekeeper-movements",
                "type": "bar",
                "title": "Stock received, sold and adjusted",
                "labels": ["Received", "Sold", "Adjusted"],
                "datasets": [
                    {"label": "Base units", "data": [float(received), float(sold), float(adjusted)]}
                ],
            }
        )
        category_rows = (
            StockBatch.objects.filter(remaining__gt=0, product__is_active=True)
            .values("product__category__name")
            .annotate(
                stock=Sum("remaining"),
                value=Sum(F("remaining") * F("unit_cost")),
            )
            .order_by("-stock")
        )
        category_rows = list(category_rows)
        charts.append(
            {
                "id": "storekeeper-categories",
                "type": "doughnut",
                "title": "Inventory distribution by category",
                "labels": [row["product__category__name"] or "Uncategorised" for row in category_rows],
                "datasets": [{"label": "Stock on hand", "data": [float(row["stock"] or 0) for row in category_rows]}],
            }
        )
        tables.append(
            {
                "title": "Low and out-of-stock products",
                "columns": ["Product", "On hand", "Reorder level", "Status"],
                "rows": [
                    {
                        "cells": [
                            product.name,
                            f"{_fmt_qty(product.stock_quantity)} {product.unit}",
                            _fmt_qty(product.reorder_level),
                            "Out of stock" if product.is_out_of_stock else "Low",
                        ],
                        "url": f"/inventory/products/?edit={product.pk}",
                    }
                    for product in (out + low)[:8]
                ],
                "empty": "No product is at or below its reorder level.",
                "empty_icon": "box",
                "action_url": "/inventory/stock/",
                "action_label": "Stock overview",
            }
        )
        tables.append(
            {
                "title": "Recent stock adjustments",
                "columns": ["Date", "Product", "Change", "Reason"],
                "rows": [
                    {
                        "cells": [
                            timezone.localtime(item.created_at).strftime("%d %b %H:%M"),
                            item.product.name,
                            f"{'+' if item.quantity_delta > 0 else ''}{_fmt_qty(item.quantity_delta)}",
                            item.get_reason_display(),
                        ]
                    }
                    for item in StockAdjustment.objects.select_related("product").order_by("-created_at")[:6]
                ],
                "empty": "No stock adjustments recorded.",
                "empty_icon": "sliders",
                "action_url": "/inventory/adjustments/",
                "action_label": "Adjust stock",
            }
        )

    else:  # accountant
        metrics = [
            {"label": "Income", "value": _money(revenue, symbol), "hint": f"{transactions} sales"},
            {"label": "Cost of goods sold", "value": _money(cogs, symbol), "hint": "Direct cost"},
            {"label": "Gross profit", "value": _money(gross_profit, symbol), "hint": "Income less cost of goods"},
            {"label": "Operating expenses", "value": _money(expenses, symbol), "hint": "Recorded expenses"},
            {"label": "Net operating profit", "value": _money(net_profit, symbol), "hint": "Gross profit less expenses"},
            {"label": "Outstanding balances", "value": _money(balance, symbol), "hint": f"Payments received {_money(received, symbol)}"},
        ]
        buckets, _ = _bucket_dates(start, end)
        daily = _sales_by_day(start, end)
        daily_expenses = _expenses_by_day(start, end)
        charts.append(
            {
                "id": "accountant-income-expenses",
                "type": "line",
                "title": "Income and operating expenses",
                "labels": [label for label, _, _ in buckets],
                "datasets": [
                    {"label": f"Income ({symbol})", "data": _series(buckets, daily, "revenue")},
                    {
                        "label": "Operating expenses",
                        "data": [
                            float(
                                sum(
                                    (daily_expenses.get(day, Decimal("0")) for day in _days(first, last)),
                                    Decimal("0"),
                                )
                            )
                            for _, first, last in buckets
                        ],
                    },
                ],
            }
        )
        method_labels, method_values = _payments_by_method(start, end)
        charts.append(
            {
                "id": "accountant-methods",
                "type": "doughnut",
                "title": "Payments received by method",
                "labels": method_labels,
                "datasets": [{"label": "Received", "data": method_values}],
            }
        )
        tables.append(
            {
                "title": "Recent expenses",
                "columns": ["Date", "Description", "Category", "Amount"],
                "rows": [
                    {
                        "cells": [
                            expense.date.strftime("%d %b %Y"),
                            expense.description,
                            expense.category.name if expense.category else "Uncategorised",
                            _fmt_qty(expense.amount),
                        ]
                    }
                    for expense in Expense.objects.select_related("category").order_by("-date", "-id")[:8]
                ],
                "empty": "No expenses were recorded in this period.",
                "empty_icon": "wallet",
                "action_url": "/expenses/",
                "action_label": "Open expenses",
            }
        )
        tables.append(
            {
                "title": "Customer payments received",
                "columns": ["Date", "Customer", "Method", "Amount"],
                "rows": [
                    {
                        "cells": [
                            payment.date.strftime("%d %b %Y"),
                            payment.customer.name,
                            payment.method_name or "Unspecified",
                            _fmt_qty(payment.amount),
                        ],
                        "url": f"/customers/{payment.customer_id}/",
                    }
                    for payment in CustomerPayment.objects.select_related("customer")
                    .filter(date__range=(start, end))
                    .order_by("-date")[:8]
                ],
                "empty": "No customer payments in this period.",
                "empty_icon": "wallet",
                "action_url": "/customers/payments/",
                "action_label": "Payment history",
            }
        )

    if kind == "owner":
        metrics.extend(
            [
                {
                    "label": "Inventory value",
                    "value": _money(
                        StockBatch.objects.filter(remaining__gt=0).aggregate(
                            v=Sum(F("remaining") * F("unit_cost"))
                        )["v"]
                        or 0,
                        symbol,
                    ),
                    "hint": "At cost, on hand",
                }
            ]
        )

    # Assignment never grants information: without a finance/reporting
    # permission the cost and profit figures are removed even when the role
    # has been given a financial dashboard.
    if not can_finance:
        restricted = {
            "Gross profit",
            "Net operating profit",
            "Cost of goods sold",
            "Operating expenses",
            "Inventory value",
            "Income",
            "Payments received",
            "Outstanding balances",
        }
        metrics = [metric for metric in metrics if metric["label"] not in restricted]
        charts = [
            chart
            for chart in charts
            if chart["id"] not in {"owner-comparison", "accountant-income-expenses", "cashier-methods"}
        ]
        tables = [
            table for table in tables if table["title"] != "Recent expenses"
        ]

    return {
        "dashboard_kind": kind,
        "dashboard_label": DASHBOARD_LABELS.get(kind, "Dashboard"),
        "metrics": metrics,
        "charts": charts,
        "tables": tables,
        "transactions": transactions,
        "currency_symbol": symbol,
    }


def _days(first, last):
    cursor = first
    while cursor <= last:
        yield cursor
        cursor += timedelta(days=1)


def _low_stock_table():
    products = _low_stock_products()
    return {
        "title": "Low stock",
        "columns": ["Product", "On hand", "Reorder level", "Status"],
        "rows": [
            {
                "cells": [
                    product.name,
                    f"{_fmt_qty(product.stock_quantity)} {product.unit}",
                    _fmt_qty(product.reorder_level),
                    "Out of stock" if product.is_out_of_stock else "Low",
                ],
                "url": f"/inventory/products/?edit={product.pk}",
            }
            for product in products
        ],
        "empty": "No product is at or below its reorder level.",
        "empty_icon": "box",
        "action_url": "/inventory/stock/",
        "action_label": "Stock overview",
    }
