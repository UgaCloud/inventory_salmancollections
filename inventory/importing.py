import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Category, Product
from .services import add_opening_stock

TEMPLATE_COLUMNS = [
    "name",
    "sku",
    "barcode",
    "category",
    "kind",
    "unit",
    "brand",
    "concentration",
    "unit_price",
    "reorder_level",
    "packed_size_ml",
    "bulk_parent_sku",
    "opening_stock",
    "opening_cost",
    "preset_sizes",
]

TEMPLATE_ROWS = [
    [
        "Classic Tote Bag",
        "BAG-001",
        "6001001001",
        "Handbags",
        "standard",
        "pcs",
        "Example",
        "",
        "25.00",
        "3",
        "",
        "",
        "10",
        "12.00",
        "",
    ],
    [
        "Oud Royale",
        "OUD-BULK",
        "",
        "Perfumes",
        "bulk_perfume",
        "ml",
        "Example",
        "EDP",
        "1.20",
        "100",
        "",
        "",
        "500",
        "0.55",
        "5:7.00;10:12.00;30:32.00",
    ],
    [
        "Oud Royale 30ml",
        "OUD-30",
        "6002002001",
        "Perfumes",
        "packed_perfume",
        "bottle",
        "Example",
        "EDP",
        "32.00",
        "5",
        "30",
        "OUD-BULK",
        "10",
        "17.00",
        "",
    ],
]

VALID_KINDS = {choice[0] for choice in Product.KIND_CHOICES}
VALID_UNITS = {choice[0] for choice in Product.UNIT_CHOICES}


def template_csv():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerows(TEMPLATE_ROWS)
    return buffer.getvalue()


def _decimal(value, field, row_number, errors, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            errors.append(f"Row {row_number}: {field} is required.")
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        errors.append(f"Row {row_number}: {field} must be a number.")
        return None


def _parse_presets(value, row_number, errors):
    presets = []
    for chunk in (value or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            errors.append(f"Row {row_number}: preset sizes must look like 10:4.50;15:6.50.")
            continue
        size, _, price = chunk.partition(":")
        try:
            ml = Decimal(size.strip())
            amount = Decimal(price.strip())
        except InvalidOperation:
            errors.append(f"Row {row_number}: invalid preset size '{chunk}'.")
            continue
        if ml <= 0 or amount < 0:
            errors.append(f"Row {row_number}: preset '{chunk}' must use positive sizes.")
            continue
        presets.append({"ml": str(ml), "price": str(amount.quantize(Decimal("0.01")))})
    return sorted(presets, key=lambda item: Decimal(item["ml"]))


def import_products(csv_file, *, user=None):
    """Validate the whole file, then import it atomically. Returns (count, errors)."""
    try:
        raw = csv_file.read()
    except Exception:
        return 0, ["The file could not be read."]
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raw = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return 0, ["The CSV file has no header row."]
    missing = [column for column in ("name", "sku", "unit_price") if column not in reader.fieldnames]
    if missing:
        return 0, [f"Missing required column(s): {', '.join(missing)}."]
    rows = list(reader)
    if not rows:
        return 0, ["The CSV file contains no product rows."]

    errors = []
    prepared = []
    seen_skus = set()
    seen_barcodes = set()
    for index, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        sku = (row.get("sku") or "").strip()
        if not name:
            errors.append(f"Row {index}: name is required.")
        if not sku:
            errors.append(f"Row {index}: sku is required.")
            continue
        if sku.lower() in seen_skus:
            errors.append(f"Row {index}: SKU {sku} appears twice in the file.")
        seen_skus.add(sku.lower())
        if Product.objects.filter(sku__iexact=sku).exists():
            errors.append(f"Row {index}: SKU {sku} already exists.")
        barcode = (row.get("barcode") or "").strip()
        if barcode:
            if barcode in seen_barcodes or Product.objects.filter(barcode=barcode).exists():
                errors.append(f"Row {index}: barcode {barcode} is already in use.")
            seen_barcodes.add(barcode)
        kind = (row.get("kind") or Product.KIND_STANDARD).strip() or Product.KIND_STANDARD
        if kind not in VALID_KINDS:
            errors.append(f"Row {index}: unknown product type '{kind}'.")
        unit = (row.get("unit") or "").strip()
        if kind == Product.KIND_BULK:
            unit = Product.UNIT_ML
        elif not unit:
            unit = Product.UNIT_PIECE
        if unit not in VALID_UNITS:
            errors.append(f"Row {index}: unknown unit '{unit}'.")
        price = _decimal(row.get("unit_price"), "unit_price", index, errors, required=True)
        if price is not None and price < 0:
            errors.append(f"Row {index}: unit_price cannot be negative.")
        reorder = _decimal(row.get("reorder_level"), "reorder_level", index, errors)
        packed_size = _decimal(row.get("packed_size_ml"), "packed_size_ml", index, errors)
        opening = _decimal(row.get("opening_stock"), "opening_stock", index, errors) or Decimal("0")
        opening_cost = _decimal(row.get("opening_cost"), "opening_cost", index, errors) or Decimal("0")
        if opening < 0:
            errors.append(f"Row {index}: opening_stock cannot be negative.")
        presets = _parse_presets(row.get("preset_sizes"), index, errors) if kind == Product.KIND_BULK else []
        prepared.append(
            {
                "name": name,
                "sku": sku,
                "barcode": barcode or None,
                "category": (row.get("category") or "").strip(),
                "kind": kind,
                "unit": unit,
                "brand": (row.get("brand") or "").strip(),
                "concentration": (row.get("concentration") or "").strip(),
                "unit_price": price or Decimal("0"),
                "reorder_level": reorder or Decimal("0"),
                "packed_size_ml": packed_size,
                "bulk_parent_sku": (row.get("bulk_parent_sku") or "").strip(),
                "opening": opening,
                "opening_cost": opening_cost,
                "presets": presets,
                "row": index,
            }
        )
    if errors:
        return 0, errors

    created = 0
    with transaction.atomic():
        products_by_sku = {}
        pending_parents = []
        for item in prepared:
            category = None
            if item["category"]:
                category, _ = Category.objects.get_or_create(name=item["category"])
            product = Product.objects.create(
                name=item["name"],
                sku=item["sku"],
                barcode=item["barcode"],
                category=category,
                kind=item["kind"],
                unit=item["unit"],
                brand=item["brand"],
                concentration=item["concentration"],
                unit_price=item["unit_price"],
                reorder_level=item["reorder_level"],
                packed_size_ml=item["packed_size_ml"],
                preset_sizes=item["presets"],
            )
            products_by_sku[item["sku"]] = product
            if item["kind"] == Product.KIND_PACKED and item["bulk_parent_sku"]:
                pending_parents.append((product, item))
            if item["opening"] > 0:
                add_opening_stock(
                    product,
                    item["opening"],
                    item["opening_cost"],
                    user=user,
                    note="Imported opening stock",
                )
            created += 1

        # Link packed bottles after every product exists, so row order does not matter.
        for product, item in pending_parents:
            bulk_parent = products_by_sku.get(item["bulk_parent_sku"]) or Product.objects.filter(
                sku=item["bulk_parent_sku"]
            ).first()
            if bulk_parent is None:
                raise ValueError(
                    f"Row {item['row']}: linked bulk perfume {item['bulk_parent_sku']} was not found."
                )
            if bulk_parent.kind != Product.KIND_BULK:
                raise ValueError(f"Row {item['row']}: the linked product is not a bulk perfume.")
            product.bulk_parent = bulk_parent
            product.save(update_fields=["bulk_parent"])
    return created, []
