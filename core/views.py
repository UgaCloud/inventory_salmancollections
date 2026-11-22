from datetime import datetime
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .audit import log_action
from .backup import (
    BackupError,
    create_backup,
    delete_backup,
    restore_backup,
)
from .dashboards import PERIOD_CHOICES, build_dashboard, resolve_period
from .decorators import perm_required
from .forms import (
    BusinessSettingsForm,
    LoginForm,
    PaginationForm,
    PaymentMethodForm,
    RoleForm,
    StaffUserForm,
)
from .http import form_errors, is_ajax, json_error, json_ok, wants_fragment
from .models import AuditLog, BackupRecord, PaymentMethod, Role, ShopSettings, StaffProfile
from .pagination import PAGINATION_SECTIONS, page_size_for
from .permissions import (
    AUDIT_VIEW,
    BACKUP_MANAGE,
    DASHBOARD_VIEW,
    SETTINGS_MANAGE,
    USERS_MANAGE,
    user_permissions,
)


def paginate(request, queryset, section="default"):
    return Paginator(queryset, page_size_for(section)).get_page(request.GET.get("page"))


def permission_denied_view(request, exception=None):
    return render(request, "403.html", status=403)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        log_action(action="Signed in", user=form.get_user(), request=request)
        return redirect(request.GET.get("next") or "core:dashboard")
    return render(request, "core/login.html", {"form": form})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        log_action(action="Signed out", user=request.user, request=request)
    auth_logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("core:login")


@perm_required(DASHBOARD_VIEW)
def dashboard(request):
    period, start, end, subtitle = resolve_period(request.GET)
    context = build_dashboard(request.user, start, end)
    context.update(
        {
            "period": period,
            "period_choices": PERIOD_CHOICES,
            "start": start,
            "end": end,
            "period_subtitle": subtitle,
            "today": timezone.localdate(),
            "audit_events": (
                AuditLog.objects.select_related("user").all()[:6]
                if AUDIT_VIEW in user_permissions(request.user)
                else []
            ),
        }
    )
    return render(request, "core/dashboard.html", context)


@perm_required(SETTINGS_MANAGE)
def settings_business(request):
    shop = ShopSettings.load()
    form = BusinessSettingsForm(instance=shop)
    if request.method == "POST":
        form = BusinessSettingsForm(request.POST, request.FILES, instance=shop)
        if form.is_valid():
            form.save()
            log_action(action="Business settings updated", user=request.user, target=shop, request=request)
            if is_ajax(request):
                return json_ok("Business settings saved.", refresh=True)
            messages.success(request, "Business settings saved.")
            return redirect("core:settings")
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    return render(request, "core/settings_business.html", {"form": form, "shop": shop})


@perm_required(SETTINGS_MANAGE)
def settings_pagination(request):
    shop = ShopSettings.load()
    form = PaginationForm(instance=shop)
    if request.method == "POST":
        form = PaginationForm(request.POST, instance=shop)
        if form.is_valid():
            form.save()
            log_action(action="Pagination settings updated", user=request.user, target=shop, request=request)
            if is_ajax(request):
                return json_ok("Pagination settings saved.", refresh=True)
            messages.success(request, "Pagination settings saved.")
            return redirect("core:settings_pagination")
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    return render(
        request,
        "core/settings_pagination.html",
        {
            "form": form,
            "shop": shop,
            "sections": PAGINATION_SECTIONS,
            "sizes": [(label, page_size_for(key)) for key, label in PAGINATION_SECTIONS],
        },
    )


@perm_required(SETTINGS_MANAGE)
def payment_methods(request):
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(PaymentMethod, pk=request.GET["edit"])
    form = PaymentMethodForm(instance=editing)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            method = get_object_or_404(PaymentMethod, pk=request.POST.get("id"))
            method_name = method.name
            method.delete()
            log_action(action="Payment method deleted", user=request.user, detail={"name": method_name}, request=request)
            if is_ajax(request):
                return json_ok("Payment method deleted.", refresh_list=True)
            messages.success(request, "Payment method deleted.")
            return redirect("core:payment_methods")
        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(PaymentMethod, pk=request.POST["id"])
        form = PaymentMethodForm(request.POST, instance=instance)
        if form.is_valid():
            method = form.save()
            log_action(action="Payment method saved", user=request.user, target=method, request=request)
            if is_ajax(request):
                return json_ok(
                    "Payment method saved.",
                    refresh_list=True,
                    redirect="" if instance is None else request.path,
                )
            messages.success(request, "Payment method saved.")
            return redirect("core:payment_methods")
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    methods = PaymentMethod.objects.all()
    context = {
        "form": form,
        "editing": editing,
        "methods": methods,
        "list_url": request.path,
        "page_title": "Payment methods",
    }
    fragment = wants_fragment(request)
    if fragment == "list":
        return render(request, "core/_payment_list.html", context)
    if fragment == "form":
        return render(request, "core/_payment_form.html", context)
    return render(request, "core/payment_methods.html", context)


@perm_required(USERS_MANAGE)
def users(request):
    profiles = StaffProfile.objects.select_related("user", "role")
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(StaffProfile, pk=request.GET["edit"])
    form = StaffUserForm(profile=editing)
    if request.method == "POST":
        profile = None
        if request.POST.get("id"):
            profile = get_object_or_404(StaffProfile, pk=request.POST["id"])
        form = StaffUserForm(request.POST, profile=profile)
        if form.is_valid():
            if profile and profile.user_id == request.user.pk and not form.cleaned_data["is_active"]:
                form.add_error("is_active", "You cannot deactivate your own account.")
            elif profile and profile.user_id == request.user.pk and form.cleaned_data["role"].slug != "owner":
                form.add_error("role", "You cannot remove your own owner role.")
            else:
                saved = form.save()
                log_action(
                    action="User account saved",
                    user=request.user,
                    target=saved,
                    detail={"username": saved.user.username, "role": saved.role.name},
                    request=request,
                )
                if is_ajax(request):
                    return json_ok(
                        "User account saved.",
                        refresh_list=True,
                        redirect="" if profile is None else request.path,
                    )
                messages.success(request, "User account saved.")
                return redirect("core:users")
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    context = {
        "form": form,
        "editing": editing,
        "profiles": profiles,
        "roles": Role.objects.all(),
        "roles_count": Role.objects.count(),
        "list_url": request.path,
    }
    fragment = wants_fragment(request)
    if fragment == "list":
        return render(request, "core/_user_list.html", context)
    if fragment == "form":
        return render(request, "core/_user_form.html", context)
    return render(request, "core/users.html", context)


@perm_required(USERS_MANAGE)
@require_POST
def user_role(request, pk):
    """Change a staff member's role straight from the users table."""
    profile = get_object_or_404(StaffProfile.objects.select_related("user", "role"), pk=pk)
    role_id = (request.POST.get("role") or "").strip()
    role = get_object_or_404(Role, pk=role_id) if role_id else None
    if profile.user_id == request.user.pk and (role is None or role.slug != "owner"):
        return json_error("You cannot remove your own owner role.")
    profile.role = role
    profile.save(update_fields=["role"])
    log_action(
        action="User role changed",
        user=request.user,
        target=profile,
        detail={"username": profile.user.username, "role": role.name if role else "None"},
        request=request,
    )
    return json_ok(
        f"{profile.user.get_full_name() or profile.user.username} is now "
        f"{role.name if role else 'without a role'}.",
        refresh_list=True,
    )


def _unique_role_slug(name):
    base = slugify(name)[:50] or "role"
    slug = base
    suffix = 2
    while Role.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@perm_required(SETTINGS_MANAGE)
def roles(request):
    roles_list = list(Role.objects.all())
    creating = request.GET.get("new") == "1"
    role = None if creating else (roles_list[0] if roles_list else None)
    if not creating and request.GET.get("role"):
        role = get_object_or_404(Role, pk=request.GET["role"])
    form = RoleForm(instance=role)
    locked = bool(role and role.slug == "owner")
    if request.method == "POST":
        if request.POST.get("action") == "create":
            creating = True
            role = None
            form = RoleForm(request.POST)
            if form.is_valid():
                role = form.save(commit=False)
                role.slug = _unique_role_slug(role.name)
                role.is_system = False
                role.save()
                log_action(
                    action="Role created",
                    user=request.user,
                    target=role,
                    detail={"permissions": role.permissions},
                    request=request,
                )
                messages.success(request, f"Role “{role.name}” created.")
                return redirect(f"{request.path}?role={role.pk}")
            messages.error(request, "Please correct the errors below.")
        else:
            locked = False
            role = get_object_or_404(Role, pk=request.POST.get("role"))
            locked = role.slug == "owner"
            if locked:
                messages.error(request, "The Owner role always has full access and cannot be edited.")
                return redirect(f"{request.path}?role={role.pk}")
            form = RoleForm(request.POST, instance=role)
            if form.is_valid():
                role = form.save()
                log_action(
                    action="Role permissions updated",
                    user=request.user,
                    target=role,
                    detail={"permissions": role.permissions},
                    request=request,
                )
                messages.success(request, "Role permissions updated.")
                return redirect(f"{request.path}?role={role.pk}")
            messages.error(request, "Please correct the errors below.")
    if role:
        selected_permissions = role.permissions or []
    elif request.method == "POST":
        selected_permissions = request.POST.getlist("permissions")
    else:
        selected_permissions = []
    return render(
        request,
        "core/roles.html",
        {
            "roles": roles_list,
            "role": role,
            "editing": role or creating,
            "creating": creating,
            "form": form,
            "locked": locked,
            "selected_permissions": selected_permissions,
        },
    )


@perm_required(BACKUP_MANAGE)
def backups(request):
    shop = ShopSettings.load()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "create":
                record = create_backup(user=request.user, kind="manual", note=request.POST.get("note", ""))
                log_action(action="Backup created", user=request.user, target=record, request=request)
                messages.success(request, f"Backup created: {record.filename}")
            elif action == "restore":
                record = get_object_or_404(BackupRecord, pk=request.POST.get("id"))
                if request.POST.get("confirm", "").strip().upper() != "RESTORE":
                    raise BackupError("Type RESTORE to confirm restoring a backup.")
                safety = restore_backup(record, user=request.user)
                messages.success(
                    request,
                    f"Backup restored. A safety backup was saved as {safety.filename}.",
                )
            elif action == "delete":
                record = get_object_or_404(BackupRecord, pk=request.POST.get("id"))
                filename = record.filename
                delete_backup(record)
                log_action(action="Backup deleted", user=request.user, detail={"filename": filename}, request=request)
                messages.success(request, "Backup deleted.")
            elif action == "toggle_auto":
                shop.auto_backup_enabled = not shop.auto_backup_enabled
                shop.save(update_fields=["auto_backup_enabled", "updated_at"])
                messages.success(
                    request,
                    "Automatic backups enabled." if shop.auto_backup_enabled else "Automatic backups disabled.",
                )
        except BackupError as exc:
            messages.error(request, str(exc))
        return redirect("core:backups")
    records = BackupRecord.objects.select_related("created_by")
    return render(
        request,
        "core/backups.html",
        {"records": records, "shop": shop, "backup_root": str(django_settings.BACKUP_ROOT)},
    )


def pwa_manifest(request):
    shop = ShopSettings.load()
    payload = {
        "name": f"{shop.name} — Inventory & Sales",
        "short_name": shop.name[:12] or "Inventory",
        "description": "Boutique inventory, point of sale and business reports.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#ffffff",
        "theme_color": "#4f46e5",
        "icons": [
            {
                "src": django_settings.STATIC_URL + "img/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": django_settings.STATIC_URL + "img/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": django_settings.STATIC_URL + "img/icon-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "shortcuts": [
            {"name": "Point of sale", "url": "/pos/"},
            {"name": "Sales", "url": "/sales/"},
            {"name": "Stock", "url": "/inventory/stock/"},
        ],
    }
    return JsonResponse(payload, json_dumps_params={"indent": 2}, content_type="application/manifest+json")


def pwa_service_worker(request):
    path = Path(django_settings.BASE_DIR) / "static" / "js" / "service-worker.js"
    response = HttpResponse(path.read_text(encoding="utf-8"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response

def offline(request):
    return render(request, "core/offline.html")


@perm_required(BACKUP_MANAGE)
def backup_download(request, pk):
    record = get_object_or_404(BackupRecord, pk=pk)
    root = Path(django_settings.BACKUP_ROOT).resolve()
    path = (root / record.filename).resolve()
    if root not in path.parents or not path.exists():
        raise Http404("Backup file not found.")
    log_action(action="Backup downloaded", user=request.user, target=record, request=request)
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=record.filename,
        content_type="application/json",
    )


@perm_required(AUDIT_VIEW)
def audit_log(request):
    entries = AuditLog.objects.select_related("user")
    query = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    day = request.GET.get("date", "").strip()
    if query:
        entries = entries.filter(
            Q(action__icontains=query)
            | Q(detail__icontains=query)
            | Q(user__username__icontains=query)
        )
    if action:
        entries = entries.filter(action__icontains=action)
    if day:
        try:
            entries = entries.filter(created_at__date=datetime.strptime(day, "%Y-%m-%d").date())
        except ValueError:
            pass
    page = paginate(request, entries, "audit")
    actions = AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")
    template = "core/_audit_list.html" if wants_fragment(request) == "list" else "core/audit.html"
    return render(
        request,
        template,
        {"page": page, "entries": page, "actions": actions, "q": query, "action": action, "day": day},
    )
