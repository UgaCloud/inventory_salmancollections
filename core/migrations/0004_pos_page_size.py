import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_pagination_sizes"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopsettings",
            name="page_size_pos",
            field=models.PositiveSmallIntegerField(
                default=12,
                validators=[
                    django.core.validators.MinValueValidator(4),
                    django.core.validators.MaxValueValidator(60),
                ],
                verbose_name="Point of sale catalogue",
            ),
        ),
    ]
