from django.core.management.base import BaseCommand

from catalog.services import refresh_due_offer_prices


class Command(BaseCommand):
    help = "Apply or remove scheduled discounts whose offer window has started or ended. Run every few minutes from cron."

    def handle(self, *args, **options):
        changed = refresh_due_offer_prices()
        self.stdout.write(f"Updated {changed} product price(s).")
