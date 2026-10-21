from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0011_photo_import_product_image_path"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="auto_publish_on_first_image",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text="Publish after an authorized manager uploads a valid image.",
            ),
        ),
    ]
