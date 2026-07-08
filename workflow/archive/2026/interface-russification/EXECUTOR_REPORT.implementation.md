# Executor Report: русификация интерфейса

Дата: 2026-05-29

## Выполнено

- Созданы ADR, активный план, руководство и workflow-блок для русификации UI и будущей локализации.
- Переведены основные пользовательские поверхности: базовый шаблон, меню, ИИ-чат, ИИ-центр, ревью памяти, центр настроек, аналитика, доска заявок, лист ожидания, инвентарь и формы.
- Переведены JS-сообщения, Django `verbose_name`, `help_text`, labels, `TextChoices`, настройки и серверные сообщения, которые попадают в UI.
- Переведены описания ИИ-инструментов и типов задач в `contracts/ai/tools.json`, `contracts/ai/task_types.json` и рабочих копиях `data/contracts/ai/`.
- Сгенерированы label-only миграции для изменений человекочитаемых подписей.
- Оставлены без перевода машинные ключи, tool id, JSON-ключи, URL, CSS/JS id и технические аббревиатуры.

## Проверки

- `.venv/bin/python manage.py check` — OK.
- `.venv/bin/python manage.py validate_architecture_contracts` — OK.
- `.venv/bin/python manage.py makemigrations --check --dry-run` — OK.
- `.venv/bin/python manage.py test apps.core.tests apps.ai.tests apps.memory.tests apps.settings_center.tests apps.workorders.tests apps.waiting_list.tests apps.inventory.tests --keepdb` — 242 tests OK.
- `.venv/bin/python manage.py test apps.ai.tests --keepdb` после перевода контрактов задач — 70 tests OK.
- `E2E_BASE_URL=http://127.0.0.1:8000 E2E_USERNAME=chief_manager E2E_PASSWORD=... npm run test:e2e -- --project=chromium` — 7 tests OK.
- Видимый текст ключевых страниц просканирован; английские UI-слова из контрольного списка не найдены.
- Скриншоты ключевых страниц сохранены в `.local/playwright/russification-screenshots/`.
- `make gen-struct` — OK, `PROJECT_STRUCTURE.yaml` обновлен.
- `git diff --check` — OK.

## Остаточные ограничения

- Полноценная многоязычная локализация, выбор языка и `gettext`-каталоги отложены в отдельный этап.
- Исторические пользовательские данные и импортированные названия не переводятся.
- Внешние продуктовые имена и технические сокращения остаются как есть.
