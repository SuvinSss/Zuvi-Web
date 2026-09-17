"""Supervised local operator entry point; no worker or automatic retry."""
import json
import signal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from catalog.import_contract import ImportProblem
from catalog.import_permissions import require_action
from catalog.import_services import counts, execute_job, prepare_job
from catalog.models import ImportJob


class Command(BaseCommand):
    help = 'Supervised catalogue import: prepare, execute, resume or status (direct PostgreSQL session required).'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['prepare', 'execute', 'resume', 'status'])
        parser.add_argument('--job', required=True, type=str)
        parser.add_argument('--actor', required=True, help='Accountable active management username; trusted local shell access is required.')
        parser.add_argument('--image-dir', help='Private incoming folder; accepted only for prepare.')
        parser.add_argument('--reclaim-stale', action='store_true')

    def handle(self, *args, **options):
        if options['action'] != 'prepare' and options['image_dir']:
            raise CommandError('Image replacement is accepted only before approval through prepare.')
        if options['action'] == 'prepare' and not options['image_dir']:
            raise CommandError('prepare requires --image-dir inside the private incoming folder.')
        previous = signal.getsignal(signal.SIGTERM)
        def stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            actor = get_user_model().objects.get(username=options['actor'])
            job = ImportJob.objects.select_related('store').get(pk=options['job'])
            if options['action'] == 'status':
                require_action(actor, 'execute', store=job.store, job=job)
            elif options['action'] == 'prepare':
                job = prepare_job(job_id=job.pk, actor=actor, image_dir=options['image_dir'], reclaim_stale=options['reclaim_stale'])
            else:
                job = execute_job(job_id=job.pk, actor=actor, resume=options['action'] == 'resume', reclaim_stale=options['reclaim_stale'],
                                  progress=lambda event: self.stdout.write(json.dumps(event)))
            self.stdout.write(json.dumps({'job': str(job.pk), 'status': job.status, 'counts': counts(job), 'last_error_code': job.last_error_code}))
        except (ImportProblem, PermissionDenied) as exc:
            raise CommandError(str(exc)) from None
        except (get_user_model().DoesNotExist, ImportJob.DoesNotExist, ValueError, ValidationError):
            raise CommandError('The specified actor or job is unavailable.') from None
        except KeyboardInterrupt:
            raise CommandError('Interrupted. Inspect durable status and use explicit resume; uploaded orphan objects may remain.') from None
        finally:
            signal.signal(signal.SIGTERM, previous)
