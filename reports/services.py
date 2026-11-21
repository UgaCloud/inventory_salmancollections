"""Dashboard metrics and business reports."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from finance.models import Expense, ExpenseCategory
from inventory.models import (
    PackRun,
    Product,
    Purchase,
    StockBatch,
    StockMovement,
)
from sales.models import (
    Customer,
    CustomerPayment,
    Mixture,
    Refund,
    Sale,
    SaleItem,
    SalePayment,
)

MONEY_COLUMNS = {"subtotal", "discount", "total", "paid", "balance", "cost", "profit"}


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def shop_date_range(params):
    today = timezone.localdate()
    start = parse_date(params.get("start")) or today.replace(day=1)
    end = parse_date(params.get("end")) or today
    if start > end:
        start, end = end, start
    return start, end


def dashboard_context():
    today = timezone.localdate()
    month_start = today.replace(day=1)
    week_ago = today - timedelta(days=30)

    completed_today = Sale.objects.filter(
        status=Sale.STATUS_COMPLETED, created_at__date=today
    )
    today_totals = completed_today.aggregate(
        revenue=Sum("total"), cogs=Sum("cogs"), received=Sum("paid")
    )
    revenue = today_totals["revenue"] or Decimal("0")
    cogs = today_totals["cogs"] or Decimal("0")

    customer_money = (
        CustomerPayment.objects.filter(date=today).aggregate(v=Sum("amount"))["v"]
        or Decimal("0")
    )
    refunds = (
        Refund.objects.filter(created_at__date=today).aggregate(v=Sum("amount"))["v"]
        or Decimal("0")
    )
    expenses = (
        Expense.objects.filter(date=today).aggregate(v=Sum("amount"))["v"]
        or Decimal("0")
    )
    outstanding = (
        Sale.objects.filter(status=Sale.STATUS_COMPLETED).aggregate(v=Sum("balance"))["v"]
        or Decimal("0")
    )
    month_totals = Sale.objects.filter(
        status=Sale.STATUS_COMPLETED, created_at__date__gte=month_start
    ).aggregate(revenue=Sum("total"), cogs=Sum("cogs"))

    products = list(
        Product.objects.filter(is_active=True).select_related("balance")
    )
    low_stock = [p for p in products if p.is_low_stock]
    out_of_stock = [p for p in products if p.is_out_of_stock]

    best_sellers = (
        SaleItem.objects.filter(
            sale__status=Sale.STATUS_COMPLETED,
            sale__created_at__date__gte=week_ago,
        )
        .values("description")
        .annotate(revenue=Sum("line_total"), quantity=Sum("quantity"))
        .order_by("-revenue")[:5]
    )

    return {
        "today": today,
        "today_sales": revenue,
        "today_received": (today_totals["received"] or Decimal("0"))
        + customer_money
        - refunds,
        "today_profit": revenue - cogs,
        "today_expenses": expenses,
        "outstanding": outstanding,
        "month_revenue": month_totals["revenue"] or Decimal("0"),
        "month_profit": (month_totals["revenue"] or Decimal("0"))
        - (month_totals["cogs"] or Decimal("0")),
        "product_count": len(products),
        "low_stock": low_stock[:6],
        "low_stock_count": len(low_stock),
        "out_of_stock_count": len(out_of_stock),
        "recent_sales": Sale.objects.select_related("customer", "cashier")[:8],
        "best_sellers": best_sellers,
        "recent_purchases": Purchase.objects.select_related("supplier")[:5],
        "prepared_mixtures": Mixture.objects.filter(
            status=Mixture.STATUS_PREPARED
        ).count(),
        "customer_count": Customer.objects.filter(is_active=True).count(),
        "stock_value": _stock_value(),
    }


def _stock_value():
    total = Decimal("0")
    for batch in StockBatch.objects.filter(remaining__gt=0).only("remaining", "unit_cost"):
        total += batch.remaining * batch.unit_cost
    return total


def _money(value):
    return value or Decimal("0")


def report_sales(start, end):
    sales = list(
        Sale.objects.filter(created_at__date__range=(start, end))
        .select_related("customer", "cashier")
        .order_by("created_at")
    )
    rows = [
        [
            sale.number,
            sale.created_at,
            sale.customer.name if sale.customer else "Walk-in",
            sale.cashier.get_full_name() if sale.cashier else "—",
            sale.get_status_display(),
            sale.subtotal,
            sale.discount,
            sale.total,
            sale.paid,
            sale.balance,
            sale.cogs,
        ]
        for sale in sales
    ]
    completed = [s for s in sales if s.status == Sale.STATUS_COMPLETED]
    return {
        "title": "Sales report",
        "columns": [
            "Receipt",
            "Date",
            "Customer",
            "Cashier",
            "Status",
            "Subtotal",
            "Discount",
            "Total",
            "Paid",
            "Balance",
            "Cost",
        ],
        "rows": rows,
        "summary": [
            ("Sales", len(completed)),
            ("Revenue", sum((s.total for s in completed), Decimal("0"))),
            ("Received", sum((s.paid for s in completed), Decimal("0"))),
            ("Outstanding", sum((s.balance for s in completed), Decimal("0"))),
            (
                "Cancelled refunds",
                sum(
                    (s.refunded_amount for s in sales if s.status == Sale.STATUS_CANCELLED),
                    Decimal("0"),
                ),
            ),
        ],
    }


def report_products(start, end):
    items = (
        SaleItem.objects.filter(
            sale__status=Sale.STATUS_COMPLETED,
            sale__created_at__date__range=(start, end),
            product__isnull=False,
        )
        .values("product__name", "product__sku", "product__kind")
        .annotate(quantity=Sum("quantity"), revenue=Sum("line_total"), cost=Sum("cogs"))
        .order_by("-revenue")
    )
    rows = []
    for item in items:
        revenue = _money(item["revenue"])
        cost = _money(item["cost"])
        rows.append(
            [
                item["product__name"],
                item["product__sku"],
                item["product__kind"],
                item["quantity"],
                revenue,
                cost,
                revenue - cost,
            ]
        )
    return {
        "title": "Product performance",
        "columns": ["Product", "SKU", "Type", "Quantity sold", "Revenue", "Cost", "Profit"],
        "rows": rows,
        "summary": [
            ("Products", len(rows)),
            ("Revenue", sum((r[4] for r in rows), Decimal("0"))),
            ("Profit", sum((r[6] for r in rows), Decimal("0"))),
        ],
    }


def report_inventory(start, end):
    products = list(
        Product.objects.select_related("balance").prefetch_related("batches").order_by("name")
    )
    rows = []
    total_value = Decimal("0")
    for product in products:
        value = product.stock_value
        total_value += value
        rows.append(
            [
                product.name,
                product.sku,
                product.kind,
                product.unit,
                product.stock_quantity,
                product.average_cost,
                value,
                product.reorder_level,
                "Out of stock" if product.is_out_of_stock else (
                    "Low" if product.is_low_stock else "In stock"
                ),
            ]
        )
    return {
        "title": "Inventory valuation",
        "columns": [
            "Product",
            "SKU",
            "Type",
            "Unit",
            "Stock",
            "Average cost",
            "Stock value",
            "Reorder level",
            "Status",
        ],
        "rows": rows,
        "summary": [("Products", len(rows)), ("Stock value", total_value)],
    }


def report_purchases(start, end):
    purchases = list(
        Purchase.objects.filter(purchase_date__range=(start, end))
        .select_related("supplier", "user")
        .order_by("purchase_date")
    )
    rows = [
        [
            purchase.number,
            purchase.purchase_date,
            purchase.supplier.name if purchase.supplier else "—",
            purchase.total_quantity,
            purchase.total_cost,
            purchase.user.username if purchase.user else "—",
            purchase.reference,
        ]
        for purchase in purchases
    ]
    return {
        "title": "Purchase report",
        "columns": ["Purchase", "Date", "Supplier", "Quantity", "Cost", "Received by", "Reference"],
        "rows": rows,
        "summary": [
            ("Purchases", len(rows)),
            ("Total cost", sum((p.total_cost for p in purchases), Decimal("0"))),
        ],
    }


def report_profit(start, end):
    sales = (
        Sale.objects.filter(
            status=Sale.STATUS_COMPLETED, created_at__date__range=(start, end)
        )
        .values("created_at__date")
        .annotate(revenue=Sum("total"), cost=Sum("cogs"))
        .order_by("created_at__date")
    )
    expenses = (
        Expense.objects.filter(date__range=(start, end))
        .values("date")
        .annotate(total=Sum("amount"))
    )
    expense_map = {row["date"]: _money(row["total"]) for row in expenses}
    rows = []
    total_revenue = Decimal("0")
    total_cost = Decimal("0")
    total_expense = Decimal("0")
    for day in sales:
        revenue = _money(day["revenue"])
        cost = _money(day["cost"])
        expense = expense_map.pop(day["created_at__date"], Decimal("0"))
        rows.append(
            [day["created_at__date"], revenue, cost, revenue - cost, expense, revenue - cost - expense]
        )
        total_revenue += revenue
        total_cost += cost
        total_expense += expense
    for day, expense in sorted(expense_map.items()):
        rows.append([day, Decimal("0"), Decimal("0"), Decimal("0"), expense, -expense])
        total_expense += expense
    return {
        "title": "Gross and net profit",
        "columns": ["Date", "Sales", "Cost of goods", "Gross profit", "Expenses", "Net profit"],
        "rows": rows,
        "summary": [
            ("Revenue", total_revenue),
            ("Cost of goods sold", total_cost),
            ("Gross profit", total_revenue - total_cost),
            ("Operating expenses", total_expense),
            ("Net operating profit", total_revenue - total_cost - total_expense),
        ],
    }


def report_expenses(start, end):
    expenses = list(
        Expense.objects.filter(date__range=(start, end))
        .select_related("category", "payment_method")
        .order_by("date")
    )
    rows = [
        [
            expense.date,
            expense.category.name if expense.category else "Uncategorised",
            expense.description,
            expense.method_name,
            expense.amount,
            expense.user.username if expense.user else "—",
        ]
        for expense in expenses
    ]
    by_category = (
        Expense.objects.filter(date__range=(start, end))
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    return {
        "title": "Expense report",
        "columns": ["Date", "Category", "Description", "Method", "Amount", "Recorded by"],
        "rows": rows,
        "summary": [
            ("Expenses", len(rows)),
            ("Total", sum((e.amount for e in expenses), Decimal("0"))),
        ],
        "extra_summary": [
            (row["category__name"] or "Uncategorised", _money(row["total"]))
            for row in by_category
        ],
    }


def report_perfumes(start, end):
    items = list(
        SaleItem.objects.filter(
            sale__status=Sale.STATUS_COMPLETED,
            sale__created_at__date__range=(start, end),
        )
        .select_related("product", "mixture")
        .order_by("sale__created_at")
    )
    rows = []
    for item in items:
        if item.mixture_id:
            rows.append(
                [
                    "Mixture",
                    item.description,
                    item.quantity,
                    "mixture",
                    item.line_total,
                    item.cogs,
                    item.line_total - item.cogs,
                ]
            )
        elif item.product and item.product.kind in (
            Product.KIND_BULK,
            Product.KIND_PACKED,
        ):
            kind = "Bulk (measured)" if item.product.kind == Product.KIND_BULK else "Packed bottle"
            rows.append(
                [
                    kind,
                    item.product.name,
                    item.quantity,
                    item.product.unit,
                    item.line_total,
                    item.cogs,
                    item.line_total - item.cogs,
                ]
            )
    return {
        "title": "Perfume sales",
        "columns": ["Type", "Perfume", "Quantity", "Unit", "Revenue", "Cost", "Profit"],
        "rows": rows,
        "summary": [
            ("Lines", len(rows)),
            ("Revenue", sum((r[4] for r in rows), Decimal("0"))),
            ("Profit", sum((r[6] for r in rows), Decimal("0"))),
        ],
    }


def report_movements(start, end):
    movements = list(
        StockMovement.objects.filter(created_at__date__range=(start, end))
        .select_related("product", "user")
        .order_by("-created_at")[:2000]
    )
    rows = [
        [
            movement.created_at,
            movement.product.name,
            movement.product.sku,
            movement.get_kind_display(),
            movement.quantity,
            movement.unit_cost,
            movement.balance_after,
            movement.user.username if movement.user else "—",
            movement.note,
        ]
        for movement in movements
    ]
    incoming = sum((m.quantity for m in movements if m.quantity > 0), Decimal("0"))
    outgoing = sum((-m.quantity for m in movements if m.quantity < 0), Decimal("0"))
    return {
        "title": "Stock movements",
        "columns": [
            "Date",
            "Product",
            "SKU",
            "Type",
            "Quantity",
            "Unit cost",
            "Balance after",
            "User",
            "Note",
        ],
        "rows": rows,
        "summary": [
            ("Movements", len(rows)),
            ("Units in", incoming),
            ("Units out", outgoing),
        ],
    }


REPORTS = {
    "sales": (report_sales, "Receipts, revenue, money received and outstanding balances."),
    "products": (report_products, "What sold, in which quantities, and the profit it made."),
    "inventory": (report_inventory, "Stock on hand, average cost and inventory value."),
    "purchases": (report_purchases, "Stock received from suppliers and what it cost."),
    "profit": (report_profit, "Revenue, cost of goods, gross profit and net operating profit."),
    "expenses": (report_expenses, "Operating expenses by date and category."),
    "perfumes": (report_perfumes, "Bulk millilitre sales, packed bottles and mixtures."),
    "movements": (report_movements, "Every stock increase and decrease with its reason."),
}


def build_report(slug, start, end):
    entry = REPORTS.get(slug)
    if not entry:
        return None
    builder = entry[0]
    report = builder(start, end)
    report["slug"] = slug
    report["start"] = start
    report["end"] = end
    report.setdefault("extra_summary", [])
    return report
