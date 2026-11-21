from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import PaymentMethod
from core.services import ensure_defaults
from core.testing import make_staff
from inventory.models import Product
from inventory.services import add_opening_stock
from sales.models import Customer
from sales.services import cancel_sale, checkout, record_customer_payment

from .models import Expense
from .services import expected_cash


class ExpectedCashTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.cash = PaymentMethod.objects.get(is_default=True)
        cls.tote = Product.objects.create(
            name="Tote", sku="CASH-1", unit=Product.UNIT_PIECE,
            unit_price=Decimal("25.00"),
        )
        add_opening_stock(cls.tote, 10, Decimal("10.00"))

    def test_change_is_deducted_from_the_drawer(self):
        checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("2")}],
            payments=[{"method": self.cash, "amount": Decimal("60")}],
            cashier=self.owner,
        )
        self.assertEqual(
            expected_cash(timezone.localdate(), Decimal("100")), Decimal("150.00")
        )

    def test_same_day_cancellation_nets_out(self):
        sale, _ = checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("2")}],
            payments=[{"method": self.cash, "amount": Decimal("60")}],
            cashier=self.owner,
        )
        cancel_sale(sale=sale, user=self.owner, reason="Returned")
        self.assertEqual(
            expected_cash(timezone.localdate(), Decimal("100")), Decimal("100.00")
        )

    def test_customer_payments_and_cash_expenses_are_included(self):
        customer = Customer.objects.create(name="Amina")
        checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("2")}],
            payments=[{"method": self.cash, "amount": Decimal("20")}],
            cashier=self.owner,
            customer=customer,
        )
        record_customer_payment(
            customer=customer, amount=Decimal("30"), method=self.cash, user=self.owner
        )
        Expense.objects.create(
            date=timezone.localdate(), amount=Decimal("12.50"),
            payment_method=self.cash, method_name="Cash", description="Cleaning",
        )
        # 100 float + 20 paid at the till + 30 customer payment - 12.50 expense
        self.assertEqual(
            expected_cash(timezone.localdate(), Decimal("100")), Decimal("137.50")
        )
