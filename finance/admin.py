from django.contrib import admin

from .models import CashReconciliation, Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "description", "category", "amount", "method_name", "user")
    list_filter = ("category",)
    search_fields = ("description", "reference")


@admin.register(CashReconciliation)
class CashReconciliationAdmin(admin.ModelAdmin):
    list_display = ("date", "opening_float", "expected_cash", "counted_cash", "difference")
