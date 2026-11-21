import os
import uuid

from django.conf import settings
from django.db import models


def logo_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".png"
    return f"shop/logo/{uuid.uuid4().hex}{ext}"


class ShopSettings(models.Model):
    """Singleton row holding the shop's business and receipt configuration."""

    name = models.CharField("Business name", max_length=150, default="My Boutique")
    currency_code = models.CharField(max_length=10, default="USD")
    currency_symbol = models.CharField(max_length=5, default="$")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to=logo_upload_to, blank=True, null=True)
    receipt_header = models.CharField(
        max_length=200, blank=True, help_text="Shown under the shop name on receipts."
    )
    receipt_footer = models.TextField(
        blank=True, default="Thank you for your business."
    )
    receipt_show_logo = models.BooleanField(default=True)
    allow_partial_payments = models.BooleanField(default=True)
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=3, default=5)
    auto_backup_enabled = models.BooleanField(default=False)
    backup_retention = models.PositiveIntegerField(default=10)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shop settings"
        verbose_name_plural = "Shop settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.name


class Role(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    permissions = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def permission_count(self):
        return len(self.permissions or [])


class StaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True, related_name="staff"
    )
    phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__first_name", "user__username"]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"

    def has_perm(self, code: str) -> bool:
        if self.user.is_superuser:
            return True
        if not self.is_active or not self.role:
            return False
        return code in (self.role.permissions or [])


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class PaymentMethod(models.Model):
    KIND_CHOICES = [
        ("cash", "Cash"),
        ("card", "Card"),
        ("mobile", "Mobile money"),
        ("bank", "Bank transfer"),
        ("other", "Other"),
    ]
    name = models.CharField(max_length=60, unique=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="cash")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            PaymentMethod.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class BackupRecord(models.Model):
    KIND_CHOICES = [
        ("manual", "Manual"),
        ("automatic", "Automatic"),
        ("safety", "Safety (before restore)"),
    ]
    filename = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="manual")
    note = models.CharField(max_length=200, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename
