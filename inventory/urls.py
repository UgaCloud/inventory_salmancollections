from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("inventory/products/", views.products, name="products"),
    path("inventory/perfumes/", views.perfumes, name="perfumes"),
    path("inventory/categories/", views.categories, name="categories"),
    path("inventory/units/", views.units, name="units"),
    path("inventory/perfumes/<int:pk>/", views.perfume_detail, name="perfume_detail"),
    path("inventory/stock/", views.stock_overview, name="stock"),
    path("inventory/adjustments/", views.adjustments, name="adjustments"),
    path("inventory/pack/", views.pack, name="pack"),
    path("inventory/pack/options/", views.pack_options, name="pack_options"),
    path("inventory/import/", views.import_view, name="import"),
    path("inventory/import/template/", views.import_template, name="import_template"),
    path("purchases/", views.purchases, name="purchases"),
    path("purchases/suppliers/", views.suppliers, name="suppliers"),
    path("purchases/receive/", views.receive, name="receive"),
    path("purchases/<int:pk>/", views.purchase_detail, name="purchase_detail"),
]
