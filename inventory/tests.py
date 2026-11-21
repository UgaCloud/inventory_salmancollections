from decimal import Decimal

from django.test import TestCase

from core.models import PaymentMethod
from core.services import ensure_defaults
from core.testing import make_staff
from sales.models import Mixture, Sale
from sales.services import cancel_sale, checkout, prepare_mixture

from .models import Product, StockBatch, StockMovement, Supplier
from .services import (
    InsufficientStock,
    add_opening_stock,
    adjust_stock,
    pack_from_bulk,
    receive_purchase,
)


class InventoryTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.supplier = Supplier.objects.create(name="Supplier A")
        cls.cash = PaymentMethod.objects.get(is_default=True)

        cls.bulk = Product.objects.create(
            name="Oud Royale",
            sku="OUD-BULK",
            kind=Product.KIND_BULK,
            unit=Product.UNIT_ML,
            unit_price=Decimal("1.20"),
            reorder_level=Decimal("20"),
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

        cls.packed = Product.objects.create(
            name="Oud Royale 30ml",
            sku="OUD-30",
            kind=Product.KIND_PACKED,
            unit=Product.UNIT_BOTTLE,
            unit_price=Decimal("50.00"),
            bulk_parent=cls.bulk,
            packed_size_ml=Decimal("30"),
        )
        cls.standard = Product.objects.create(
            name="Leather Tote",
            sku="BAG-1",
            unit=Product.UNIT_PIECE,
            unit_price=Decimal("25.00"),
        )
        add_opening_stock(cls.standard, 10, Decimal("12.00"))

    def _sell(self, product, quantity, amount=None):
        amount = amount if amount is not None else product.price_for_quantity(quantity)
        return checkout(
            items=[{"product_id": product.pk, "quantity": Decimal(quantity)}],
            payments=[{"method": self.cash, "amount": Decimal(amount)}],
            cashier=self.owner,
        )

    def test_receive_stock_creates_batch_movement_and_average_cost(self):
        purchase = receive_purchase(
            supplier=self.supplier,
            items=[
                {
                    "product": self.bulk,
                    "quantity": Decimal("100"),
                    "unit_cost": Decimal("0.60"),
                }
            ],
            user=self.owner,
        )
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("200"))
        self.assertEqual(self.bulk.average_cost, Decimal("0.5500"))
        self.assertEqual(purchase.total_cost, Decimal("60.00"))
        batch = StockBatch.objects.filter(product=self.bulk).order_by("-id").first()
        self.assertEqual(batch.remaining, Decimal("100"))
        self.assertTrue(
            StockMovement.objects.filter(
                product=self.bulk,
                kind=StockMovement.KIND_RECEIPT,
                reference_id=str(purchase.pk),
            ).exists()
        )

    def test_bulk_sale_uses_preset_price_and_deducts_base_quantity(self):
        sale, _ = self._sell(self.bulk, "10", "11.00")
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("90"))
        self.assertEqual(sale.total, Decimal("11.00"))
        item = sale.items.get()
        self.assertEqual(item.quantity, Decimal("10"))
        self.assertEqual(item.cogs, Decimal("5.00"))
        self.assertEqual(sale.cogs, Decimal("5.00"))

    def test_custom_millilitre_sale_uses_price_per_ml(self):
        sale, _ = self._sell(self.bulk, "7", "8.40")
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("93"))
        self.assertEqual(sale.total, Decimal("8.40"))

    def test_packed_bottle_sale_does_not_touch_bulk_stock(self):
        pack_from_bulk(
            bulk_product=self.bulk,
            packed_product=self.packed,
            ml_per_bottle=Decimal("30"),
            bottles=2,
            user=self.owner,
        )
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("40"))
        sale, _ = self._sell(self.packed, "1", "50.00")
        self.packed.refresh_from_db()
        self.bulk.refresh_from_db()
        self.assertEqual(self.packed.stock_quantity, Decimal("1"))
        self.assertEqual(self.bulk.stock_quantity, Decimal("40"))
        self.assertEqual(sale.cogs, Decimal("15.00"))

    def test_pack_run_records_both_movements_and_cost(self):
        run = pack_from_bulk(
            bulk_product=self.bulk,
            packed_product=self.packed,
            ml_per_bottle=Decimal("30"),
            bottles=2,
            user=self.owner,
            extra_cost_per_bottle=Decimal("1.00"),
        )
        self.assertEqual(run.total_ml, Decimal("60"))
        self.assertEqual(run.total_cost, Decimal("32.00"))
        self.assertEqual(run.cost_per_bottle, Decimal("16.0000"))
        self.assertTrue(
            StockMovement.objects.filter(
                product=self.bulk,
                kind=StockMovement.KIND_PACK_OUT,
                reference_id=str(run.pk),
            ).exists()
        )
        self.assertTrue(
            StockMovement.objects.filter(
                product=self.packed,
                kind=StockMovement.KIND_PACK_IN,
                reference_id=str(run.pk),
            ).exists()
        )
        batch = self.packed.batches.get()
        self.assertEqual(batch.remaining, Decimal("2"))

    def test_pack_rejects_unlinked_packed_product(self):
        other = Product.objects.create(
            name="Other bottle",
            sku="OTHER-1",
            kind=Product.KIND_PACKED,
            unit=Product.UNIT_BOTTLE,
            unit_price=10,
        )
        with self.assertRaises(ValueError):
            pack_from_bulk(
                bulk_product=self.bulk,
                packed_product=other,
                ml_per_bottle=Decimal("10"),
                bottles=1,
                user=self.owner,
            )
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("100"))

    def test_sale_cancellation_restores_exact_base_quantity(self):
        sale, _ = self._sell(self.bulk, "7", "8.40")
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("93"))

        cancel_sale(sale=sale, user=self.owner, reason="Customer changed mind")
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("100"))
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.STATUS_CANCELLED)
        self.assertEqual(sale.refunded_amount, Decimal("8.40"))
        self.assertTrue(
            StockMovement.objects.filter(
                product=self.bulk,
                kind=StockMovement.KIND_SALE_CANCEL,
                reference_id=str(sale.pk),
            ).exists()
        )
        with self.assertRaises(ValueError):
            cancel_sale(sale=sale, user=self.owner, reason="Again")

    def test_over_adjustment_is_rejected_without_changing_stock(self):
        with self.assertRaises(InsufficientStock):
            adjust_stock(
                product=self.bulk,
                delta=Decimal("-500"),
                reason="damage",
                user=self.owner,
            )
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("100"))

    def test_adjustment_increase_creates_batch(self):
        adjust_stock(
            product=self.bulk,
            delta=Decimal("5"),
            reason="stock_take",
            user=self.owner,
            note="Found extra",
        )
        self.bulk.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("105"))
        self.assertEqual(self.bulk.batches.count(), 2)

    def _mixture(self, ml_one=10, ml_two=10, price="40.00"):
        return prepare_mixture(
            name="Signature Blend",
            components=[
                {"product": self.bulk, "quantity_ml": Decimal(ml_one)},
                {"product": self.bulk2, "quantity_ml": Decimal(ml_two)},
            ],
            price=Decimal(price),
            user=self.owner,
        )

    def test_preparing_mixture_does_not_deduct_stock(self):
        mixture = self._mixture()
        self.bulk.refresh_from_db()
        self.bulk2.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("100"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("100"))
        self.assertEqual(mixture.total_ml, Decimal("20"))
        self.assertEqual(mixture.total_cost, Decimal("7.00"))
        self.assertEqual(mixture.status, Mixture.STATUS_PREPARED)

    def test_mixture_sale_deducts_every_component_and_cannot_sell_twice(self):
        mixture = self._mixture()
        sale, _ = checkout(
            items=[{"mixture_id": mixture.pk}],
            payments=[{"method": self.cash, "amount": Decimal("40.00")}],
            cashier=self.owner,
        )
        self.bulk.refresh_from_db()
        self.bulk2.refresh_from_db()
        mixture.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("90"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("90"))
        self.assertEqual(mixture.status, Mixture.STATUS_SOLD)
        item = sale.items.get()
        self.assertEqual(item.line_total, Decimal("40.00"))
        self.assertEqual(item.cogs, Decimal("7.00"))
        with self.assertRaises(ValueError):
            checkout(
                items=[{"mixture_id": mixture.pk}],
                payments=[{"method": self.cash, "amount": Decimal("40.00")}],
                cashier=self.owner,
            )

    def test_mixture_sale_fails_atomically_when_one_component_is_short(self):
        adjust_stock(
            product=self.bulk2,
            delta=Decimal("-95"),
            reason="damage",
            user=self.owner,
        )
        mixture = self._mixture(ml_two=10)
        movement_count = StockMovement.objects.count()
        with self.assertRaises(InsufficientStock):
            checkout(
                items=[{"mixture_id": mixture.pk}],
                payments=[{"method": self.cash, "amount": Decimal("40.00")}],
                cashier=self.owner,
            )
        self.bulk.refresh_from_db()
        self.bulk2.refresh_from_db()
        mixture.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("100"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("5"))
        self.assertEqual(mixture.status, Mixture.STATUS_PREPARED)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_mixture_sale_cancellation_restores_components_and_status(self):
        mixture = self._mixture()
        sale, _ = checkout(
            items=[{"mixture_id": mixture.pk}],
            payments=[{"method": self.cash, "amount": Decimal("40.00")}],
            cashier=self.owner,
        )
        cancel_sale(sale=sale, user=self.owner, reason="Returned")
        self.bulk.refresh_from_db()
        self.bulk2.refresh_from_db()
        mixture.refresh_from_db()
        self.assertEqual(self.bulk.stock_quantity, Decimal("100"))
        self.assertEqual(self.bulk2.stock_quantity, Decimal("100"))
        self.assertEqual(mixture.status, Mixture.STATUS_PREPARED)
