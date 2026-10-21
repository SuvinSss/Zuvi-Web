"""Test helper: TransactionTestCase truncates tables, which removes the seeded default pricing."""
import importlib

from django.apps import apps


def ensure_default_pricing():
    importlib.import_module("logistics.migrations.0002_seed_default_pricing").seed(apps, None)
