from __future__ import annotations

import hashlib
import json
from typing import Any

from django.utils import timezone

from .descriptors import mask_sensitive
from .models import SettingsChange


def stable_hash(value: Any) -> str:
    data = json.dumps(mask_sensitive(value), ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_masked_diff(before: Any, after: Any) -> dict[str, Any]:
    before_masked = mask_sensitive(before)
    after_masked = mask_sensitive(after)
    if before_masked == after_masked:
        return {"changed": False, "before": before_masked, "after": after_masked}
    return {"changed": True, "before": before_masked, "after": after_masked}


def record_settings_change(
    *,
    actor,
    descriptor,
    action,
    status,
    before=None,
    after=None,
    validation_result=None,
) -> SettingsChange:
    return SettingsChange.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        setting_id=descriptor.setting_id,
        domain=descriptor.domain,
        storage_kind=descriptor.storage_kind,
        action=action,
        status=status,
        before_hash=stable_hash(before) if before is not None else "",
        after_hash=stable_hash(after) if after is not None else "",
        masked_diff=build_masked_diff(before, after) if before is not None or after is not None else {},
        validation_result=mask_sensitive(validation_result or {}),
        requires_restart=descriptor.requires_restart,
        requires_reindex=descriptor.requires_reindex,
        applied_at=timezone.now() if status == SettingsChange.Status.APPLIED else None,
    )
