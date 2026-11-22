from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("settings/", views.settings_business, name="settings"),
    path("settings/pagination/", views.settings_pagination, name="settings_pagination"),
    path("settings/payment-methods/", views.payment_methods, name="payment_methods"),
    path("settings/users/", views.users, name="users"),
    path("settings/users/<int:pk>/role/", views.user_role, name="user_role"),
    path("settings/roles/", views.roles, name="roles"),
    path("settings/backups/", views.backups, name="backups"),
    path("settings/backups/<int:pk>/download/", views.backup_download, name="backup_download"),
    path("settings/audit/", views.audit_log, name="audit"),
    path("manifest.webmanifest", views.pwa_manifest, name="manifest"),
    path("service-worker.js", views.pwa_service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
]
