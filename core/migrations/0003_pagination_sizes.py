import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_role_dashboard"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_default",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Default rows per page",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_products",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Products & perfumes",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_stock",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Stock overview",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_purchases",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Purchases & receiving",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_sales",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Sales & receipts",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_customers",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Customers",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_payments",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Customer payments",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_expenses",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Expenses",
            ),
        ),
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_audit",
            field=models.PositiveSmallIntegerField(
                default=10,
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Audit log",
            ),
        ),
    ]
