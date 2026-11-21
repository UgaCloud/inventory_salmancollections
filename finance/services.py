from decimal import Decimal

from django.db.models import Q, Sum

from sales.models import CustomerPayment, Refund, Sale, SalePayment

from .models import Expense

CASH_FILTER = Q(method__kind="cash") | Q(
    method__isnull=True, method_name__iexact="cash"
)
EXPENSE_CASH_FILTER = Q(payment_method__kind="cash") | Q(
    payment_method__isnull=True, method_name__iexact="cash"
)


def expected_cash(day, opening_float=Decimal("0")):
    """Expected cash in the drawer: float + cash in - cash out."""
    # Count every tender taken that day, cancelled sales included: a same-day
    # cancellation is reversed by its refund below, not by hiding the intake.
    cash_in = (
        SalePayment.objects.filter(
            CASH_FILTER,
            sale__created_at__date=day,
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    customer_in = (
        CustomerPayment.objects.filter(CASH_FILTER, date=day).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0")
    )
    refunds_out = (
        Refund.objects.filter(created_at__date=day).aggregate(total=Sum("amount"))[
            "total"
        ]
        or Decimal("0")
    )
    change_out = (
        Sale.objects.filter(created_at__date=day).aggregate(
            total=Sum("change_given")
        )["total"]
        or Decimal("0")
    )
    cash_expenses = (
        Expense.objects.filter(EXPENSE_CASH_FILTER, date=day).aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0")
    )
    expected = (
        Decimal(opening_float)
        + cash_in
        + customer_in
        - change_out
        - refunds_out
        - cash_expenses
    )
    return expected.quantize(Decimal("0.01"))
