from django.db import migrations


DEFAULT_UNITS = [
    ("Pieces", "pcs"),
    ("Pairs", "pair"),
    ("Millilitres", "ml"),
    ("Bottles", "bottle"),
]


def seed_units(apps, schema_editor):
    Unit = apps.get_model("inventory", "Unit")
    for name, code in DEFAULT_UNITS:
        Unit.objects.get_or_create(
            code=code, defaults={"name": name, "is_active": True, "is_system": True}
        )


def unseed_units(apps, schema_editor):
    Unit = apps.get_model("inventory", "Unit")
    Unit.objects.filter(code__in=[code for _, code in DEFAULT_UNITS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_unit_category_is_active"),
    ]

    operations = [
        migrations.RunPython(seed_units, unseed_units),
    ]