"""Compatibility cleanup for chat session deletes.

The PostgreSQL primary-store target keeps chat and memory tables in one
database, so normal FK ``SET_NULL`` handles this relation. The signal is
kept as an idempotent compatibility guard while older SQLite/multi-db
deployments are migrated.
"""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.ai.models import ChatSession

from .models import MemoryWriteRequest


@receiver(pre_delete, sender=ChatSession)
def nullify_memory_write_request_sessions(sender, instance, **kwargs):
    """Set ``MemoryWriteRequest.session_id`` to NULL before deletion."""
    MemoryWriteRequest.objects.filter(session_id=instance.id).update(
        session_id=None
    )
