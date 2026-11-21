"""Business data backup and restore (single shop, whole-database scope)."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from finance.models import CashReconciliation, Expense, ExpenseCategory
from inventory.models import (
    Category,
    PackRun,
    Product,
    Purchase,
    PurchaseLine,
    StockAdjustment,
    StockBalance,
    StockBatch,
    StockMovement,
    Supplier,
)
from sales.models import (
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

from .audit import log_action
from .models import BackupRecord, PaymentMethod, Role, ShopSettings, StaffProfile

# Parents before children; restore deletes in reverse.
BACKUP_MODELS = [
    ShopSettings,
    Role,
    PaymentMethod,
    Category,
    Supplier,
    Product,
    StockBalance,
    StockBatch,
    StockMovement,
    Purchase,
    PurchaseLine,
    StockAdjustment,
    PackRun,
    Customer,
    Mixture,
    MixtureComponent,
    Sale,
    SaleItem,
    StockConsumption,
    SalePayment,
    Refund,
    CustomerPayment,
    ExpenseCategory,
    Expense,
    CashReconciliation,
]


class BackupError(Exception):
    pass


def _field_names(model):
    # attname keys ("product_id") let Model(**row) assign relations directly,
    # and keeping the primary key preserves the ids other rows point at.
    return [f.attname for f in model._meta.concrete_fields]


def _backup_dir() -> Path:
    path = Path(settings.BACKUP_ROOT)
    path.mkdir(parents=True, exist_ok=True)
    return path


def serialize_shop():
    models = {}
    for model in BACKUP_MODELS:
        rows = list(model.objects.values(*_field_names(model)))
        if model is Product:
            # Bulk perfumes must exist before the packed bottles that link to them.
            rows.sort(key=lambda row: (row.get("bulk_parent_id") is not None, row["id"]))
        models[model._meta.label] = rows
    profiles = list(
        StaffProfile.objects.values("user_id", "role_id", "phone", "is_active")
    )
    return {
        "format": 1,
        "created_at": timezone.now().isoformat(),
        "shop": ShopSettings.load().name,
        "models": models,
        "staff_profiles": profiles,
    }


def _write_backup(payload, *, kind, user, note=""):
    raw = json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True).encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = {"manual": "backup", "automatic": "auto-backup", "safety": "safety"}[kind]
    filename = f"{prefix}-{stamp}-{checksum[:8]}.json"
    path = _backup_dir() / filename
    path.write_bytes(raw)
    count = sum(len(rows) for rows in payload["models"].values())
    record = BackupRecord.objects.create(
        filename=filename,
        file_size=len(raw),
        checksum=checksum,
        kind=kind,
        note=note,
        record_count=count,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    return record


def apply_retention(retention=None):
    shop = ShopSettings.load()
    retention = retention or shop.backup_retention or 10
    records = list(BackupRecord.objects.filter(kind__in=["manual", "automatic"]).order_by("-created_at"))
    for record in records[retention:]:
        delete_backup(record)


def create_backup(*, user=None, kind="manual", note="", enforce_retention=True):
    payload = serialize_shop()
    record = _write_backup(payload, kind=kind, user=user, note=note)
    if enforce_retention:
        apply_retention()
    return record


def delete_backup(record):
    path = Path(settings.BACKUP_ROOT) / record.filename
    try:
        if path.exists():
            os.remove(path)
    except OSError:
        pass
    record.delete()


def verify_backup(record):
    path = Path(settings.BACKUP_ROOT) / record.filename
    if not path.exists():
        raise BackupError("The backup file is missing from the backup store.")
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if record.checksum and checksum != record.checksum:
        raise BackupError("Backup integrity check failed: checksum mismatch.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BackupError("The backup file is not valid JSON.")
    if payload.get("format") != 1 or "models" not in payload:
        raise BackupError("Unrecognised backup format.")
    return payload


@transaction.atomic
def restore_backup(record, *, user=None):
    """Restore a verified backup, creating a safety backup first."""
    payload = verify_backup(record)
    safety = create_backup(
        user=user,
        kind="safety",
        note=f"Safety backup before restoring {record.filename}",
        enforce_retention=False,
    )
    models = payload["models"]
    for model in reversed(BACKUP_MODELS):
        model.objects.all().delete()
    for model in BACKUP_MODELS:
        rows = models.get(model._meta.label, [])
        if not rows:
            continue
        objects = [model(**row) for row in rows]
        model.objects.bulk_create(objects, batch_size=500)
    for profile in payload.get("staff_profiles", []):
        StaffProfile.objects.filter(user_id=profile["user_id"]).update(
            role_id=profile.get("role_id"),
            phone=profile.get("phone", ""),
            is_active=profile.get("is_active", True),
        )
    log_action(
        action="Backup restored",
        user=user,
        target=record,
        detail={"filename": record.filename, "safety_backup": safety.filename},
    )
    return safety
