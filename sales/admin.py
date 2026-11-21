from django.contrib import admin

from .models import (
    Customer,
    CustomerPayment,
    Mixture,
    MixtureComponent,
    Refund,
    Sale,
    SaleItem,
    SalePayment,
    StockConsumption,
)


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


class SalePaymentInline(admin.TabularInline):
    model = SalePayment
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("number", "created_at", "customer", "cashier", "total", "paid", "balance", "status")
    list_filter = ("status",)
    search_fields = ("number", "customer__name")
    inlines = [SaleItemInline, SalePaymentInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "is_active")
    search_fields = ("name", "phone", "email")


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ("sale", "description", "quantity", "line_total", "cogs")
    search_fields = ("description", "sale__number")


class MixtureComponentInline(admin.TabularInline):
    model = MixtureComponent
    extra = 0


@admin.register(Mixture)
class MixtureAdmin(admin.ModelAdmin):
    list_display = ("name", "total_ml", "total_cost", "price", "status", "created_at")
    list_filter = ("status",)
    inlines = [MixtureComponentInline]


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ("customer", "amount", "method_name", "date", "sale")
    search_fields = ("customer__name", "reference")


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("sale", "amount", "reason", "created_at", "user")


@admin.register(StockConsumption)
class StockConsumptionAdmin(admin.ModelAdmin):
    list_display = ("sale_item", "product", "quantity", "unit_cost", "amount")
