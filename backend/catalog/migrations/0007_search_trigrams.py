from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0006_product_approved_by_approved_at")]
    operations = [TrigramExtension()]
