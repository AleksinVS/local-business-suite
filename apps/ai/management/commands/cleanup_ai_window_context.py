from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ai.models import AIWindowContextSnapshot


class Command(BaseCommand):
    help = "Delete expired AI window context snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only report how many rows would be deleted.")

    def handle(self, *args, **options):
        queryset = AIWindowContextSnapshot.objects.filter(expires_at__lt=timezone.now())
        count = queryset.count()
        if not options["dry_run"]:
            queryset.delete()
        suffix = "would be deleted" if options["dry_run"] else "deleted"
        self.stdout.write(self.style.SUCCESS(f"{count} AI window context snapshots {suffix}."))
