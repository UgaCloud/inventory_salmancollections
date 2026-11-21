"""Sales engine: one checkout path for products, bulk measures and mixtures."""
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import PaymentMethod, ShopSettings
from core.utils import divide, money, qty
from inventory.models import Product, StockMovement
from inventory.services import (
    InsufficientStock,
    _lock_balance,
    _lock_product,
    consume_stock,
    restore_stock,
)

from .models import (
    Customer,
    CustomerPayment,
    Mixture,
    MixtureComponent,
    Refund,
    Sale,
    SaleItem,
    SalePayment,
    StockConsumption,
)


def _next_sale_number():
    ShopSettings.objects.select_for_update().get(pk=1)
    last = Sale.objects.order_by("-id").first()
    return f"INV-{(last.pk + 1) if last else 1:06d}"


def _resolve_active_method(payment):
    method = payment.get("method")
    if not method:
        method = PaymentMethod.objects.filter(is_active=True).order_by(
            "-is_default", "sort_order"
        ).first()
    if method is None or not method.is_active:
        raise ValueError("Choose an active payment method.")
    return method


@transaction.atomic
def checkout(*, items, payments, cashier, customer=None, discount=0, note=""):
    """Complete a sale atomically. Stock is deducted for every line.

    Returns ``(sale, change)``. Any failure (including insufficient stock or an
    invalid payment) rolls the whole sale back, leaving no partial deductions.
    """
    if not items:
        raise ValueError("Add at least one product to the sale.")
    shop = ShopSettings.load()
    discount = money(discount)
    if discount < 0:
        raise ValueError("Discount cannot be negative.")

    sale = Sale.objects.create(
        number=_next_sale_number(),
        customer=customer,
        cashier=cashier if getattr(cashier, "is_authenticated", False) else None,
        note=note,
    )
    subtotal = Decimal("0")
    total_cogs = Decimal("0")

    for item in items:
        if item.get("mixture_id"):
            mixture = (
                Mixture.objects.select_for_update()
                .prefetch_related("components__product")
                .get(pk=item["mixture_id"])
            )
            if mixture.status != Mixture.STATUS_PREPARED:
                raise ValueError(f"Mixture {mixture.name} is not available for sale.")
            components = list(mixture.components.all())
            if not components:
                raise ValueError(f"Mixture {mixture.name} has no components.")
            for component in components:
                if component.product.stock_quantity < component.quantity_ml:
                    raise InsufficientStock(
                        component.product,
                        component.quantity_ml,
                        component.product.stock_quantity,
                    )
            sale_item = SaleItem.objects.create(
                sale=sale,
                mixture=mixture,
                description=f"{mixture.name} (mixture, {mixture.total_ml}ml)",
                quantity=1,
                unit_price=mixture.price,
                line_total=money(mixture.price),
                unit_cost=mixture.total_cost,
                cogs=mixture.total_cost,
                is_measurement=True,
            )
            for component in components:
                consumptions = consume_stock(
                    component.product,
                    component.quantity_ml,
                    kind=StockMovement.KIND_MIXTURE_SALE,
                    reference_type="Sale",
                    reference_id=sale.pk,
                    note=f"Sold as mixture {mixture.name}",
                    user=cashier,
                )
                for entry in consumptions:
                    StockConsumption.objects.create(
                        sale_item=sale_item,
                        product=component.product,
                        batch=entry["batch"],
                        quantity=entry["quantity"],
                        unit_cost=entry["unit_cost"],
                        amount=money(entry["quantity"] * entry["unit_cost"]),
                    )
            subtotal += sale_item.line_total
            total_cogs += sale_item.cogs
            mixture.status = Mixture.STATUS_SOLD
            mixture.sold_at = timezone.now()
            mixture.save(update_fields=["status", "sold_at"])
        else:
            product = Product.objects.select_for_update().get(
                pk=item["product_id"], is_active=True
            )
            quantity = qty(item["quantity"])
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            line_total = product.price_for_quantity(quantity)
            consumptions = consume_stock(
                product,
                quantity,
                kind=StockMovement.KIND_SALE,
                reference_type="Sale",
                reference_id=sale.pk,
                user=cashier,
            )
            cost = sum(
                (entry["quantity"] * entry["unit_cost"] for entry in consumptions),
                Decimal("0"),
            )
            sale_item = SaleItem.objects.create(
                sale=sale,
                product=product,
                description=product.name,
                quantity=quantity,
                unit_price=divide(line_total, quantity, places=4),
                line_total=line_total,
                unit_cost=divide(cost, quantity, places=4),
                cogs=money(cost),
                is_measurement=product.unit == Product.UNIT_ML,
            )
            for entry in consumptions:
                StockConsumption.objects.create(
                    sale_item=sale_item,
                    product=product,
                    batch=entry["batch"],
                    quantity=entry["quantity"],
                    unit_cost=entry["unit_cost"],
                    amount=money(entry["quantity"] * entry["unit_cost"]),
                )
            subtotal += line_total
            total_cogs += sale_item.cogs

    if discount > subtotal:
        raise ValueError("Discount cannot be more than the subtotal.")
    total = money(subtotal - discount)

    paid = Decimal("0")
    resolved_payments = []
    for payment in payments:
        amount = money(payment.get("amount") or 0)
        if amount <= 0:
            continue
        method = _resolve_active_method(payment)
        paid += amount
        resolved_payments.append((method, amount))

    if customer is None:
        if paid < total:
            raise ValueError(
                "The payment is less than the total. Choose a customer to allow a balance."
            )
    else:
        if paid > total:
            raise ValueError("Payment cannot be more than the total for a customer sale.")
        if paid < total and not shop.allow_partial_payments:
            raise ValueError("Partial payments are disabled in settings.")

    if paid <= 0:
        raise ValueError("Enter an amount received.")

    balance = money(total - paid) if customer else Decimal("0")
    change = money(paid - total) if (customer is None and paid > total) else Decimal("0")

    for method, amount in resolved_payments:
        SalePayment.objects.create(
            sale=sale, method=method, method_name=method.name, amount=amount
        )

    sale.subtotal = money(subtotal)
    sale.discount = discount
    sale.total = total
    # Net received: change handed back to a walk-in is not money the shop kept.
    sale.paid = money(paid - change)
    sale.balance = balance
    sale.change_given = change
    sale.cogs = money(total_cogs)
    sale.save()
    return sale, change


@transaction.atomic
def cancel_sale(*, sale, user, reason=""):
    """Cancel a completed sale, reversing stock and recording a refund."""
    ShopSettings.objects.select_for_update().get(pk=1)
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.STATUS_COMPLETED:
        raise ValueError("This sale has already been cancelled.")
    items = list(sale.items.select_related("product", "mixture"))
    for item in items:
        consumptions = list(item.consumptions.select_related("batch", "product"))
        by_product = {}
        for entry in consumptions:
            by_product.setdefault(entry.product, []).append(
                {
                    "batch": entry.batch,
                    "quantity": entry.quantity,
                    "unit_cost": entry.unit_cost,
                }
            )
        for product, entries in by_product.items():
            if item.mixture_id:
                kind = StockMovement.KIND_MIXTURE_CANCEL
            else:
                kind = StockMovement.KIND_SALE_CANCEL
            restore_stock(
                product,
                entries,
                kind=kind,
                reference_type="Sale",
                reference_id=sale.pk,
                note=reason or "Sale cancelled",
                user=user,
            )
        if item.mixture_id and item.mixture:
            mixture = Mixture.objects.select_for_update().get(pk=item.mixture_id)
            if mixture.status == Mixture.STATUS_SOLD:
                mixture.status = Mixture.STATUS_PREPARED
                mixture.sold_at = None
                mixture.save(update_fields=["status", "sold_at"])

    if sale.paid > 0:
        Refund.objects.create(
            sale=sale,
            amount=sale.paid,
            method_name="Refund",
            reason=reason or "Sale cancelled",
            user=user,
        )
    sale.status = Sale.STATUS_CANCELLED
    sale.refunded_amount = sale.paid
    sale.balance = Decimal("0")
    sale.cancelled_at = timezone.now()
    sale.cancelled_by = user if getattr(user, "is_authenticated", False) else None
    sale.cancel_reason = reason
    sale.save()
    return sale


@transaction.atomic
def prepare_mixture(*, name, components, price, user, notes=""):
    """Prepare a mixture and snapshot component costs without touching stock."""
    components = [c for c in components if c.get("product") and qty(c.get("quantity_ml")) > 0]
    if len(components) < 2:
        raise ValueError("A mixture needs at least two perfumes.")
    price = money(price)
    if price <= 0:
        raise ValueError("Enter a selling price for the mixture.")
    total_ml = Decimal("0")
    total_cost = Decimal("0")
    mixture = Mixture.objects.create(
        name=name,
        notes=notes,
        price=price,
        prepared_by=user if getattr(user, "is_authenticated", False) else None,
    )
    seen = set()
    for component in components:
        product = _lock_product(component["product"])
        if product.kind != Product.KIND_BULK:
            raise ValueError(f"{product.name} is not a bulk perfume.")
        if product.pk in seen:
            raise ValueError(f"{product.name} is listed more than once.")
        seen.add(product.pk)
        quantity_ml = qty(component["quantity_ml"])
        cost_per_ml = product.average_cost
        cost = money(quantity_ml * cost_per_ml)
        MixtureComponent.objects.create(
            mixture=mixture,
            product=product,
            quantity_ml=quantity_ml,
            cost_per_ml=cost_per_ml,
            cost=cost,
        )
        total_ml += quantity_ml
        total_cost += cost
    mixture.total_ml = total_ml
    mixture.total_cost = money(total_cost)
    mixture.save(update_fields=["total_ml", "total_cost"])
    return mixture


@transaction.atomic
def record_customer_payment(*, customer, amount, method, user, date=None, note=""):
    """Record a payment against outstanding sales, oldest first."""
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Enter an amount greater than zero.")
    reference = uuid.uuid4().hex[:12]
    open_sales = list(
        Sale.objects.select_for_update()
        .filter(customer=customer, status=Sale.STATUS_COMPLETED, balance__gt=0)
        .order_by("created_at", "id")
    )
    outstanding = sum((s.balance for s in open_sales), Decimal("0"))
    if outstanding <= 0:
        raise ValueError("This customer has no outstanding balance.")
    if amount > outstanding:
        raise ValueError(
            f"Payment is more than the outstanding balance of {money(outstanding)}."
        )
    remaining = amount
    payments = []
    for sale in open_sales:
        if remaining <= 0:
            break
        applied = min(sale.balance, remaining)
        sale.paid = money(sale.paid + applied)
        sale.balance = money(sale.balance - applied)
        sale.save(update_fields=["paid", "balance"])
        payments.append(
            CustomerPayment.objects.create(
                customer=customer,
                sale=sale,
                amount=applied,
                method=method,
                method_name=method.name if method else "",
                date=date or timezone.localdate(),
                note=note,
                reference=reference,
                user=user if getattr(user, "is_authenticated", False) else None,
            )
        )
        remaining -= applied
    return payments
