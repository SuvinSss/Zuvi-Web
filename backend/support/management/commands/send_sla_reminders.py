from django.core.management.base import BaseCommand

from support.services import send_sla_reminders


class Command(BaseCommand):
    help = "Send due-soon / breached SLA notifications for open tickets and complaints (each only once)."

    def handle(self, *args, **options):
        result = send_sla_reminders()
        self.stdout.write(f"SLA reminders sent: {result['due_soon']} due soon, {result['breached']} breached.")
