"""Тесты защищённой выдачи вложений ИИ-чата через единый media-dispatcher.

Проверяют доменную политику ``apps.ai.media_policies.serve_chat_attachment_media``
за маршрутом ``/media/chat_attachments/…``: доступ только владельцу сессии,
отказ чужому/анонимному, hardening (null-байт, path traversal, отсутствующий на
диске файл) и 404 на неизвестном префиксе.

MEDIA_ROOT подменяется на временный каталог, чтобы записанные тестом файлы не
попадали в data/media/.
"""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import ChatAttachment, ChatMessage, ChatSession

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ChatAttachmentServingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.owner = User.objects.create_user(username="chat_owner", password="pass")
        self.other = User.objects.create_user(username="chat_other", password="pass")

        self.session = ChatSession.objects.create(user=self.owner, title="Сессия владельца")
        self.message = ChatMessage.objects.create(
            session=self.session,
            role=ChatMessage.Role.USER,
            content="Сообщение с вложением",
        )
        self.attachment = ChatAttachment.objects.create(
            message=self.message,
            file=SimpleUploadedFile(
                "doc.txt", b"chat-file-bytes", content_type="text/plain"
            ),
            file_type=ChatAttachment.FileType.DOCUMENT,
            file_name="doc.txt",
            file_size=len(b"chat-file-bytes"),
        )
        # /media/chat_attachments/<YYYY>/<MM>/<DD>/doc.txt — совпадает с file.url.
        self.file_url = self.attachment.file.url

    def test_owner_receives_file(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"chat-file-bytes")

    def test_different_user_gets_404(self):
        self.client.force_login(self.other)
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_not_served(self):
        # Диспетчер под login_required: аноним получает redirect на login (302),
        # файл не отдаётся. 404 также допустим — главное, файл не раскрыт.
        response = self.client.get(self.file_url)
        self.assertIn(response.status_code, (302, 404))
        if response.status_code == 302:
            self.assertIn(reverse("login"), response.url)

    def test_null_byte_in_path_returns_404(self):
        self.client.force_login(self.owner)
        response = self.client.get("/media/chat_attachments/doc\x00.txt")
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_attempt_returns_404(self):
        secret = Path(settings.MEDIA_ROOT).resolve().parent / "chat_secret.txt"
        secret.write_bytes(b"top-secret")
        self.addCleanup(secret.unlink, missing_ok=True)

        self.client.force_login(self.owner)
        response = self.client.get("/media/chat_attachments/../../chat_secret.txt")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "top-secret", status_code=404)

    def test_missing_file_on_disk_returns_404(self):
        # Запись о вложении есть, а файла на диске нет — не 500, а 404.
        Path(self.attachment.file.path).unlink()
        self.client.force_login(self.owner)
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 404)

    def test_unknown_prefix_returns_404(self):
        self.client.force_login(self.owner)
        response = self.client.get("/media/nope/x")
        self.assertEqual(response.status_code, 404)
