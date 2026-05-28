# Контекстный ИИ-чат в левой панели

Статус: implemented MVP.

Дата: 2026-05-28.

Связанные документы:

- `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`
- `docs/planning/active/context-aware-sidebar-ai-chat.md`
- `workflow/active/context-aware-sidebar-ai-chat/`

## Что изменилось

Главное меню перенесено в выпадающий список `Все функции` в верхнем левом блоке. Освобожденная левая панель показывает встроенный ИИ-чат на рабочих страницах.

Встроенный чат использует отдельную `sidebar`-сессию пользователя. Обычные full-page сессии не смешиваются с ней. Из панели можно открыть текущую sidebar-сессию на полной странице чата через ссылку `Открыть полный чат`.

Исключение: на странице `AI чат` левая панель не загружает второй встроенный чат. Там она показывает список чат-сессий, а центральная область целиком отдана текущему диалогу. Это сохраняет один активный чат на экране и убирает вложенную навигацию внутри центральной части.

## Контекст окна

Браузер собирает безопасный `PageContextEnvelope` из `data-ai-context` на странице и активных частях интерфейса. Сейчас:

- все страницы получают базовый route context: `module` и `view`;
- доска заявок получает подробный контекст фильтров;
- открытая карточка заявки в правой панели становится `selection` с `source_code=workorders`, `object_type=workorder`, `object_id=<pk>`.

Сервер не доверяет клиентскому `object_id` и `capabilities`. Для `workorders` выбранная заявка заново проверяется через `visible_workorders_queryset(user)`, а права пересчитываются через доменные policies.

Сообщение чата хранит `context_snapshot_id`, `window_id`, `context_version`, `context_hash` и краткий безопасный digest. Инструмент `ui.get_current_context` читает snapshot, привязанный к сообщению, а не последний snapshot вкладки.

## Правила для новых модулей

Чтобы модуль дал ИИ более точный контекст, добавьте на рабочий контейнер `data-ai-context` с JSON:

```html
<div data-ai-context='{"schema_version":"1","page":{"module":"inventory","view":"detail"},"selection":{"source_code":"inventory","object_type":"device","object_id":"123"}}'>
```

Клиентский контекст должен содержать только безопасные идентификаторы и короткий display. Не передавайте полный HTML, свободный текст карточек, секреты или PII.

После добавления selection нужно добавить server-side resolver в `apps.ai.page_context.resolve_page_context()`. Resolver обязан проверять видимость объекта для пользователя и возвращать только безопасную сводку.

## Настройки

Общие настройки полной страницы и sidebar-чата лежат в контракте:

- default: `contracts/ai/chat_settings.json`;
- runtime: `data/contracts/ai/chat_settings.json`;
- Settings Center id: `ai.contract.chat_settings`.

Эффективные настройки строятся как `defaults` плюс override из `surfaces.full_page` или `surfaces.sidebar`.

Ключевые параметры:

- `recent_message_limit`: сколько последних сообщений передавать в prompt;
- `summary_enabled`: включена ли суммаризация старой части истории;
- `summary_trigger_messages`: порог compact;
- `max_prompt_chars`: максимальная длина пользовательского ввода;
- `context_tool_enabled`: доступен ли `ui.get_current_context`.

Для sidebar по умолчанию `recent_message_limit=8`.

## Суммаризация

Sidebar-сессия компактируется после новых сообщений: последние N сообщений остаются обычной историей, более старые сообщения сжимаются в `ChatSession.metadata.sidebar_summary`.

`sidebar_summary` считается чувствительным runtime state:

- не отправляется в память автоматически;
- не пишется в обычные audit payload/logs как raw text;
- хранит provenance через диапазон/source message ids;
- проходит masking перед сохранением.

UI просмотра или ручной перегенерации summary в MVP нет.

## Проверка

Базовые команды:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests apps.workorders.tests
python -m unittest services.agent_runtime.tests.test_normalization
```

E2E:

```bash
E2E_BASE_URL=http://127.0.0.1:8001 \
E2E_USERNAME=<user> \
E2E_PASSWORD=<password> \
npm run test:e2e -- --project=chromium
```

Тест `scripts/e2e/tests/sidebar_ai_context.spec.ts` проверяет загрузку меню `Все функции`, встроенного чата и обновление контекста при открытии карточки заявки.
