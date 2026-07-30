from django.core.exceptions import PermissionDenied

from apps.workorders.policies import has_role_capability, is_manager

# Роль контракта, которой по умолчанию выданы права листа ожидания.
ROLE_DOCTOR = "doctor"


def can_view_waiting_list(user):
    # Лист ожидания содержит персональные данные пациентов: доступ только по
    # праву view_waiting_list из контракта ролей (по умолчанию — роль «Врач»).
    return user.is_authenticated and has_role_capability(user, "view_waiting_list")


def can_create_waiting_list(user):
    return user.is_authenticated and has_role_capability(user, "create_waiting_list")


def can_edit_waiting_list_entry(user, entry):
    if not user.is_authenticated:
        return False
    if is_manager(user):
        return True
    return entry.author_id == user.id


def can_transition_waiting_list_entry(user, entry):
    if not user.is_authenticated:
        return False
    if is_manager(user):
        return True
    return entry.author_id == user.id
