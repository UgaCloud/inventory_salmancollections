from django.db import models
from django.utils import timezone

from core.models import PaymentMethod


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "expense categories"

    def __str__(self):
        return self.name


class Expense(models.Model):
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )
    date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True
    )
    method_name = models.CharField(max_length=60, blank=True)
    description = models.CharField(max_length=200)
    reference = models.CharField(max_length=80, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.description} {self.amount}"

    def save(self, *args, **kwargs):
        if self.payment_method and not self.method_name:
            self.method_name = self.payment_method.name
        super().save(*args, **kwargs)


class CashReconciliation(models.Model):
    date = models.DateField(default=timezone.localdate, unique=True)
    opening_float = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    counted_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Cash reconciliation {self.date}"
