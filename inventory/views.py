from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.audit import log_action
from core.decorators import perm_required, perm_required_any
from core.http import form_errors, is_ajax, json_error, json_ok, wants_fragment
from core.models import ShopSettings
from core.pagination import page_size_for
from core.permissions import PRODUCTS_MANAGE, PURCHASES_MANAGE, STOCK_ADJUST
from core.utils import money, to_decimal

from .forms import (
    CategoryForm,
    ImportForm,
    PackForm,
    ProductForm,
    PurchaseForm,
    StockAdjustForm,
    SupplierForm,
    UnitForm,
)
from .importing import import_products, template_csv
from .models import (
    Category,
    PackRun,
    Product,
    Purchase,
    StockAdjustment,
    StockBatch,
    Supplier,
    Unit,
)
from .services import InsufficientStock, add_opening_stock, adjust_stock, pack_from_bulk, receive_purchase


def _paginate(request, queryset, section="default"):
    return Paginator(queryset, page_size_for(section)).get_page(request.GET.get("page"))


def _product_queryset():
    return Product.objects.select_related("category", "balance", "bulk_parent").order_by("name")


def _product_workspace(request, *, template, fixed_kind=None):
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(Product, pk=request.GET["edit"])
    initial = {}
    if fixed_kind:
        initial = {"kind": fixed_kind, "unit": Product.UNIT_ML}
    form = ProductForm(instance=editing, initial=initial if not editing else None)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            product = get_object_or_404(Product, pk=request.POST.get("id"))
            if (
                product.sale_items.exists()
                or product.purchase_lines.exists()
                or product.movements.exists()
            ):
                message = "This product has sales or stock history. Deactivate it instead of deleting."
                if is_ajax(request):
                    return json_error(message)
                messages.error(request, message)
                return redirect(request.path)
            name = product.name
            product.delete()
            log_action(action="Product deleted", user=request.user, detail={"name": name}, request=request)
            if is_ajax(request):
                return json_ok("Product deleted.", refresh_list=True)
            messages.success(request, "Product deleted.")
            return redirect(request.path)

        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(Product, pk=request.POST["id"])
        form = ProductForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            product = form.save()
            opening = form.cleaned_data.get("opening_stock") or Decimal("0")
            if instance is None and opening > 0:
                add_opening_stock(
                    product,
                    opening,
                    form.cleaned_data.get("opening_cost") or Decimal("0"),
                    user=request.user,
                )
            log_action(
                action="Product saved",
                user=request.user,
                target=product,
                detail={"name": product.name, "sku": product.sku, "kind": product.kind},
                request=request,
            )
            if is_ajax(request):
                return json_ok(
                    "Product saved.",
                    refresh_list=True,
                    redirect="" if instance is None else request.path,
                )
            messages.success(request, f"{product.name} saved.")
            return redirect(request.path)
        if is_ajax(request):
            return json_error(errors=form_errors(form))

    products = _product_queryset()
    if fixed_kind:
        products = products.filter(kind=fixed_kind)
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    kind = request.GET.get("kind", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query) | Q(barcode__icontains=query)
        )
    if category:
        products = products.filter(category_id=category)
    if kind and not fixed_kind:
        products = products.filter(kind=kind)
    if status == "low":
        products = products.filter(reorder_level__gt=0, balance__quantity__lte=F("reorder_level"))
    elif status == "out":
        products = products.filter(Q(balance__quantity__lte=0) | Q(balance__isnull=True))
    elif status == "inactive":
        products = products.filter(is_active=False)
    page = _paginate(
        request, products, "perfumes" if fixed_kind == Product.KIND_BULK else "products"
    )

    context = {
        "form": form,
        "editing": editing,
        "page": page,
        "products": page,
        "categories": Category.objects.all(),
        "kind_choices": Product.KIND_CHOICES,
        "list_url": request.path,
        "filters": {"q": query, "category": category, "kind": kind, "status": status},
        "fixed_kind": fixed_kind,
        "perfume_mode": fixed_kind == Product.KIND_BULK,
    }
    fragment = wants_fragment(request)
    if fragment == "list":
        return render(request, "inventory/_product_list.html", context)
    if fragment == "form":
        return render(request, "inventory/_product_form.html", context)
    return render(request, template, context)


@perm_required(PRODUCTS_MANAGE)
def products(request):
    return _product_workspace(request, template="inventory/products.html")


@perm_required(PRODUCTS_MANAGE)
def perfumes(request):
    return _product_workspace(
        request, template="inventory/perfumes.html", fixed_kind=Product.KIND_BULK
    )


@perm_required(PRODUCTS_MANAGE)
def categories(request):
    """Create, edit and retire product categories from the interface."""
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(Category, pk=request.GET["edit"])
    form = CategoryForm(instance=editing)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            category = get_object_or_404(Category, pk=request.POST.get("id"))
            if category.products.exists():
                message = (
                    "This category is used by products and cannot be deleted. "
                    "Deactivate it instead."
                )
                if is_ajax(request):
                    return json_error(message)
                messages.error(request, message)
                return redirect(request.path)
            name = category.name
            category.delete()
            log_action(action="Category deleted", user=request.user, detail={"name": name}, request=request)
            if is_ajax(request):
                return json_ok("Category deleted.", refresh_list=True)
            messages.success(request, "Category deleted.")
            return redirect(request.path)
        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(Category, pk=request.POST["id"])
        form = CategoryForm(request.POST, instance=instance)
        if form.is_valid():
            category = form.save()
            log_action(action="Category saved", user=request.user, target=category, request=request)
            if is_ajax(request):
                return json_ok("Category saved.", refresh_list=True)
            messages.success(request, "Category saved.")
            return redirect(request.path)
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    context = {
        "form": form,
        "editing": editing,
        "categories": Category.objects.all(),
        "list_url": request.path,
    }
    fragment = wants_fragment(request)
    if fragment == "list":
        return render(request, "inventory/_category_list.html", context)
    if fragment == "form":
        return render(request, "inventory/_category_form.html", context)
    return render(request, "inventory/categories.html", context)


@perm_required(PRODUCTS_MANAGE)
def units(request):
    """Create, edit and retire the units used by the product catalogue."""
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(Unit, pk=request.GET["edit"])
    form = UnitForm(instance=editing)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            unit = get_object_or_404(Unit, pk=request.POST.get("id"))
            if Product.objects.filter(unit=unit.code).exists():
                message = (
                    "This unit is used by products and cannot be deleted. "
                    "Deactivate it instead."
                )
                if is_ajax(request):
                    return json_error(message)
                messages.error(request, message)
                return redirect(request.path)
            name = unit.name
            unit.delete()
            log_action(action="Unit deleted", user=request.user, detail={"name": name}, request=request)
            if is_ajax(request):
                return json_ok("Unit deleted.", refresh_list=True)
            messages.success(request, "Unit deleted.")
            return redirect(request.path)
        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(Unit, pk=request.POST["id"])
        form = UnitForm(request.POST, instance=instance)
        if form.is_valid():
            unit = form.save()
            log_action(action="Unit saved", user=request.user, target=unit, request=request)
            if is_ajax(request):
                return json_ok("Unit saved.", refresh_list=True)
            messages.success(request, "Unit saved.")
            return redirect(request.path)
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    context = {
        "form": form,
        "editing": editing,
        "units": Unit.objects.all(),
        "list_url": request.path,
    }
    fragment = wants_fragment(request)
    if fragment == "list":
        return render(request, "inventory/_unit_list.html", context)
    if fragment == "form":
        return render(request, "inventory/_unit_form.html", context)
    return render(request, "inventory/units.html", context)


@perm_required(PRODUCTS_MANAGE)
def perfume_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("balance", "category").prefetch_related("batches"),
        pk=pk,
        kind=Product.KIND_BULK,
    )
    packed_products = list(
        product.packed_products.select_related("balance", "category").order_by("name")
    )
    recent_sales = (
        product.sale_items.select_related("sale")
        .filter(sale__status="completed")
        .order_by("-id")[:12]
    )
    movements = product.movements.select_related("user", "batch")[:20]
    batches = product.batches.filter(remaining__gt=0).order_by("received_at")
    sold_ml = sum(
        (item.quantity for item in product.sale_items.filter(sale__status="completed")),
        Decimal("0"),
    )
    revenue = sum(
        (item.line_total for item in product.sale_items.filter(sale__status="completed")),
        Decimal("0"),
    )
    cogs = sum(
        (item.cogs for item in product.sale_items.filter(sale__status="completed")),
        Decimal("0"),
    )
    packed_sales = []
    for packed in packed_products:
        packed_sales.append(
            {
                "product": packed,
                "sold": sum(
                    (
                        item.quantity
                        for item in packed.sale_items.filter(sale__status="completed")
                    ),
                    Decimal("0"),
                ),
            }
        )
    return render(
        request,
        "inventory/perfume_detail.html",
        {
            "product": product,
            "packed_products": packed_products,
            "packed_sales": packed_sales,
            "recent_sales": recent_sales,
            "movements": movements,
            "batches": batches,
            "sold_ml": sold_ml,
            "revenue": money(revenue),
            "cogs": money(cogs),
            "profit": money(revenue - cogs),
            "stock_value": money(product.stock_value),
        },
    )


@perm_required_any(PRODUCTS_MANAGE, STOCK_ADJUST)
def stock_overview(request):
    products = Product.objects.select_related("balance", "category").prefetch_related("batches")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    category = request.GET.get("category", "").strip()
    kind = request.GET.get("kind", "").strip()
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query) | Q(barcode__icontains=query)
        )
    if status == "low":
        products = products.filter(reorder_level__gt=0, balance__quantity__lte=F("reorder_level"))
    elif status == "out":
        products = products.filter(Q(balance__quantity__lte=0) | Q(balance__isnull=True))
    if category:
        products = products.filter(category_id=category)
    if kind:
        products = products.filter(kind=kind)
    products = products.order_by("name")
    page = _paginate(request, products, "stock")
    rows = list(page)
    context = {
        "page": page,
        "products": rows,
        "categories": Category.objects.all(),
        "kind_choices": Product.KIND_CHOICES,
        "filters": {"q": query, "status": status, "category": category, "kind": kind},
        "total_value": money(sum((p.stock_value for p in rows), Decimal("0"))),
        "low_count": sum(1 for p in rows if p.is_low_stock),
        "out_count": sum(1 for p in rows if p.is_out_of_stock),
        "shop": ShopSettings.load(),
    }
    if wants_fragment(request) == "list":
        return render(request, "inventory/_stock_list.html", context)
    return render(request, "inventory/stock.html", context)


@perm_required(STOCK_ADJUST)
def adjustments(request):
    form = StockAdjustForm()
    if request.method == "POST":
        form = StockAdjustForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            delta = data["quantity"] if data["direction"] == "increase" else -data["quantity"]
            try:
                adjustment = adjust_stock(
                    product=data["product"],
                    delta=delta,
                    reason=data["reason"],
                    user=request.user,
                    note=data["note"],
                )
            except (ValueError, InsufficientStock) as exc:
                form.add_error(None, str(exc))
            else:
                log_action(
                    action="Stock adjusted",
                    user=request.user,
                    target=adjustment,
                    detail={
                        "product": adjustment.product.name,
                        "delta": str(adjustment.quantity_delta),
                        "reason": adjustment.reason,
                    },
                    request=request,
                )
                if is_ajax(request):
                    return json_ok("Stock adjusted.", refresh=True)
                messages.success(request, "Stock adjusted.")
                return redirect("inventory:adjustments")
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    history = StockAdjustment.objects.select_related("product", "user")[:100]
    return render(
        request,
        "inventory/adjustments.html",
        {
            "form": form,
            "history": history,
            "list_url": request.path,
        },
    )


@perm_required_any(PRODUCTS_MANAGE, STOCK_ADJUST)
def pack(request):
    form = PackForm()
    if request.method == "POST":
        form = PackForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                run = pack_from_bulk(
                    bulk_product=data["bulk_product"],
                    packed_product=data["packed_product"],
                    ml_per_bottle=data["ml_per_bottle"],
                    bottles=data["bottles"],
                    user=request.user,
                    note=data["note"],
                    extra_cost_per_bottle=data["extra_cost_per_bottle"] or Decimal("0"),
                )
            except (ValueError, InsufficientStock) as exc:
                form.add_error(None, str(exc))
            else:
                log_action(
                    action="Packed from bulk",
                    user=request.user,
                    target=run,
                    detail={
                        "bulk": run.bulk_product.name,
                        "packed": run.packed_product.name,
                        "ml": str(run.total_ml),
                        "bottles": run.bottles,
                    },
                    request=request,
                )
                if is_ajax(request):
                    return json_ok("Packing run completed.", refresh=True)
                messages.success(request, "Packing run completed.")
                return redirect("inventory:pack")
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    runs = PackRun.objects.select_related("bulk_product", "packed_product", "user")[:50]
    return render(
        request,
        "inventory/pack.html",
        {"form": form, "runs": runs, "list_url": request.path},
    )


@perm_required_any(PRODUCTS_MANAGE, STOCK_ADJUST)
def pack_options(request):
    bulk_id = request.GET.get("bulk")
    options = (
        Product.objects.filter(kind=Product.KIND_PACKED, bulk_parent_id=bulk_id, is_active=True)
        .select_related("balance")
        .order_by("name")
    )
    return JsonResponse(
        {
            "options": [
                {
                    "id": product.pk,
                    "name": product.name,
                    "stock": str(product.stock_quantity),
                    "size": str(product.packed_size_ml or ""),
                }
                for product in options
            ]
        }
    )


@perm_required(PRODUCTS_MANAGE)
def import_view(request):
    form = ImportForm()
    if request.method == "POST":
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                count, errors = import_products(form.cleaned_data["file"], user=request.user)
            except ValueError as exc:
                count, errors = 0, [str(exc)]
            if errors:
                messages.error(request, "Nothing was imported. Fix the errors and try again.")
                return render(
                    request,
                    "inventory/import.html",
                    {"form": form, "errors": errors, "list_url": request.path},
                )
            log_action(
                action="Products imported",
                user=request.user,
                detail={"count": count},
                request=request,
            )
            messages.success(request, f"{count} product(s) imported.")
            return redirect("inventory:products")
        messages.error(request, "Choose a CSV file to import.")
    return render(
        request,
        "inventory/import.html",
        {"form": form, "errors": [], "list_url": request.path},
    )


@perm_required(PRODUCTS_MANAGE)
def import_template(request):
    response = HttpResponse(template_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="product-import-template.csv"'
    return response


# ---------------------------------------------------------------------------
# Purchasing
# ---------------------------------------------------------------------------


@perm_required(PURCHASES_MANAGE)
def suppliers(request):
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(Supplier, pk=request.GET["edit"])
    form = SupplierForm(instance=editing)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            supplier = get_object_or_404(Supplier, pk=request.POST.get("id"))
            if supplier.purchases.exists():
                message = "This supplier has purchases and cannot be deleted. Deactivate it instead."
                if is_ajax(request):
                    return json_error(message)
                messages.error(request, message)
                return redirect(request.path)
            name = supplier.name
            supplier.delete()
            log_action(action="Supplier deleted", user=request.user, detail={"name": name}, request=request)
            if is_ajax(request):
                return json_ok("Supplier deleted.", refresh_list=True)
            messages.success(request, "Supplier deleted.")
            return redirect(request.path)
        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(Supplier, pk=request.POST["id"])
        form = SupplierForm(request.POST, instance=instance)
        if form.is_valid():
            supplier = form.save()
            log_action(action="Supplier saved", user=request.user, target=supplier, request=request)
            if is_ajax(request):
                return json_ok(
                    "Supplier saved.",
                    refresh_list=True,
                    redirect="" if instance is None else request.path,
                )
            messages.success(request, "Supplier saved.")
            return redirect(request.path)
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    supplier_list = Supplier.objects.all()
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        supplier_list = supplier_list.filter(
            Q(name__icontains=query)
            | Q(contact_person__icontains=query)
            | Q(phone__icontains=query)
            | Q(email__icontains=query)
        )
    if status == "inactive":
        supplier_list = supplier_list.filter(is_active=False)
    context = {
        "form": form,
        "editing": editing,
        "suppliers": supplier_list,
        "filters": {"q": query, "status": status},
        "list_url": request.path,
    }
    fragment = wants_fragment(request)
    if fragment == "list":
        return render(request, "inventory/_supplier_list.html", context)
    if fragment == "form":
        return render(request, "inventory/_supplier_form.html", context)
    return render(request, "inventory/suppliers.html", context)


def _parse_purchase_lines(post):
    products = post.getlist("product_id")
    quantities = post.getlist("quantity")
    costs = post.getlist("unit_cost")
    expiries = post.getlist("expiry_date")
    items = []
    errors = []
    for index, product_id in enumerate(products):
        if not (product_id or "").strip():
            continue
        try:
            product = Product.objects.get(pk=product_id, is_active=True)
        except (Product.DoesNotExist, ValueError):
            errors.append(f"Line {index + 1}: choose a valid product.")
            continue
        raw_quantity = (quantities[index] if index < len(quantities) else "").strip()
        raw_cost = (costs[index] if index < len(costs) else "").strip()
        raw_expiry = (expiries[index] if index < len(expiries) else "").strip()
        try:
            quantity = to_decimal(raw_quantity, field=f"quantity for {product.name}")
            if quantity <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"Line {index + 1}: enter a positive quantity for {product.name}.")
            continue
        if raw_cost:
            try:
                unit_cost = to_decimal(raw_cost, field=f"cost for {product.name}")
                if unit_cost < 0:
                    raise ValueError
            except ValueError:
                errors.append(f"Line {index + 1}: enter a valid cost for {product.name}.")
                continue
        else:
            unit_cost = product.average_cost or Decimal("0")
        expiry = None
        if raw_expiry:
            try:
                expiry = datetime.strptime(raw_expiry, "%Y-%m-%d").date()
            except ValueError:
                errors.append(f"Line {index + 1}: enter a valid expiry date.")
                continue
        items.append(
            {
                "product": product,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "expiry_date": expiry,
            }
        )
    if not items and not errors:
        errors.append("Add at least one product line.")
    return items, errors


@perm_required(PURCHASES_MANAGE)
def receive(request):
    form = PurchaseForm(initial={"purchase_date": timezone.localdate()})
    line_errors = []
    if request.method == "POST":
        form = PurchaseForm(request.POST)
        items, line_errors = _parse_purchase_lines(request.POST)
        if form.is_valid() and not line_errors:
            try:
                purchase = receive_purchase(
                    supplier=form.cleaned_data["supplier"],
                    items=items,
                    user=request.user,
                    purchase_date=form.cleaned_data["purchase_date"],
                    note=form.cleaned_data.get("note", ""),
                    reference=form.cleaned_data.get("reference", ""),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                log_action(
                    action="Stock received",
                    user=request.user,
                    target=purchase,
                    detail={"total": str(purchase.total_cost), "lines": len(items)},
                    request=request,
                )
                if is_ajax(request):
                    if request.POST.get("drawer") == "1":
                        return json_ok(
                            f"Stock received on {purchase.number}.",
                            drawer_close=True,
                            refresh=True,
                        )
                    return json_ok(
                        f"Stock received on {purchase.number}.",
                        redirect=request.path,
                    )
                messages.success(request, f"Stock received on {purchase.number}.")
                return redirect("inventory:purchase_detail", pk=purchase.pk)
        elif line_errors and is_ajax(request):
            return json_error("Please correct the product lines.", errors={"_form": line_errors})
        if is_ajax(request):
            return json_error(errors=form_errors(form))
        if line_errors:
            messages.error(request, "Please correct the product lines.")
    recent = Purchase.objects.select_related("supplier")[:5]
    context = {
        "form": form,
        "line_errors": line_errors,
        "products": Product.objects.filter(is_active=True).select_related("balance").order_by("name"),
        "recent": recent,
        "list_url": request.path,
        "today": timezone.localdate(),
    }
    if request.GET.get("drawer") == "1":
        return render(request, "inventory/_receive_drawer.html", context)
    return render(request, "inventory/receive.html", context)


@perm_required(PURCHASES_MANAGE)
def purchases(request):
    queryset = Purchase.objects.select_related("supplier", "user")
    query = request.GET.get("q", "").strip()
    supplier_id = request.GET.get("supplier", "").strip()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
    if query:
        queryset = queryset.filter(
            Q(number__icontains=query)
            | Q(reference__icontains=query)
            | Q(supplier__name__icontains=query)
        )
    if supplier_id:
        queryset = queryset.filter(supplier_id=supplier_id)
    if start:
        try:
            queryset = queryset.filter(purchase_date__gte=datetime.strptime(start, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end:
        try:
            queryset = queryset.filter(purchase_date__lte=datetime.strptime(end, "%Y-%m-%d").date())
        except ValueError:
            pass
    page = _paginate(request, queryset, "purchases")
    total = sum((purchase.total_cost for purchase in page), Decimal("0"))
    template = (
        "inventory/_purchases_list.html"
        if wants_fragment(request) == "list"
        else "inventory/purchases.html"
    )
    return render(
        request,
        template,
        {
            "page": page,
            "purchases": page,
            "suppliers": Supplier.objects.all(),
            "filters": {"q": query, "supplier": supplier_id, "start": start, "end": end},
            "page_total": total,
        },
    )


@perm_required(PURCHASES_MANAGE)
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.select_related("supplier", "user"), pk=pk
    )
    lines = purchase.lines.select_related("product", "batch")
    return render(
        request,
        "inventory/purchase_detail.html",
        {"purchase": purchase, "lines": lines},
    )
