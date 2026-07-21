from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ai.models import PendingAction


class Command(BaseCommand):
    help = "Mark expired pending AI actions as expired."

    def handle(self, *args, **options):
        updated = PendingAction.objects.filter(
            status=PendingAction.Status.PENDING,
            expires_at__lte=timezone.now(),
        ).update(status=PendingAction.Status.EXPIRED)
        self.stdout.write(self.style.SUCCESS(f"Expired pending AI actions: {updated}"))
