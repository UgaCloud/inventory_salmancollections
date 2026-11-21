from django.test import TestCase
from django.urls import reverse

from .audit import log_action
from .backup import create_backup, restore_backup
from .models import AuditLog, BackupRecord, Role, ShopSettings
from .services import ensure_defaults
from .testing import make_staff
from inventory.models import Product
from inventory.services import add_opening_stock


class PermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.cashier = make_staff("cashier", "cashier")
        cls.accountant = make_staff("accountant", "accountant")
        cls.storekeeper = make_staff("storekeeper", "storekeeper")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_cashier_can_use_dashboard_and_pos(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales:pos")).status_code, 200)

    def test_cashier_cannot_manage_inventory_or_finance(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("inventory:products")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:adjustments")).status_code, 403)
        self.assertEqual(self.client.get(reverse("finance:expenses")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:settings")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:backups")).status_code, 403)

    def test_accountant_can_view_reports_and_expenses(self):
        self.client.force_login(self.accountant)
        self.assertEqual(self.client.get(reverse("reports:hub")).status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:expenses")).status_code, 200)
        self.assertEqual(self.client.get(reverse("inventory:adjustments")).status_code, 403)

    def test_storekeeper_can_manage_stock_but_not_users(self):
        self.client.force_login(self.storekeeper)
        self.assertEqual(self.client.get(reverse("inventory:products")).status_code, 200)
        self.assertEqual(self.client.get(reverse("inventory:adjustments")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:users")).status_code, 403)

    def test_role_change_takes_effect_immediately(self):
        role = Role.objects.get(slug="cashier")
        role.permissions = list(role.permissions) + ["reports.view"]
        role.save()
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("reports:hub")).status_code, 200)

    def test_owner_reaches_settings(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("core:settings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:backups")).status_code, 200)


class AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.product = Product.objects.create(
            name="Tote", sku="BAG-1", unit_price=10
        )

    def test_audit_entry_is_recorded(self):
        log_action(action="Stock adjusted", user=self.owner, target=self.product, detail={"delta": "1"})
        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, "Stock adjusted")
        self.assertEqual(entry.target_type, "Product")
        self.assertEqual(entry.target_id, str(self.product.pk))

    def test_audit_page_lists_entries(self):
        log_action(action="Stock adjusted", user=self.owner, target=self.product)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:audit"))
        self.assertContains(response, "Stock adjusted")


class BackupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.owner = make_staff("owner", "owner", superuser=True)
        cls.product = Product.objects.create(name="Original name", sku="SKU-1", unit_price=5)
        add_opening_stock(cls.product, 4, 2)

    def test_restore_round_trip_creates_safety_backup(self):
        record = create_backup(user=self.owner, kind="manual")
        self.assertTrue(record.checksum)
        BackupRecord.objects.get(pk=record.pk)

        self.product.name = "Changed later"
        self.product.save()

        safety = restore_backup(record, user=self.owner)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Original name")
        self.assertTrue(BackupRecord.objects.filter(filename=safety.filename).exists())
        self.assertTrue(Role.objects.filter(slug="owner").exists())
        self.assertEqual(ShopSettings.objects.count(), 1)

    def test_download_requires_backup_permission(self):
        record = create_backup(user=self.owner, kind="manual")
        cashier = make_staff("cashier2", "cashier")
        self.client.force_login(cashier)
        response = self.client.get(reverse("core:backup_download", args=[record.pk]))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:backup_download", args=[record.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()
