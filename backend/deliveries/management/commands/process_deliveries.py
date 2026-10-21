from django.core.management.base import BaseCommand

from deliveries import services


class Command(BaseCommand):
    help = "Expire unanswered delivery offers and retry automatic assignment for queued deliveries. Run every minute or so."

    def handle(self, *args, **options):
        expired = services.expire_stale_offers()
        assigned = services.sweep_unassigned()
        self.stdout.write(f"Expired {expired} offers, assigned {assigned} queued deliveries.")
