from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("pos/", views.pos, name="pos"),
    path("pos/catalogue/", views.pos_catalogue, name="catalogue"),
    path("pos/checkout/", views.pos_checkout, name="checkout"),
    path("sales/mixtures/", views.mixtures, name="mixtures"),
    path("sales/mixtures/<int:pk>/sell/", views.mixture_sell, name="mixture_sell"),
    path("sales/", views.sales, name="list"),
    path("sales/<int:pk>/", views.sale_detail, name="detail"),
    path("sales/<int:pk>/receipt/", views.sale_receipt, name="receipt"),
    path("sales/<int:pk>/cancel/", views.cancel_sale_view, name="cancel"),
]
