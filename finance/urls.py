from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("finance/expenses/", views.expenses, name="expenses"),
    path("finance/cash/", views.cash, name="cash"),
]
