from django.core.exceptions import PermissionDenied

from apps.workorders.policies import is_manager


def can_view_waiting_list(user):
    return user.is_authenticated


def can_create_waiting_list(user):
    return user.is_authenticated


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
