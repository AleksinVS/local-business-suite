"""Политика защищённой выдачи вложений ИИ-чата (префикс ``chat_attachments``).

Регистрируется в ``AiConfig.ready()`` в общем реестре ``apps.core.media``.
Восстанавливает защищённую раздачу ``ChatAttachment``, потерявшую маршрут в
пакете 03 (``chat_detail.html`` по-прежнему ссылается на ``{{ att.file.url }}``).

Владение файлом определяется цепочкой ``ChatAttachment → message → session →
user``: пользователь получает файл только если сессия сообщения принадлежит ему.
"""
from apps.core.media import build_file_response, resolve_media_path

from .models import ChatAttachment


def serve_chat_attachment_media(request, subpath):
    """Возвращает ``FileResponse`` вложения чата владельцу или ``None`` (→ 404)."""
    if not request.user.is_authenticated:
        return None

    absolute = resolve_media_path("chat_attachments", subpath)
    if absolute is None:
        return None

    attachment = (
        ChatAttachment.objects.select_related("message__session")
        .filter(file=f"chat_attachments/{subpath}")
        .first()
    )
    if attachment is None:
        return None

    message = attachment.message
    # message опционален (blank/null): без сообщения владельца определить нельзя
    # → отказ (404), а не незамеченный AttributeError → HTTP 500.
    if message is None or message.session.user_id != request.user.id:
        return None

    if not absolute.is_file():
        return None

    # У ChatAttachment нет поля content_type — тип выводит FileResponse по имени.
    return build_file_response(absolute, attachment.file_name)
