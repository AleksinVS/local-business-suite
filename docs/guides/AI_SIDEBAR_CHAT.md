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

## Открытие правой панели из ИИ-чата

ИИ может открыть объект справа через tool `ui.open_right_panel`. Инструмент принимает только безопасные идентификаторы:

```json
{
  "source_code": "workorders",
  "object_type": "workorder",
  "object_id": "123",
  "mode": "view"
}
```

Модель не передает URL и HTML. Django находит зарегистрированный `RightPanelProvider`, проверяет доступ, строит локальный `htmx_url` и возвращает браузеру `ui_command`. Браузерный мост `LocalBusinessRightPanel` загружает существующий partial в общий правый сайдбар и обновляет `PageContextEnvelope`.

Поддержанные MVP-провайдеры:

- `workorders / workorder`;
- `waiting_list / waiting_list_entry`.

## Module AI skills

Открытие объектов из ИИ-чата больше не зашито в `services/agent_runtime/graph.py`.
Модули регистрируют workflow-инструкции через `apps.core.ai_skills`:

- `workorders.open_right_panel` описывает, как открыть заявку по номеру или текущему контексту;
- `waiting_list.open_right_panel` описывает, как открыть запись листа ожидания;
- `ai.skill_creator` помогает администратору создать runtime skill.

Agent runtime получает каталог skills через Django gateway, выбирает подходящий skill по `description` и `trigger_examples`, вызывает `activate_skill`, а затем работает обычными tools. Для открытия справа skill всегда заканчивается вызовом `ui.open_right_panel`; права и URL по-прежнему проверяет Django.

Чтобы подключить новый модуль:

1. Добавьте `apps/<module>/right_panel.py` с provider для своего `source_code/object_type`.
2. В `can_open()` используйте доменные selectors/policies.
3. В `build_panel()` верните `RightPanelDescriptor` с URL на существующий HTMX detail partial.
4. Зарегистрируйте provider в `AppConfig.ready()`.
5. Добавьте `data-ai-context` в detail partial и resolver в `apps.ai.page_context.resolve_page_context()`.
6. Добавьте `apps/<module>/ai_skills.py` и зарегистрируйте module skill в `AppConfig.ready()`.
7. Покройте provider и skill unit-тестом и e2e-сценарием открытия из sidebar-чата.

Для MVP поддерживается только `mode=view`. Редактирование, создание, удаление, комментарии и переходы статусов остаются отдельными доменными инструментами с прежними проверками прав и подтверждением для опасных действий.

Операторские правила создания runtime skills описаны в `docs/guides/AI_SKILLS_OPERATIONS.md`.

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

Встроенный sidebar-чат можно очистить кнопкой в заголовке панели. Очистка удаляет сообщения только текущей `sidebar`-сессии и сбрасывает `sidebar_summary`; обычные full-page чаты не затрагиваются.

## Проверка

Базовые команды:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.ai.tests apps.workorders.tests apps.waiting_list.tests
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
