"""Shared lifecycle fence for all memory-source pipelines."""

from __future__ import annotations

from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.file_locks import exclusive_file_lock, memory_source_lifecycle_lock_path

from .models import MemorySource


@contextmanager
def enabled_source_operation(*, source_id: int | None = None, source_code: str = "", timeout: float = 300.0):
    """Yield a fresh enabled source under the common process-wide fence."""

    if not source_id and not source_code:
        raise ValidationError("Не указан источник памяти.")
    with exclusive_file_lock(memory_source_lifecycle_lock_path(), timeout=timeout):
        with transaction.atomic():
            queryset = MemorySource.objects.select_for_update()
            source = (
                queryset.filter(pk=source_id).first()
                if source_id
                else queryset.filter(code=source_code).first()
            )
            if source is None:
                raise ValidationError("Источник памяти не найден.")
            if source.status != MemorySource.Status.ENABLED:
                raise ValidationError(f"Источник '{source.code}' отключён для операций памяти.")
        # The DB row lock is released before long I/O; the process lock stays
        # held, and every supported status writer uses the same fence.
        yield source
