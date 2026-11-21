from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from inventory.models import Product, StockBatch
from core.models import PaymentMethod


class Customer(models.Model):
    name = models.CharField(max_length=150)
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

    @property
    def outstanding_balance(self):
        return (
            Sale.objects.filter(customer=self, status=Sale.STATUS_COMPLETED).aggregate(
                total=Sum("balance")
            )["total"]
            or Decimal("0")
        )

    def get_absolute_url(self):
        return reverse("customers:detail", args=[self.pk])


class Sale(models.Model):
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    number = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales"
    )
    cashier = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, related_name="sales"
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_COMPLETED)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    change_given = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cogs = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, help_text="Cost of goods sold."
    )
    refunded_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_sales",
    )
    cancel_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.number

    @property
    def gross_profit(self):
        return self.total - self.cogs

    @property
    def is_cancelled(self):
        return self.status == self.STATUS_CANCELLED

    def get_absolute_url(self):
        return reverse("sales:detail", args=[self.pk])


class Mixture(models.Model):
    STATUS_PREPARED = "prepared"
    STATUS_SOLD = "sold"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PREPARED, "Prepared"),
        (STATUS_SOLD, "Sold"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    name = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    total_ml = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PREPARED)
    prepared_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, related_name="mixtures"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sold_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name

    @property
    def profit(self):
        return self.price - self.total_cost


class MixtureComponent(models.Model):
    mixture = models.ForeignKey(
        Mixture, on_delete=models.CASCADE, related_name="components"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="mixture_components"
    )
    quantity_ml = models.DecimalField(max_digits=14, decimal_places=3)
    cost_per_ml = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.product} {self.quantity_ml}ml"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, null=True, blank=True, related_name="sale_items"
    )
    mixture = models.ForeignKey(
        Mixture, on_delete=models.SET_NULL, null=True, blank=True, related_name="sale_items"
    )
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(
        max_digits=14, decimal_places=3, help_text="In the product's base unit."
    )
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    cogs = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_measurement = models.BooleanField(default=False)

    def __str__(self):
        return self.description


class StockConsumption(models.Model):
    """The exact batch quantities a sale line deducted, kept for exact reversal."""

    sale_item = models.ForeignKey(
        SaleItem, on_delete=models.CASCADE, related_name="consumptions"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sale_consumptions"
    )
    batch = models.ForeignKey(
        StockBatch, on_delete=models.SET_NULL, null=True, blank=True
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.product} {self.quantity}"


class SalePayment(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True
    )
    method_name = models.CharField(max_length=60, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.method_name} {self.amount}"


class Refund(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="refunds")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method_name = models.CharField(max_length=60, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.amount} for {self.sale.number}"


class CustomerPayment(models.Model):
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="payments"
    )
    sale = models.ForeignKey(
        Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="customer_payments"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True
    )
    method_name = models.CharField(max_length=60, blank=True)
    date = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)
    reference = models.CharField(max_length=40, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.customer} {self.amount}"
