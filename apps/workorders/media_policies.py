"""Политика защищённой выдачи файлов вложений заявок (префикс ``workorders``).

Регистрируется в ``WorkordersConfig.ready()`` в общем реестре ``apps.core.media``.
Логика перенесена из бывшего view ``serve_workorder_attachment`` без изменения
поведения для ``/media/workorders/…``: файл резолвится через доменный объект
``WorkOrderAttachment`` (право видеть проверяется штатной политикой ``can_view``
на связанной заявке, а не по «сырой» строке пути).
"""
from apps.core.media import build_file_response, resolve_media_path

from .models import WorkOrderAttachment
from .policies import can_view


def serve_workorder_media(request, subpath):
    """Возвращает ``FileResponse`` вложения заявки или ``None`` (отказ → 404)."""
    absolute = resolve_media_path("workorders", subpath)
    if absolute is None:
        return None

    attachment = WorkOrderAttachment.objects.filter(file=f"workorders/{subpath}").first()
    if attachment is None or not can_view(request.user, attachment.workorder):
        # None → 404, а не 403: не раскрываем факт существования файла.
        return None

    if not absolute.is_file():
        return None

    return build_file_response(absolute, attachment.filename, attachment.content_type)
