import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.decorators import perm_required, perm_required_any
from core.http import form_errors, is_ajax, json_error, json_ok
from core.models import PaymentMethod, ShopSettings
from core.permissions import (
    CUSTOMERS_MANAGE,
    MIXTURES_MANAGE,
    POS_USE,
    REPORTS_VIEW,
    SALES_CANCEL,
)
from inventory.models import Category, Product
from inventory.services import InsufficientStock

from .forms import CustomerForm, CustomerPaymentForm, MixtureForm, MixtureSaleForm
from .models import Customer, CustomerPayment, Mixture, Sale, SaleItem, SalePayment
from .services import cancel_sale, checkout, prepare_mixture, record_customer_payment


def _paginate(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def _catalogue_queryset():
    return (
        Product.objects.filter(is_active=True)
        .select_related("balance", "category")
        .order_by("name")
    )


def _catalogue_products(request):
    products = _catalogue_queryset()
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(sku__icontains=query)
            | Q(barcode__iexact=query)
            | Q(brand__icontains=query)
        )
    if category:
        products = products.filter(category_id=category)
    return products[:200]


@perm_required(POS_USE)
def pos(request):
    shop = ShopSettings.load()
    context = {
        "products": _catalogue_products(request),
        "categories": Category.objects.filter(products__is_active=True).distinct().order_by("name"),
        "customers": Customer.objects.filter(is_active=True).order_by("name"),
        "methods": PaymentMethod.objects.filter(is_active=True),
        "mixtures": Mixture.objects.filter(status=Mixture.STATUS_PREPARED)
        .prefetch_related("components__product")
        .order_by("name"),
        "shop": shop,
        "pos_config": {
            "catalogueUrl": "/pos/catalogue/",
            "checkoutUrl": "/pos/checkout/",
            "currency": shop.currency_symbol,
            "allowPartial": shop.allow_partial_payments,
        },
    }
    return render(request, "sales/pos.html", context)


@perm_required(POS_USE)
def pos_catalogue(request):
    return render(
        request,
        "sales/_catalogue.html",
        {"products": _catalogue_products(request)},
    )


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        raise ValueError("The request could not be read.")


@perm_required(POS_USE)
@require_POST
def pos_checkout(request):
    try:
        payload = _json_body(request)
        raw_items = payload.get("items") or []
        if not raw_items:
            raise ValueError("The cart is empty.")
        items = []
        for raw in raw_items:
            if raw.get("mixture_id"):
                mixture = Mixture.objects.get(pk=raw["mixture_id"], status=Mixture.STATUS_PREPARED)
                items.append({"mixture_id": mixture.pk})
            else:
                product = Product.objects.get(pk=raw.get("product_id"), is_active=True)
                try:
                    quantity = Decimal(str(raw.get("quantity")))
                except (InvalidOperation, TypeError):
                    raise ValueError(f"Enter a valid quantity for {product.name}.")
                if quantity <= 0:
                    raise ValueError(f"Enter a quantity greater than zero for {product.name}.")
                items.append({"product_id": product.pk, "quantity": quantity})
        customer = None
        if payload.get("customer_id"):
            customer = Customer.objects.get(pk=payload["customer_id"], is_active=True)
        payments = []
        for raw in payload.get("payments") or []:
            amount = Decimal(str(raw.get("amount") or "0"))
            if amount <= 0:
                continue
            method = PaymentMethod.objects.get(pk=raw.get("method_id"), is_active=True)
            payments.append({"method": method, "amount": amount})
        try:
            discount = Decimal(str(payload.get("discount") or "0"))
        except InvalidOperation:
            raise ValueError("Enter a valid discount.")
        sale, change = checkout(
            items=items,
            payments=payments,
            cashier=request.user,
            customer=customer,
            discount=discount,
            note=(payload.get("note") or "").strip()[:200],
        )
    except (ValueError, InsufficientStock, Product.DoesNotExist, Mixture.DoesNotExist, PaymentMethod.DoesNotExist, Customer.DoesNotExist) as exc:
        return json_error(str(exc))
    except Exception:
        return json_error("The sale could not be completed. Please review the cart and try again.")
    log_action(
        action="Sale completed",
        user=request.user,
        target=sale,
        detail={"total": str(sale.total), "items": len(items)},
        request=request,
    )
    return json_ok(
        f"Sale {sale.number} completed.",
        sale_id=sale.pk,
        number=sale.number,
        total=str(sale.total),
        change=str(change),
        receipt_url=f"/sales/{sale.pk}/receipt/",
    )


@perm_required_any(POS_USE, REPORTS_VIEW)
def sale_receipt(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related("customer", "cashier"), pk=pk
    )
    items = sale.items.select_related("product")
    payments = sale.payments.all()
    return render(
        request,
        "sales/receipt.html",
        {
            "sale": sale,
            "items": items,
            "payments": payments,
            "shop": ShopSettings.load(),
            "print_mode": True,
        },
    )


@perm_required_any(POS_USE, REPORTS_VIEW)
def sales(request):
    queryset = Sale.objects.select_related("customer", "cashier")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
    if query:
        queryset = queryset.filter(
            Q(number__icontains=query)
            | Q(customer__name__icontains=query)
            | Q(customer__phone__icontains=query)
        )
    if status in {Sale.STATUS_COMPLETED, Sale.STATUS_CANCELLED}:
        queryset = queryset.filter(status=status)
    for raw, lookup in ((start, "created_at__date__gte"), (end, "created_at__date__lte")):
        if raw:
            try:
                queryset = queryset.filter(**{lookup: datetime.strptime(raw, "%Y-%m-%d").date()})
            except ValueError:
                pass
    page = _paginate(request, queryset)
    totals = queryset.filter(status=Sale.STATUS_COMPLETED).aggregate(
        total=Sum("total"), paid=Sum("paid"), balance=Sum("balance")
    )
    return render(
        request,
        "sales/sales.html",
        {
            "page": page,
            "sales": page,
            "filters": {"q": query, "status": status, "start": start, "end": end},
            "totals": totals,
        },
    )


@perm_required_any(POS_USE, REPORTS_VIEW)
def sale_detail(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("customer", "cashier", "cancelled_by"), pk=pk)
    return render(
        request,
        "sales/detail.html",
        {
            "sale": sale,
            "items": sale.items.select_related("product", "mixture"),
            "payments": sale.payments.all(),
            "refunds": sale.refunds.all(),
            "shop": ShopSettings.load(),
        },
    )


@perm_required(SALES_CANCEL)
@require_POST
def cancel_sale_view(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    reason = (request.POST.get("reason") or "").strip()[:200]
    if not reason:
        messages.error(request, "Enter a reason for cancelling this sale.")
        return redirect("sales:detail", pk=sale.pk)
    try:
        sale = cancel_sale(sale=sale, user=request.user, reason=reason)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        log_action(
            action="Sale cancelled",
            user=request.user,
            target=sale,
            detail={"number": sale.number, "refund": str(sale.refunded_amount), "reason": reason},
            request=request,
        )
        messages.success(request, f"Sale {sale.number} cancelled and stock restored.")
    return redirect("sales:detail", pk=pk)


@perm_required(MIXTURES_MANAGE)
def mixtures(request):
    form = MixtureForm()
    component_errors = []
    if request.method == "POST":
        form = MixtureForm(request.POST)
        raw_products = request.POST.getlist("component_product")
        raw_quantities = request.POST.getlist("component_ml")
        components = []
        for index, product_id in enumerate(raw_products):
            if not (product_id or "").strip():
                continue
            raw_quantity = (raw_quantities[index] if index < len(raw_quantities) else "").strip()
            try:
                from core.utils import to_decimal

                quantity = to_decimal(raw_quantity, field="millilitres")
                if quantity <= 0:
                    raise ValueError
            except ValueError:
                component_errors.append(f"Component {len(components) + 1}: enter a quantity in millilitres.")
                continue
            components.append({"product_id": product_id, "quantity_ml": quantity})
        if len(components) < 2:
            component_errors.append("Choose at least two perfumes and their millilitres.")
        if form.is_valid() and not component_errors:
            try:
                resolved = []
                for component in components:
                    product = Product.objects.get(
                        pk=component["product_id"], kind=Product.KIND_BULK, is_active=True
                    )
                    resolved.append(
                        {"product": product, "quantity_ml": component["quantity_ml"]}
                    )
                mixture = prepare_mixture(
                    name=form.cleaned_data["name"],
                    components=resolved,
                    price=form.cleaned_data["price"],
                    user=request.user,
                    notes=form.cleaned_data.get("notes", ""),
                )
            except (ValueError, Product.DoesNotExist) as exc:
                form.add_error(None, str(exc))
            else:
                log_action(
                    action="Mixture prepared",
                    user=request.user,
                    target=mixture,
                    detail={"ml": str(mixture.total_ml), "price": str(mixture.price)},
                    request=request,
                )
                messages.success(
                    request,
                    f"Mixture {mixture.name} prepared. Add it to the POS cart or sell it right here.",
                )
                return redirect(f"{reverse('sales:mixtures')}?sell={mixture.pk}")
        else:
            messages.error(request, "Please correct the mixture details.")
    perfumes = (
        Product.objects.filter(kind=Product.KIND_BULK, is_active=True)
        .select_related("balance")
        .order_by("name")
    )
    return render(
        request,
        "sales/mixtures.html",
        {
            "form": form,
            "perfumes": perfumes,
            "component_errors": component_errors,
            "prepared": Mixture.objects.filter(status=Mixture.STATUS_PREPARED)
            .prefetch_related("components__product")
            .order_by("name"),
            "history": Mixture.objects.exclude(status=Mixture.STATUS_PREPARED)
            .prefetch_related("components__product")
            .order_by("-created_at")[:20],
            "sale_form": MixtureSaleForm(),
        },
    )


@perm_required_any(POS_USE, MIXTURES_MANAGE)
@require_POST
def mixture_sell(request, pk):
    """Sell a prepared mixture straight away, without going through the POS cart."""
    mixture = get_object_or_404(Mixture, pk=pk)
    if mixture.status != Mixture.STATUS_PREPARED:
        messages.error(request, "That mixture has already been sold.")
        return redirect("sales:mixtures")
    form = MixtureSaleForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            sale, change = checkout(
                items=[{"mixture_id": mixture.pk}],
                payments=[{"method": data["method"], "amount": data["amount"]}],
                cashier=request.user,
                customer=data.get("customer"),
                note=(data.get("note") or f"Mixture {mixture.name}")[:200],
            )
        except (ValueError, InsufficientStock) as exc:
            messages.error(request, str(exc))
        else:
            log_action(
                action="Mixture sold",
                user=request.user,
                target=sale,
                detail={"mixture": mixture.name, "total": str(sale.total)},
                request=request,
            )
            symbol = ShopSettings.load().currency_symbol
            message = f"Mixture {mixture.name} sold on {sale.number}."
            if change:
                message += f" Change due: {symbol}{change:,.2f}."
            messages.success(request, message)
            return redirect("sales:detail", pk=sale.pk)
    else:
        messages.error(request, "Please correct the sale details.")
    return redirect(f"{reverse('sales:mixtures')}?sell={mixture.pk}")


def _customer_queryset():
    return Customer.objects.annotate(
        outstanding=Coalesce(
            Sum("sales__balance", filter=Q(sales__status=Sale.STATUS_COMPLETED)),
            Value(0),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    ).order_by("name")


@perm_required(CUSTOMERS_MANAGE)
def customers(request):
    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(Customer, pk=request.GET["edit"])
    form = CustomerForm(instance=editing)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            customer = get_object_or_404(Customer, pk=request.POST.get("id"))
            if customer.sales.exists():
                message = "This customer has sales and cannot be deleted. Deactivate them instead."
                if is_ajax(request):
                    return json_error(message)
                messages.error(request, message)
                return redirect(request.path)
            name = customer.name
            customer.delete()
            log_action(action="Customer deleted", user=request.user, detail={"name": name}, request=request)
            if is_ajax(request):
                return json_ok("Customer deleted.", refresh_list=True)
            messages.success(request, "Customer deleted.")
            return redirect(request.path)
        instance = None
        if request.POST.get("id"):
            instance = get_object_or_404(Customer, pk=request.POST["id"])
        form = CustomerForm(request.POST, instance=instance)
        if form.is_valid():
            customer = form.save()
            log_action(action="Customer saved", user=request.user, target=customer, request=request)
            if is_ajax(request):
                return json_ok(
                    "Customer saved.",
                    refresh_list=True,
                    redirect="" if instance is None else request.path,
                )
            messages.success(request, "Customer saved.")
            return redirect(request.path)
        if is_ajax(request):
            return json_error(errors=form_errors(form))
    query = request.GET.get("q", "").strip()
    balance_filter = request.GET.get("filter", "").strip()
    customers_list = _customer_queryset()
    if query:
        customers_list = customers_list.filter(
            Q(name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query)
        )
    if balance_filter == "outstanding":
        customers_list = customers_list.filter(outstanding__gt=0)
    page = _paginate(request, customers_list)
    context = {
        "form": form,
        "editing": editing,
        "page": page,
        "customers": page,
        "filters": {"q": query, "filter": balance_filter},
        "list_url": request.path,
    }
    fragment = request.GET.get("fragment")
    if fragment == "list":
        return render(request, "sales/_customer_list.html", context)
    if fragment == "form":
        return render(request, "sales/_customer_form.html", context)
    return render(request, "sales/customers.html", context)


@perm_required(CUSTOMERS_MANAGE)
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sales_list = customer.sales.select_related("cashier").order_by("-created_at")
    payments = customer.payments.select_related("sale", "method").order_by("-created_at")
    form = CustomerPaymentForm(
        initial={"date": timezone.localdate(), "amount": customer.outstanding_balance}
    )
    return render(
        request,
        "sales/customer_detail.html",
        {
            "customer": customer,
            "sales": sales_list[:50],
            "payments": payments[:50],
            "form": form,
            "outstanding": customer.outstanding_balance,
        },
    )


@perm_required(CUSTOMERS_MANAGE)
@require_POST
def record_payment(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerPaymentForm(request.POST)
    if form.is_valid():
        try:
            payments = record_customer_payment(
                customer=customer,
                amount=form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                user=request.user,
                date=form.cleaned_data["date"],
                note=form.cleaned_data.get("note", ""),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            log_action(
                action="Customer payment recorded",
                user=request.user,
                target=customer,
                detail={
                    "amount": str(form.cleaned_data["amount"]),
                    "allocations": len(payments),
                },
                request=request,
            )
            messages.success(
                request,
                f"Payment recorded for {customer.name}. Outstanding balance is now "
                f"{ShopSettings.load().currency_symbol}{customer.outstanding_balance:,.2f}.",
            )
    else:
        messages.error(request, "Please correct the payment details.")
    return redirect("customers:detail", pk=customer.pk)


@perm_required(CUSTOMERS_MANAGE)
def payments(request):
    queryset = CustomerPayment.objects.select_related("customer", "sale", "method", "user")
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(customer__name__icontains=query) | Q(reference__icontains=query)
        )
    page = _paginate(request, queryset, per_page=30)
    total = sum((payment.amount for payment in page), Decimal("0"))
    return render(
        request,
        "sales/payments.html",
        {"page": page, "payments": page, "q": query, "page_total": total},
    )
