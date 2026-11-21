from django.core.management.base import BaseCommand

from core.backup import create_backup
from core.models import ShopSettings


class Command(BaseCommand):
    help = "Create a shop backup. Use --auto to respect the automatic backup setting."

    def add_arguments(self, parser):
        parser.add_argument("--auto", action="store_true", help="Only run when automatic backups are enabled.")

    def handle(self, *args, **options):
        shop = ShopSettings.load()
        if options["auto"] and not shop.auto_backup_enabled:
            self.stdout.write("Automatic backups are disabled; nothing to do.")
            return
        record = create_backup(
            kind="automatic" if options["auto"] else "manual",
            note="Scheduled backup" if options["auto"] else "Command line backup",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Backup created: {record.filename} ({record.record_count} records)"
            )
        )
