# Приёмка: 09-legacy-ai-ui-driver-removal

Дата: 2026-07-07.
Роли: исполнитель — субагент (Sonnet); независимая проверка — не требуется
(`independent_verification: false`, риск medium); gating-проверка, code-review и
приёмка — агент-оркестратор.

## Вердикт

**Принят с расширением scope оркестратором-одобренным.** Реализация ADR-0032
корректна; агент дополнительно удалил ставший мёртвым HTMX-сайдбар-чат (обосновано),
затронув 2 файла вне буквального write_scope — проверено, безопасно.

## Gating-проверка (выполнена оркестратором до запуска)

- `deployments/test-host/.env` — настройки `LOCAL_BUSINESS_AI_UI_DRIVER` НЕТ
  (→ default native); остаточного `driver=legacy` в deployment-silo нет. ADR-0032
  Accepted (sign-off владельца). Условие implementation_notes #27 выполнено.
  (Прочие приватные silo вне рабочей копии; владелец о переходе на native
  осведомлён через принятие ADR-0032.)

## Что проверено (code-review оркестратором)

- **settings.py:** `_validate_ai_ui_driver()` — `legacy` → `ImproperlyConfigured`
  с явным сообщением о переходе на native/copilotkit; прочие невалидные →
  `{copilotkit, native}`. Проверено вручную:
  `LOCAL_BUSINESS_AI_UI_DRIVER=legacy manage.py check` падает на импорте с нужным
  текстом. Дефолт — native (copilotkit только при `COPILOTKIT_ENABLED`).
- **drivers.py:** `DRIVER_LEGACY` удалён, `VALID_AI_UI_DRIVERS={copilotkit,native}`,
  все фолбэки (`normalize_ai_ui_driver`, `authenticated_ai_ui_driver`) → native.
- **Удаление мёртвого HTMX-чата (расширение scope, обосновано):** после запрета
  legacy ветка `{% elif show_sidebar_ai_chat %}` в `templates/base.html` стала
  недостижима (аутентифицированный пользователь всегда либо copilotkit, либо
  native). Удалены: `AISidebarChatView`/`AISidebarChatClearView` (views.py),
  их маршруты (`apps/ai/urls.py` — вне scope), `templates/ai/partials/sidebar_chat.html`,
  `static/src/js/sidebar_chat.js`, ветка + `<script>` в `templates/base.html`
  (вне scope), флаг `show_sidebar_ai_chat` (context_processors).
  **Обоснование правки base.html/urls.py:** оставить `{% static 'sidebar_chat.js' %}`
  на удалённый файл уронило бы КАЖДУЮ страницу в production (whitenoise
  `CompressedManifestStaticFilesStorage` падает на отсутствующем ассете).
- **copilotkit НЕ затронут (non-goal соблюдён):** его ветка идёт ПЕРВОЙ
  (`{% if copilotkit_enabled %}`) и монтируется в собственный
  `#copilotkit-sidebar-root` (`static/src/copilotkit/main.jsx:218`), а не в
  `#sidebar-ai-chat`. Проверено оркестратором лично.
- **Нет dangling-ссылок:** grep по `show_sidebar_ai_chat|sidebar_chat.js|
  sidebar_chat.html|AISidebarChatView` — 0.
- **Тесты:** `test_legacy_driver_disables...` заменён на
  `test_legacy_ai_ui_driver_raises_improperly_configured_with_native_hint`; удалены
  2 теста удалённого legacy-view (эквивалентное покрытие native есть).
- **Ловушки соблюдены:** `migrate_legacy_chat_db.py` (SQLite-legacy) не тронут;
  ассеты удалялись по функции, а не по слову.
- **Доки:** `.env.example` (убран дубль `=legacy`), `AI_UI_PROTOCOL_OPERATIONS.md`,
  `AI_UI_PROTOCOL_DEPLOYMENT.md`, `COPILOTKIT_AG_UI_DEPLOYMENT.md`, ADR-0028
  (примечание про ADR-0032). Агент также исправил `COPILOTKIT_AG_UI_OPERATIONS.md`
  (вне scope): его rollback-runbook предписывал `driver=legacy`, что теперь уронило
  бы Django — реальная эксплуатационная ловушка. Обоснованно.

## Acceptance-проверки

- `.venv/bin/python manage.py test apps.ai.tests apps.ai.tests_context_processors`
  → **109 tests, OK** (+ полный `apps.ai` OK, исполнитель).
- Оркестратор дополнительно прогнал широкий рендер-регресс
  `apps.core.tests apps.workorders.tests apps.ai` (base.html — глобальный шаблон).
- `.venv/bin/python manage.py check` → без ошибок; `LOCAL_BUSINESS_AI_UI_DRIVER=legacy
  ... check` → `ImproperlyConfigured` с сообщением про native.
- `makemigrations --check` → без изменений.
- grep UI-driver-legacy по `apps/ai config/settings.py .env.example` → остаются
  только исключённый `migrate_legacy_chat_db` и намеренный код/тест/комментарий
  отклонения.

## Не выполнено / отложено

- **E2E НЕ прогонялся** (нет живого сервера/браузера в окружении) — честно отмечено;
  `sidebar_ai_context.spec.ts` (100% legacy-gated) удалён, дефолты в
  `native_ai_ui.spec.ts`/`copilotkit_sidebar.spec.ts` исправлены с legacy на native;
  `playwright --list` подтвердил парсинг. E2E-прогон — на подходящем окружении.
- **Doc-debt (в рекомендацию):** `docs/guides/AI_SIDEBAR_CHAT.md` (общая инфра
  ADR-0019, вне scope) содержит одну устаревшую ссылку на удалённый spec — кандидат
  на подчистку пакетом 12 или отдельной doc-задачей. README/DEPLOYMENT «legacy»
  относятся к SQLite, не к UI-драйверу — оставлены верно.
