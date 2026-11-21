"""The single authoritative inventory engine.

Every stock increase or decrease goes through this module. Each operation is
atomic, locks the affected rows, converts quantities into the product's base
unit before checking availability, and leaves an auditable stock movement.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.models import ShopSettings
from core.utils import divide, money, qty, unit_cost

from .models import (
    PackRun,
    Product,
    Purchase,
    PurchaseLine,
    StockAdjustment,
    StockBalance,
    StockBatch,
    StockMovement,
)


class InsufficientStock(Exception):
    def __init__(self, product, requested, available):
        self.product = product
        self.requested = requested
        self.available = available
        super().__init__(
            f"Not enough stock for {product.name}: need {requested} "
            f"{product.get_unit_display().lower()}, only {available} available."
        )


def _lock_product(product):
    return Product.objects.select_for_update().get(pk=product.pk)


def _lock_balance(product):
    balance, created = StockBalance.objects.get_or_create(
        product_id=product.pk, defaults={"quantity": 0}
    )
    if created:
        balance.refresh_from_db()
    return StockBalance.objects.select_for_update().get(pk=balance.pk)


def _movement(
    product,
    kind,
    quantity,
    balance_after,
    *,
    unit_cost_value=Decimal("0"),
    batch=None,
    reference_type="",
    reference_id="",
    note="",
    user=None,
):
    return StockMovement.objects.create(
        product=product,
        batch=batch,
        kind=kind,
        quantity=quantity,
        unit_cost=unit_cost_value,
        balance_after=balance_after,
        reference_type=reference_type,
        reference_id=str(reference_id or ""),
        note=note,
        user=user if getattr(user, "is_authenticated", False) else None,
    )


def _update_average_cost(product, added_qty, added_cost, existing_qty):
    total_qty = existing_qty + added_qty
    if total_qty <= 0:
        return
    old_value = existing_qty * product.average_cost
    new_average = divide(old_value + added_cost, total_qty, places=4)
    product.average_cost = new_average
    product.save(update_fields=["average_cost", "updated_at"])


def next_purchase_number():
    ShopSettings.objects.select_for_update().get(pk=1)
    last = Purchase.objects.order_by("-id").first()
    return f"PUR-{(last.pk + 1) if last else 1:06d}"


def add_opening_stock(product, quantity, cost, *, user=None, note="Opening stock"):
    """Register opening stock as a real batch so costing stays consistent."""
    quantity = qty(quantity)
    if quantity <= 0:
        raise ValueError("Opening stock must be greater than zero.")
    with transaction.atomic():
        _lock_product(product)
        balance = _lock_balance(product)
        batch = StockBatch.objects.create(
            product=product,
            received_at=timezone.localdate(),
            quantity=quantity,
            remaining=quantity,
            unit_cost=unit_cost(cost),
            reference="opening",
            note=note,
        )
        balance.quantity = balance.quantity + quantity
        balance.save(update_fields=["quantity", "updated_at"])
        _update_average_cost(
            product, quantity, quantity * unit_cost(cost), balance.quantity - quantity
        )
        _movement(
            product,
            StockMovement.KIND_OPENING,
            quantity,
            balance.quantity,
            unit_cost_value=unit_cost(cost),
            batch=batch,
            note=note,
            user=user,
        )
        return batch


@transaction.atomic
def receive_purchase(*, supplier, items, user, purchase_date=None, note="", reference=""):
    """Receive stock: creates batches, movements, balances and a purchase record."""
    if not items:
        raise ValueError("Add at least one product line.")
    purchase = Purchase.objects.create(
        number=next_purchase_number(),
        supplier=supplier,
        purchase_date=purchase_date or timezone.localdate(),
        note=note,
        reference=reference,
        user=user if getattr(user, "is_authenticated", False) else None,
    )
    total = Decimal("0")
    for item in items:
        product = _lock_product(item["product"])
        quantity = qty(item["quantity"])
        cost = unit_cost(item["unit_cost"])
        if quantity <= 0:
            raise ValueError(f"Quantity for {product.name} must be greater than zero.")
        if cost < 0:
            raise ValueError(f"Cost for {product.name} cannot be negative.")
        balance = _lock_balance(product)
        batch = StockBatch.objects.create(
            product=product,
            supplier=supplier,
            received_at=purchase.purchase_date,
            expiry_date=item.get("expiry_date"),
            quantity=quantity,
            remaining=quantity,
            unit_cost=cost,
            reference=purchase.number,
            note=note,
        )
        existing = balance.quantity
        balance.quantity = existing + quantity
        balance.save(update_fields=["quantity", "updated_at"])
        _update_average_cost(product, quantity, quantity * cost, existing)
        _movement(
            product,
            StockMovement.KIND_RECEIPT,
            quantity,
            balance.quantity,
            unit_cost_value=cost,
            batch=batch,
            reference_type="Purchase",
            reference_id=purchase.pk,
            note=note,
            user=user,
        )
        line_total = money(quantity * cost)
        PurchaseLine.objects.create(
            purchase=purchase,
            product=product,
            quantity=quantity,
            unit_cost=cost,
            line_total=line_total,
            expiry_date=item.get("expiry_date"),
            batch=batch,
        )
        total += line_total
    purchase.total_cost = money(total)
    purchase.save(update_fields=["total_cost"])
    return purchase


def consume_stock(
    product,
    quantity,
    *,
    kind,
    reference_type="",
    reference_id="",
    note="",
    user=None,
    allow_negative=False,
):
    """Deduct a base-unit quantity, consuming batches first-in first-out.

    Returns the list of batch consumptions so the exact quantities and costs can
    be restored if the transaction is later reversed.
    """
    quantity = qty(quantity)
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    product = _lock_product(product)
    balance = _lock_balance(product)
    if quantity > balance.quantity and not allow_negative:
        raise InsufficientStock(product, quantity, balance.quantity)

    left = quantity
    consumptions = []
    batches = (
        StockBatch.objects.select_for_update()
        .filter(product=product, remaining__gt=0)
        .order_by("received_at", "id")
    )
    for batch in batches:
        if left <= 0:
            break
        take = min(batch.remaining, left)
        batch.remaining = batch.remaining - take
        batch.save(update_fields=["remaining"])
        consumptions.append(
            {"batch": batch, "quantity": take, "unit_cost": batch.unit_cost}
        )
        left -= take
    if left > 0 and balance.quantity > 0:
        # Balance without a batch (legacy/imported stock): cost at average.
        consumptions.append(
            {"batch": None, "quantity": left, "unit_cost": product.average_cost}
        )
        left = Decimal("0")
    if left > 0 and not allow_negative:
        raise InsufficientStock(product, quantity, balance.quantity)

    balance.quantity = balance.quantity - quantity
    balance.save(update_fields=["quantity", "updated_at"])
    total_cost = sum((c["quantity"] * c["unit_cost"] for c in consumptions), Decimal("0"))
    movement_cost = divide(total_cost, quantity, places=4)
    batch_ref = consumptions[-1]["batch"] if consumptions else None
    _movement(
        product,
        kind,
        -quantity,
        balance.quantity,
        unit_cost_value=movement_cost,
        batch=batch_ref,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        user=user,
    )
    return consumptions


def restore_stock(
    product, consumptions, *, kind, reference_type="", reference_id="", note="", user=None
):
    """Give back exactly the quantities recorded when stock was consumed."""
    product = _lock_product(product)
    balance = _lock_balance(product)
    restored = Decimal("0")
    for entry in consumptions:
        quantity = qty(entry["quantity"])
        if quantity <= 0:
            continue
        batch = entry.get("batch")
        if batch is not None:
            batch = StockBatch.objects.select_for_update().filter(pk=batch.pk).first()
        if batch is not None:
            batch.remaining = batch.remaining + quantity
            batch.save(update_fields=["remaining"])
        balance.quantity = balance.quantity + quantity
        balance.save(update_fields=["quantity", "updated_at"])
        _movement(
            product,
            kind,
            quantity,
            balance.quantity,
            unit_cost_value=entry.get("unit_cost") or Decimal("0"),
            batch=batch,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            user=user,
        )
        restored += quantity
    return restored


@transaction.atomic
def adjust_stock(*, product, delta, reason, user, note=""):
    """Apply a signed stock correction. Rejected if it would go below zero."""
    delta = qty(delta)
    if delta == 0:
        raise ValueError("Enter a quantity to adjust.")
    if not reason:
        raise ValueError("Choose a reason for the adjustment.")
    product = _lock_product(product)
    if delta > 0:
        balance = _lock_balance(product)
        cost = product.average_cost
        batch = StockBatch.objects.create(
            product=product,
            received_at=timezone.localdate(),
            quantity=delta,
            remaining=delta,
            unit_cost=cost,
            reference="adjustment",
            note=note or "Stock adjustment",
        )
        balance.quantity = balance.quantity + delta
        balance.save(update_fields=["quantity", "updated_at"])
        _movement(
            product,
            StockMovement.KIND_ADJUSTMENT,
            delta,
            balance.quantity,
            unit_cost_value=cost,
            batch=batch,
            reference_type="StockAdjustment",
            note=note,
            user=user,
        )
        balance_after = balance.quantity
    else:
        consume_stock(
            product,
            -delta,
            kind=StockMovement.KIND_ADJUSTMENT,
            reference_type="StockAdjustment",
            note=note,
            user=user,
        )
        balance_after = _lock_balance(product).quantity
    adjustment = StockAdjustment.objects.create(
        product=product,
        quantity_delta=delta,
        balance_after=balance_after,
        reason=reason,
        note=note,
        user=user if getattr(user, "is_authenticated", False) else None,
    )
    return adjustment


@transaction.atomic
def pack_from_bulk(
    *,
    bulk_product,
    packed_product,
    ml_per_bottle,
    bottles,
    user,
    note="",
    extra_cost_per_bottle=Decimal("0"),
):
    """Convert bulk millilitres into independently stocked packed bottles."""
    ml_per_bottle = qty(ml_per_bottle)
    bottles = int(bottles)
    if bottles <= 0:
        raise ValueError("Number of bottles must be greater than zero.")
    if ml_per_bottle <= 0:
        raise ValueError("Millilitres per bottle must be greater than zero.")
    bulk_product = _lock_product(bulk_product)
    packed_product = _lock_product(packed_product)
    if bulk_product.kind != Product.KIND_BULK:
        raise ValueError("The source product must be a bulk perfume.")
    if packed_product.kind != Product.KIND_PACKED:
        raise ValueError("The destination product must be a packed perfume.")
    if packed_product.bulk_parent_id != bulk_product.pk:
        raise ValueError("The packed product is not linked to this bulk perfume.")
    total_ml = qty(ml_per_bottle * bottles)
    run = PackRun.objects.create(
        bulk_product=bulk_product,
        packed_product=packed_product,
        ml_per_bottle=ml_per_bottle,
        bottles=bottles,
        total_ml=total_ml,
        total_cost=0,
        cost_per_bottle=0,
        note=note,
        user=user if getattr(user, "is_authenticated", False) else None,
    )
    consumptions = consume_stock(
        bulk_product,
        total_ml,
        kind=StockMovement.KIND_PACK_OUT,
        reference_type="PackRun",
        reference_id=run.pk,
        note=note or "Packing run",
        user=user,
    )
    liquid_cost = sum(
        (c["quantity"] * c["unit_cost"] for c in consumptions), Decimal("0")
    )
    extra = money(Decimal(extra_cost_per_bottle) * bottles)
    total_cost = money(liquid_cost + extra)
    per_bottle = divide(total_cost, bottles, places=4)

    balance = _lock_balance(packed_product)
    batch = StockBatch.objects.create(
        product=packed_product,
        received_at=timezone.localdate(),
        quantity=bottles,
        remaining=bottles,
        unit_cost=per_bottle,
        reference="packing",
        note=note or "Packed from bulk",
    )
    existing = balance.quantity
    balance.quantity = existing + bottles
    balance.save(update_fields=["quantity", "updated_at"])
    _update_average_cost(packed_product, Decimal(bottles), total_cost, existing)
    _movement(
        packed_product,
        StockMovement.KIND_PACK_IN,
        Decimal(bottles),
        balance.quantity,
        unit_cost_value=per_bottle,
        batch=batch,
        reference_type="PackRun",
        reference_id=run.pk,
        note=note,
        user=user,
    )
    run.total_cost = total_cost
    run.cost_per_bottle = per_bottle
    run.save(update_fields=["total_cost", "cost_per_bottle"])
    return run


def stock_valuation():
    total = Decimal("0")
    for batch in StockBatch.objects.filter(remaining__gt=0).only(
        "remaining", "unit_cost"
    ):
        total += batch.remaining * batch.unit_cost
    return money(total)
