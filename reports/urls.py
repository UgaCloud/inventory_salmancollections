from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("<slug:slug>/", views.view_report, name="view"),
]
