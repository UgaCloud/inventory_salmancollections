import os
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import ShopSettings
from core.utils import money


def product_image_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"products/{uuid.uuid4().hex}{ext}"


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    KIND_STANDARD = "standard"
    KIND_BULK = "bulk_perfume"
    KIND_PACKED = "packed_perfume"
    KIND_CHOICES = [
        (KIND_STANDARD, "Boutique product"),
        (KIND_BULK, "Bulk perfume (sold by ml)"),
        (KIND_PACKED, "Packed perfume bottle"),
    ]

    UNIT_PIECE = "pcs"
    UNIT_PAIR = "pair"
    UNIT_ML = "ml"
    UNIT_BOTTLE = "bottle"
    UNIT_CHOICES = [
        (UNIT_PIECE, "Pieces"),
        (UNIT_PAIR, "Pairs"),
        (UNIT_ML, "Millilitres"),
        (UNIT_BOTTLE, "Bottles"),
    ]

    name = models.CharField(max_length=150)
    sku = models.CharField(max_length=60, unique=True)
    barcode = models.CharField(max_length=80, unique=True, blank=True, null=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_STANDARD)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default=UNIT_PIECE)
    brand = models.CharField(max_length=100, blank=True)
    concentration = models.CharField(
        max_length=40, blank=True, help_text="E.g. EDP, EDT, Parfum."
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=product_image_path, blank=True, null=True)
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="Selling price per base unit (piece, pair, ml or bottle).",
    )
    average_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    is_active = models.BooleanField(default=True)
    preset_sizes = models.JSONField(
        default=list,
        blank=True,
        help_text='Bulk perfumes: [{"ml": "10", "price": "12.00"}, ...]',
    )
    bulk_parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="packed_products",
        help_text="The bulk perfume this packed bottle belongs to.",
    )
    packed_size_ml = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.kind == self.KIND_BULK and self.unit != self.UNIT_ML:
            raise ValidationError({"unit": "Bulk perfumes must be measured in millilitres."})
        if self.bulk_parent_id and self.bulk_parent_id == self.pk:
            raise ValidationError({"bulk_parent": "A product cannot belong to itself."})
        if self.bulk_parent and self.bulk_parent.kind != self.KIND_BULK:
            raise ValidationError(
                {"bulk_parent": "The linked perfume must be a bulk perfume."}
            )

    @property
    def stock_quantity(self):
        balance = getattr(self, "balance", None)
        return balance.quantity if balance else Decimal("0")

    @property
    def stock_value(self):
        # .all() honours a prefetched cache; the related manager itself cannot be summed.
        return sum(
            (b.remaining * b.unit_cost for b in self.batches.all()), Decimal("0")
        )

    @property
    def is_low_stock(self):
        threshold = self.reorder_level or Decimal("0")
        return threshold > 0 and self.stock_quantity <= threshold

    @property
    def is_out_of_stock(self):
        return self.stock_quantity <= 0

    @property
    def is_perfume(self):
        return self.kind in (self.KIND_BULK, self.KIND_PACKED)

    @property
    def unit_label(self):
        return self.get_unit_display().lower().rstrip("s")

    def price_for_quantity(self, quantity) -> Decimal:
        quantity = Decimal(quantity)
        if self.kind == self.KIND_BULK:
            for preset in self.preset_sizes or []:
                try:
                    if Decimal(str(preset.get("ml"))) == quantity:
                        return money(preset.get("price"))
                except Exception:
                    continue
        return money(Decimal(self.unit_price) * quantity)

    def get_absolute_url(self):
        if self.kind == self.KIND_BULK:
            return reverse("inventory:perfume_detail", args=[self.pk])
        return reverse("inventory:products") + f"?edit={self.pk}"


class StockBalance(models.Model):
    product = models.OneToOneField(
        Product, on_delete=models.CASCADE, related_name="balance"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.name}: {self.quantity}"


class StockBatch(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="batches"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True
    )
    received_at = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    remaining = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at", "id"]
        verbose_name_plural = "stock batches"

    def __str__(self):
        return f"{self.product.name} batch #{self.pk}"

    @property
    def value(self):
        return self.remaining * self.unit_cost


class StockMovement(models.Model):
    KIND_RECEIPT = "receipt"
    KIND_OPENING = "opening"
    KIND_SALE = "sale"
    KIND_SALE_CANCEL = "sale_cancel"
    KIND_ADJUSTMENT = "adjustment"
    KIND_PACK_OUT = "pack_out"
    KIND_PACK_IN = "pack_in"
    KIND_MIXTURE_SALE = "mixture_sale"
    KIND_MIXTURE_CANCEL = "mixture_cancel"
    KIND_CHOICES = [
        (KIND_RECEIPT, "Stock received"),
        (KIND_OPENING, "Opening stock"),
        (KIND_SALE, "Sale"),
        (KIND_SALE_CANCEL, "Sale cancellation"),
        (KIND_ADJUSTMENT, "Stock adjustment"),
        (KIND_PACK_OUT, "Packed from bulk (out)"),
        (KIND_PACK_IN, "Packed from bulk (in)"),
        (KIND_MIXTURE_SALE, "Mixture sold"),
        (KIND_MIXTURE_CANCEL, "Mixture sale cancelled"),
    ]

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="movements"
    )
    batch = models.ForeignKey(
        StockBatch, on_delete=models.SET_NULL, null=True, blank=True
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    quantity = models.DecimalField(
        max_digits=14, decimal_places=3, help_text="Positive in, negative out."
    )
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    balance_after = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    reference_type = models.CharField(max_length=40, blank=True)
    reference_id = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.product.name}"


class Purchase(models.Model):
    number = models.CharField(max_length=30, unique=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, related_name="purchases"
    )
    purchase_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=80, blank=True)
    note = models.TextField(blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.number

    @property
    def total_quantity(self):
        return sum((line.quantity for line in self.lines.all()), Decimal("0"))


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_lines"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    expiry_date = models.DateField(null=True, blank=True)
    batch = models.ForeignKey(
        StockBatch, on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"{self.product} x {self.quantity}"


class StockAdjustment(models.Model):
    REASON_CHOICES = [
        ("stock_take", "Stock take correction"),
        ("damage", "Damaged goods"),
        ("expired", "Expired goods"),
        ("theft", "Loss or theft"),
        ("return", "Returned to supplier"),
        ("other", "Other"),
    ]
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="adjustments"
    )
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3)
    balance_after = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.product} {self.quantity_delta}"


class PackRun(models.Model):
    bulk_product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="pack_runs"
    )
    packed_product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="packed_runs"
    )
    ml_per_bottle = models.DecimalField(max_digits=12, decimal_places=3)
    bottles = models.PositiveIntegerField()
    total_ml = models.DecimalField(max_digits=14, decimal_places=3)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2)
    cost_per_bottle = models.DecimalField(max_digits=14, decimal_places=4)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.bottles} x {self.packed_product} from {self.bulk_product}"
