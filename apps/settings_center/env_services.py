from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.json_utils import atomic_write_json

from .descriptors import mask_sensitive
from .models import SettingsEnvProposal
from .registry import get_registry


def env_apply_mode() -> str:
    mode = getattr(settings, "SETTINGS_CENTER_ENV_APPLY_MODE", "proposal")
    if mode not in {"read_only", "proposal", "local_file"}:
        return "proposal"
    return mode


def env_apply_mode_label(mode: str | None = None) -> str:
    labels = {
        "read_only": "только чтение",
        "proposal": "через заявку",
        "local_file": "локальный файл",
    }
    return labels.get(mode or env_apply_mode(), "через заявку")


def effective_env_value(descriptor):
    key = descriptor.metadata.get("env_key")
    if not key:
        return ""
    import os

    return os.environ.get(key, descriptor.metadata.get("default", ""))


def env_status_rows():
    rows = []
    for descriptor in get_registry().all():
        if descriptor.storage_kind == "env_var":
            rows.append(
                {
                    "descriptor": descriptor,
                    "effective_value": mask_sensitive({"value": effective_env_value(descriptor)})["value"],
                    "apply_mode": env_apply_mode(),
                    "apply_mode_label": env_apply_mode_label(),
                }
            )
    return rows


def create_env_proposal(*, actor, changes: dict[str, str], target_label="default"):
    mode = env_apply_mode()
    if mode == "read_only":
        raise ValidationError("Настройки окружения доступны только для чтения в этом развертывании.")

    allowed_keys = {
        descriptor.metadata.get("env_key")
        for descriptor in get_registry().all()
        if descriptor.storage_kind == "env_var"
    }
    normalized = {str(key): str(value) for key, value in changes.items() if str(key) in allowed_keys}
    if not normalized:
        raise ValidationError("Не указан ни один поддерживаемый ключ окружения.")

    proposal_dir = Path(getattr(settings, "SETTINGS_CENTER_ENV_PROPOSAL_DIR", settings.DATA_DIR / "settings_center" / "env_proposals"))
    proposal_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_label": target_label,
        "created_at": timezone.now().isoformat(),
        "restart_required": True,
        "changes": mask_sensitive(normalized),
        "operator_checklist": [
            "Проверить значения в приватном контуре развертывания.",
            "Применить изменения в host-specific .env файле.",
            "Перезапустить затронутые web- и worker-процессы.",
            "Открыть центр настроек и проверить эффективные значения.",
        ],
    }
    path = proposal_dir / f"env_proposal_{timezone.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    atomic_write_json(path, payload)
    return SettingsEnvProposal.objects.create(
        actor=actor,
        target_label=target_label,
        file_path=str(path),
        masked_changes=payload["changes"],
    )
