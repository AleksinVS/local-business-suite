from __future__ import annotations

from django.conf import settings

from .descriptors import mask_sensitive
from .registry import get_registry


def build_help_context(setting_id: str, current_value=None) -> dict:
    descriptor = get_registry().get(setting_id)
    return descriptor.safe_context(current_value=current_value)


def initial_help_text(setting_id: str) -> str:
    descriptor = get_registry().get(setting_id)
    restart = " Изменение требует перезапуска процесса." if descriptor.requires_restart else ""
    reindex = " После изменения может потребоваться переиндексация." if descriptor.requires_reindex else ""
    return f"{descriptor.title}: {descriptor.description}{restart}{reindex}"


def answer_help_question(*, setting_id: str, question: str, current_value=None) -> dict:
    context = build_help_context(setting_id, current_value=current_value)
    question_text = str(question or "").strip()
    if not question_text:
        text = initial_help_text(setting_id)
    else:
        text = (
            f"Контекст настройки: {context['title']} ({context['setting_id']}). "
            f"{context['description']} Вопрос: {question_text}"
        )
    return {
        "answer": text,
        "context": mask_sensitive(context),
        "ai_enabled": bool(getattr(settings, "SETTINGS_CENTER_HELP_AI_ENABLED", True)),
    }
