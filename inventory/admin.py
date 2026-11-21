from django.contrib import admin

from .models import (
    Category,
    PackRun,
    Product,
    Purchase,
    PurchaseLine,
    StockAdjustment,
    StockBalance,
    StockBatch,
    StockMovement,
    Supplier,
)


class StockBalanceInline(admin.StackedInline):
    model = StockBalance
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "kind", "unit", "unit_price", "average_cost", "is_active")
    list_filter = ("kind", "unit", "is_active", "category")
    search_fields = ("name", "sku", "barcode", "brand")
    inlines = [StockBalanceInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "is_active")
    search_fields = ("name", "contact_person", "phone")


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ("product", "received_at", "quantity", "remaining", "unit_cost", "expiry_date")
    list_filter = ("received_at",)
    search_fields = ("product__name", "reference")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "kind", "quantity", "balance_after", "user")
    list_filter = ("kind",)
    search_fields = ("product__name", "note")


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ("product", "quantity", "updated_at")
    search_fields = ("product__name",)


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("number", "supplier", "purchase_date", "total_cost", "user")
    search_fields = ("number", "supplier__name")
    inlines = [PurchaseLineInline]


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "quantity_delta", "balance_after", "reason", "user")


@admin.register(PackRun)
class PackRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "bulk_product", "packed_product", "ml_per_bottle", "bottles", "total_cost")
