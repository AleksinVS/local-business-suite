"""Тесты на ``apps/ai/context_processors.py``.

Файл существует отдельно от ``apps/ai/tests.py`` (там же монолит
``AIViewsTests`` и прочие), чтобы не плодить пакет ``tests/`` при наличии
``tests.py`` — Django test discovery конфликтует в этом случае.

См. ADR-0029.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from apps.ai import context_processors
from apps.ai.context_processors import sidebar_ai_chat
from apps.ai.ui_runtime.drivers import (
    DRIVER_COPILOTKIT,
    DRIVER_LEGACY,
    DRIVER_NATIVE,
)
from apps.workorders.policies import ROLE_MANAGER

User = get_user_model()


class FileAssetVersionTests(TestCase):
    """Поведение ``_file_asset_version`` при разном состоянии ``staticfiles/``."""

    def setUp(self):
        # Очищаем lru_cache между тестами — иначе первый удар кэшируется.
        context_processors.native_ai_asset_version.cache_clear()
        context_processors.native_ai_css_version.cache_clear()
        context_processors.copilotkit_asset_version.cache_clear()
        context_processors.copilotkit_css_version.cache_clear()

    def tearDown(self):
        context_processors.native_ai_asset_version.cache_clear()
        context_processors.native_ai_css_version.cache_clear()
        context_processors.copilotkit_asset_version.cache_clear()
        context_processors.copilotkit_css_version.cache_clear()

    def test_returns_fallback_when_static_root_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with override_settings(STATIC_ROOT=str(missing)):
                self.assertEqual(
                    context_processors._file_asset_version(
                        "src/ai_ui/native_ai.js", "fallback-string"
                    ),
                    "fallback-string",
                )

    def test_returns_hash_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            relpath = "src/ai_ui/native_ai.js"
            full = Path(tmp) / relpath
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("// js body", encoding="utf-8")
            with override_settings(STATIC_ROOT=str(tmp)):
                version = context_processors._file_asset_version(relpath, "fb")
        # 12 hex-символов, не равны fallback.
        self.assertNotEqual(version, "fb")
        self.assertEqual(len(version), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in version))

    def test_hash_changes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            relpath = "src/ai_ui/native_ai.js"
            full = Path(tmp) / relpath
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("first", encoding="utf-8")
            with override_settings(STATIC_ROOT=str(tmp)):
                version_a = context_processors._file_asset_version(relpath, "fb")
            # Меняем mtime и содержимое, чистим кэш.
            os.utime(full, (1, 1))
            context_processors.native_ai_asset_version.cache_clear()
            full.write_text("second-longer", encoding="utf-8")
            with override_settings(STATIC_ROOT=str(tmp)):
                version_b = context_processors._file_asset_version(relpath, "fb")
        self.assertNotEqual(version_a, version_b)


class AssetVersionFunctionsTests(TestCase):
    """Открытые функции ``native_ai_asset_version`` и др. — smoke-тест."""

    def setUp(self):
        context_processors.native_ai_asset_version.cache_clear()
        context_processors.native_ai_css_version.cache_clear()
        context_processors.copilotkit_asset_version.cache_clear()
        context_processors.copilotkit_css_version.cache_clear()

    def test_native_ai_version_is_nonempty_string(self):
        version = context_processors.native_ai_asset_version()
        self.assertIsInstance(version, str)
        self.assertGreater(len(version), 0)

    def test_native_ai_css_version_is_nonempty_string(self):
        version = context_processors.native_ai_css_version()
        self.assertIsInstance(version, str)
        self.assertGreater(len(version), 0)

    def test_copilotkit_version_is_nonempty_string(self):
        version = context_processors.copilotkit_asset_version()
        self.assertIsInstance(version, str)
        self.assertGreater(len(version), 0)


class SidebarAiChatDispatcherTests(TestCase):
    """Контекст-процессор возвращает корректные флаги под каждый драйвер."""

    databases = {"default", "chat", "knowledge_meta", "analytics_control"}

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="dispatcher-cp", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.user.groups.add(manager_group)

    def _context(self, settings_kwargs: dict):
        request = self.factory.get("/")
        request.user = self.user
        with override_settings(**settings_kwargs):
            return sidebar_ai_chat(request)

    def test_native_driver_enables_only_native_branch(self):
        ctx = self._context({"LOCAL_BUSINESS_AI_UI_DRIVER": "native"})
        self.assertTrue(ctx["native_ai_ui_enabled"])
        self.assertFalse(ctx["copilotkit_enabled"])
        self.assertEqual(ctx["ai_ui_driver"], DRIVER_NATIVE)
        self.assertTrue(ctx["show_sidebar_ai_chat"])

    def test_legacy_driver_disables_both_native_and_copilotkit(self):
        ctx = self._context({"LOCAL_BUSINESS_AI_UI_DRIVER": "legacy"})
        self.assertFalse(ctx["native_ai_ui_enabled"])
        self.assertFalse(ctx["copilotkit_enabled"])
        self.assertEqual(ctx["ai_ui_driver"], DRIVER_LEGACY)
        # ``show_sidebar_ai_chat`` всё равно True для аутентифицированного
        # пользователя — это контейнер для HTMX-чата.
        self.assertTrue(ctx["show_sidebar_ai_chat"])

    def test_copilotkit_driver_enables_only_copilotkit_branch(self):
        ctx = self._context(
            {
                "LOCAL_BUSINESS_AI_UI_DRIVER": "copilotkit",
                "LOCAL_BUSINESS_COPILOTKIT_ENABLED": True,
            }
        )
        self.assertTrue(ctx["copilotkit_enabled"])
        self.assertFalse(ctx["native_ai_ui_enabled"])
        self.assertEqual(ctx["ai_ui_driver"], DRIVER_COPILOTKIT)
        self.assertTrue(ctx["show_sidebar_ai_chat"])

    def test_context_includes_both_native_and_copilotkit_versions(self):
        ctx = self._context({"LOCAL_BUSINESS_AI_UI_DRIVER": "native"})
        # Оба варианта версий должны быть в контексте: base.html рендерит
        # CSS- и JS-ссылку, не дёргая context_processors ещё раз.
        for key in (
            "native_ai_asset_version",
            "native_ai_css_version",
            "copilotkit_asset_version",
            "copilotkit_css_version",
        ):
            self.assertIn(key, ctx)
            self.assertIsInstance(ctx[key], str)
            self.assertGreater(len(ctx[key]), 0)
