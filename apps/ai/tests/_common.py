"""Общий preamble для разбитого набора тестов ai (импорты, фикстуры, mixin).

Не является тест-модулем (имя не совпадает с шаблоном discovery). Тематические
модули берут отсюда имена через ``from ..tests._common import *``.
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Department
from apps.workorders.models import Board, WorkOrder, WorkOrderStatus
from apps.workorders.policies import ROLE_CUSTOMER, ROLE_MANAGER
from apps.waiting_list.services import create_entry

User = get_user_model()
RUNTIME_DATABASES = {"default"}

from ..models import AIWindowContextSnapshot, AgentActionLog, ChatMessage, ChatSession, PendingAction
from ..chat_settings import get_chat_settings
from ..page_context import update_window_context_snapshot
from ..runtime_client import AgentRuntimeError
from ..services import normalize_session_external_id
from ..tooling import UnknownToolError, execute_pending_action, execute_tool
from ..ui_runtime.drivers import configured_ai_ui_driver
