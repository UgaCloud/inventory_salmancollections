from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import PaymentMethod
from core.services import ensure_defaults
from core.testing import make_staff
from inventory.models import Product
from inventory.services import add_opening_stock

from inventory.services import InsufficientStock

from .models import Customer, Mixture, Sale
from .services import cancel_sale, checkout, prepare_mixture, record_customer_payment


class SalesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.cash = PaymentMethod.objects.get(is_default=True)
        cls.bulk = Product.objects.create(
            name="Oud Royale",
            sku="OUD-BULK",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("1.20"),
            preset_sizes=[{"ml": "10", "price": "11.00"}],
        )
        add_opening_stock(cls.bulk, Decimal("100"), Decimal("0.50"))
        cls.bulk2 = Product.objects.create(
            name="White Musk",
            sku="MUSK-BULK",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("0.90"),
        )
        add_opening_stock(cls.bulk2, Decimal("100"), Decimal("0.20"))
        cls.tote = Product.objects.create(
            name="Leather Tote", sku="BAG-1", unit=Product.UNIT_PIECE,
            unit_price=Decimal("25.00"),
        )
        add_opening_stock(cls.tote, 10, Decimal("12.00"))

    def test_walk_in_change_is_not_counted_as_money_kept(self):
        sale, change = checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("2")}],
            payments=[{"method": self.cash, "amount": Decimal("60")}],
            cashier=self.owner,
        )
        self.assertEqual(change, Decimal("10.00"))
        self.assertEqual(sale.total, Decimal("50.00"))
        self.assertEqual(sale.paid, Decimal("50.00"))
        self.assertEqual(sale.change_given, Decimal("10.00"))
        self.assertEqual(sale.balance, Decimal("0.00"))

    def test_cancelling_a_sale_with_change_refunds_only_the_net(self):
        sale, _ = checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("2")}],
            payments=[{"method": self.cash, "amount": Decimal("60")}],
            cashier=self.owner,
        )
        cancel_sale(sale=sale, user=self.owner, reason="Returned")
        sale.refresh_from_db()
        self.assertEqual(sale.refunded_amount, Decimal("50.00"))
        self.assertEqual(sale.refunds.get().amount, Decimal("50.00"))

    def test_customer_credit_sale_and_settlement(self):
        customer = Customer.objects.create(name="Amina")
        sale, _ = checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("2")}],
            payments=[{"method": self.cash, "amount": Decimal("20")}],
            cashier=self.owner,
            customer=customer,
        )
        self.assertEqual(sale.total, Decimal("50.00"))
        self.assertEqual(sale.balance, Decimal("30.00"))
        self.assertEqual(customer.outstanding_balance, Decimal("30.00"))

        record_customer_payment(
            customer=customer, amount=Decimal("30"), method=self.cash, user=self.owner
        )
        sale.refresh_from_db()
        self.assertEqual(sale.balance, Decimal("0.00"))
        self.assertEqual(customer.outstanding_balance, Decimal("0.00"))
        with self.assertRaises(ValueError):
            record_customer_payment(
                customer=customer, amount=Decimal("1"), method=self.cash, user=self.owner
            )

    def test_perfume_and_mixture_pages_render_ui_filters(self):
        mixture = Mixture.objects.create(
            name="House Blend", price=Decimal("30"), total_ml=Decimal("20")
        )
        mixture.components.create(
            mixture=mixture, product=self.bulk, quantity_ml=Decimal("20"),
        )
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("inventory:perfumes")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("inventory:perfume_detail", args=[self.bulk.pk])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("sales:mixtures")).status_code, 200)


class PosEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.cash = PaymentMethod.objects.get(is_default=True)
        cls.tote = Product.objects.create(
            name="Leather Tote", sku="BAG-2", unit=Product.UNIT_PIECE,
            unit_price=Decimal("25.00"),
        )
        add_opening_stock(cls.tote, 5, Decimal("12.00"))

    def _post(self, payload):
        return self.client.post(
            reverse("sales:checkout"),
            data=payload,
            content_type="application/json",
        )

    def test_checkout_returns_change_and_receipt(self):
        self.client.force_login(self.owner)
        response = self._post(
            {
                "items": [{"product_id": self.tote.pk, "quantity": "1"}],
                "payments": [{"method_id": self.cash.pk, "amount": "30"}],
                "customer_id": None,
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["change"], "5.00")
        self.assertEqual(self.client.get(data["receipt_url"]).status_code, 200)
        sale = Sale.objects.get(pk=data["sale_id"])
        self.assertEqual(sale.paid, Decimal("25.00"))

    def test_oversell_returns_clean_json_error_and_keeps_stock(self):
        self.client.force_login(self.owner)
        response = self._post(
            {
                "items": [{"product_id": self.tote.pk, "quantity": "99"}],
                "payments": [{"method_id": self.cash.pk, "amount": "99"}],
                "customer_id": None,
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.tote.refresh_from_db()
        self.assertEqual(self.tote.stock_quantity, Decimal("5"))
        self.assertEqual(Sale.objects.count(), 0)

    def test_cashier_cannot_cancel_a_sale(self):
        cashier = make_staff("cashier", "cashier")
        sale, _ = checkout(
            items=[{"product_id": self.tote.pk, "quantity": Decimal("1")}],
            payments=[{"method": self.cash, "amount": Decimal("25")}],
            cashier=self.owner,
        )
        self.client.force_login(cashier)
        response = self.client.post(
            reverse("sales:cancel", args=[sale.pk]), {"reason": "test"}
        )
        self.assertEqual(response.status_code, 403)
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.STATUS_COMPLETED)


class MixedCartSaleTests(TestCase):
    """Boutique items, measured perfume, packed bottles and mixtures in one sale."""

    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("mixowner", "owner", superuser=True)
        cls.cash = PaymentMethod.objects.get(is_default=True)
        cls.bulk = Product.objects.create(
            name="Oud Royale",
            sku="MIX-OUD",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("1.20"),
        )
        add_opening_stock(cls.bulk, Decimal("100"), Decimal("0.50"))
        cls.bulk2 = Product.objects.create(
            name="White Musk",
            sku="MIX-MUSK",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("0.90"),
        )
        add_opening_stock(cls.bulk2, Decimal("100"), Decimal("0.20"))
        cls.packed = Product.objects.create(
            name="Oud Royale 30ml",
            sku="MIX-OUD-30",
            kind=Product.KIND_PACKED,
            unit=Product.UNIT_BOTTLE,
            unit_price=Decimal("30.00"),
            bulk_parent=cls.bulk,
            packed_size_ml=Decimal("30"),
        )
        add_opening_stock(cls.packed, Decimal("4"), Decimal("15.00"))
        cls.tote = Product.objects.create(
            name="Leather Tote",
            sku="MIX-BAG",
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("25.00"),
        )
        add_opening_stock(cls.tote, Decimal("10"), Decimal("12.00"))

    def test_mixed_cart_sale_deducts_every_line_and_reverses_exactly(self):
        mixture = prepare_mixture(
            name="House blend",
            components=[
                {"product": self.bulk, "quantity_ml": Decimal("10")},
                {"product": self.bulk2, "quantity_ml": Decimal("5")},
            ],
            price=Decimal("30.00"),
            user=self.owner,
        )
        sale, change = checkout(
            items=[
                {"product_id": self.bulk.pk, "quantity": Decimal("12.5")},
                {"product_id": self.bulk2.pk, "quantity": Decimal("6")},
                {"product_id": self.packed.pk, "quantity": Decimal("1")},
                {"product_id": self.tote.pk, "quantity": Decimal("1")},
                {"mixture_id": mixture.pk},
            ],
            payments=[{"method": self.cash, "amount": Decimal("120")}],
            cashier=self.owner,
        )
        self.assertEqual(sale.total, Decimal("105.40"))
        self.assertEqual(change, Decimal("14.60"))
        self.assertEqual(sale.paid, Decimal("105.40"))
        self.assertEqual(sale.items.count(), 5)
        mixture.refresh_from_db()
        self.assertEqual(mixture.status, Mixture.STATUS_SOLD)
        self.assertEqual(self.bulk.stock_quantity, Decimal("77.500"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("89.000"))
        self.assertEqual(self.packed.stock_quantity, Decimal("3.000"))
        self.assertEqual(self.tote.stock_quantity, Decimal("9.000"))

        cancel_sale(sale=sale, user=self.owner, reason="Customer returned the basket")
        sale.refresh_from_db()
        mixture.refresh_from_db()
        for product in (self.bulk, self.bulk2, self.packed, self.tote):
            product.refresh_from_db()
        self.assertEqual(sale.status, Sale.STATUS_CANCELLED)
        self.assertEqual(mixture.status, Mixture.STATUS_PREPARED)
        self.assertEqual(self.bulk.stock_quantity, Decimal("100.000"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("100.000"))
        self.assertEqual(self.packed.stock_quantity, Decimal("4.000"))
        self.assertEqual(self.tote.stock_quantity, Decimal("10.000"))

    def test_packed_bottle_oversell_rolls_the_whole_cart_back(self):
        with self.assertRaises(InsufficientStock):
            checkout(
                items=[
                    {"product_id": self.tote.pk, "quantity": Decimal("1")},
                    {"product_id": self.packed.pk, "quantity": Decimal("5")},
                ],
                payments=[{"method": self.cash, "amount": Decimal("200")}],
                cashier=self.owner,
            )
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(self.tote.stock_quantity, Decimal("10.000"))
        self.assertEqual(self.packed.stock_quantity, Decimal("4.000"))


class DirectMixtureSaleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("mixsell", "owner", superuser=True)
        cls.cash = PaymentMethod.objects.get(is_default=True)
        cls.bulk = Product.objects.create(
            name="Oud",
            sku="MS-OUD",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("1.20"),
        )
        add_opening_stock(cls.bulk, Decimal("100"), Decimal("0.50"))
        cls.bulk2 = Product.objects.create(
            name="Musk",
            sku="MS-MUSK",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("0.90"),
        )
        add_opening_stock(cls.bulk2, Decimal("100"), Decimal("0.20"))
        cls.mixture = prepare_mixture(
            name="Counter blend",
            components=[
                {"product": cls.bulk, "quantity_ml": Decimal("10")},
                {"product": cls.bulk2, "quantity_ml": Decimal("5")},
            ],
            price=Decimal("30.00"),
            user=cls.owner,
        )

    def test_direct_sale_completes_with_change_and_deducts_components(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("sales:mixture_sell", args=[self.mixture.pk]),
            {"method": self.cash.pk, "amount": "40", "customer": "", "note": "Counter sale"},
        )
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual(sale.total, Decimal("30.00"))
        self.assertEqual(sale.change_given, Decimal("10.00"))
        self.assertEqual(sale.items.count(), 1)
        self.assertIn(reverse("sales:detail", args=[sale.pk]), response.url)
        self.mixture.refresh_from_db()
        self.assertEqual(self.mixture.status, Mixture.STATUS_SOLD)
        self.assertEqual(self.bulk.stock_quantity, Decimal("90.000"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("95.000"))

    def test_walk_in_underpayment_is_rejected_and_mixture_stays_ready(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("sales:mixture_sell", args=[self.mixture.pk]),
            {"method": self.cash.pk, "amount": "20", "customer": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("sell=", response.url)
        self.assertEqual(Sale.objects.count(), 0)
        self.mixture.refresh_from_db()
        self.assertEqual(self.mixture.status, Mixture.STATUS_PREPARED)

    def test_a_mixture_can_only_be_sold_once(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("sales:mixture_sell", args=[self.mixture.pk]),
            {"method": self.cash.pk, "amount": "30", "customer": ""},
        )
        response = self.client.post(
            reverse("sales:mixture_sell", args=[self.mixture.pk]),
            {"method": self.cash.pk, "amount": "30", "customer": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("sales:mixtures"))
        self.assertEqual(Sale.objects.count(), 1)


class SeedDemoTests(TestCase):
    def test_seed_demo_fills_the_system_and_is_idempotent(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_demo", stdout=StringIO())
        product_count = Product.objects.count()
        sale_count = Sale.objects.count()
        self.assertGreaterEqual(product_count, 12)
        self.assertGreaterEqual(sale_count, 10)
        self.assertTrue(Customer.objects.count() >= 10)
        self.assertTrue(Mixture.objects.exists())

        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Product.objects.count(), product_count)
        self.assertEqual(Sale.objects.count(), sale_count)
