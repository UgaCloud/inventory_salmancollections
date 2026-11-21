from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("customers/", views.customers, name="customers"),
    path("customers/payments/", views.payments, name="payments"),
    path("customers/<int:pk>/", views.customer_detail, name="detail"),
    path("customers/<int:pk>/payments/", views.record_payment, name="record_payment"),
]
