"""Валидация доменных контрактов листа ожидания."""

from apps.core.contracts import validate_status_colors_payload

from .models import WaitingListStatus


def validate_waiting_list_status_colors_payload(payload):
    validate_status_colors_payload(
        payload,
        subject="листа ожидания",
        known_statuses=WaitingListStatus.values,
    )
