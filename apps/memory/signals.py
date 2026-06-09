"""Cross-database FK cleanup for chat sessions.

Django's cascade collector (django/db/models/deletion.py:305-310) only
skips the reverse-FK SELECT when on_delete is DO_NOTHING. The
``MemoryWriteRequest.session`` FK points from ``knowledge_meta`` to
``ai.ChatSession`` on the ``chat`` database, so we use DO_NOTHING to
avoid the cross-database SELECT. The side effect is that deleting a
ChatSession leaves a dangling ``session_id`` on any
MemoryWriteRequest rows that referenced it.

This signal achieves SET_NULL semantics for MemoryWriteRequest by
issuing an explicit UPDATE against the router-resolved
``knowledge_meta`` database BEFORE Django's collector runs. The
UPDATE is scoped to ``instance.id`` (the chat being deleted) so it
is safe under concurrent deletes.

For MemoryKnowledgeItem we intentionally keep DO_NOTHING semantics:
a knowledge item outlives its source chat by design, and the
dangling ``source_session_id`` is useful for audit.
"""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.ai.models import ChatSession

from .models import MemoryWriteRequest


@receiver(pre_delete, sender=ChatSession)
def nullify_memory_write_request_sessions(sender, instance, **kwargs):
    """Set ``MemoryWriteRequest.session_id`` to NULL when the referenced
    ChatSession is deleted.

    ``MemoryWriteRequest.objects`` uses the router and resolves to
    ``knowledge_meta``; ``.update()`` bypasses Django's cascade
    collector and therefore does not issue the cross-database SELECT
    that would otherwise target the ``chat`` database.
    """
    MemoryWriteRequest.objects.filter(session_id=instance.id).update(
        session_id=None
    )
