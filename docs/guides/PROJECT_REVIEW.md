# Ревью проекта Local Business Suite

Дата: 2026-05-12

---

## Исправленные проблемы (низкий приоритет)

### #43. ~~`unique_together` устарел — нужен `UniqueConstraint`~~ ✅
Заменён на `models.UniqueConstraint(fields=["board", "code"], name="unique_board_code")` в `apps/workorders/models.py`. Создана миграция `0012`.

### #44. ~~Пустой `accounts/signals.py` — обе ветки `pass`~~ ✅
Мёртвый signal handler удалён. Файл оставлен с docstring-заглушкой.

### #45. ~~Custom User не зарегистрирован в admin~~ ✅
Зарегистрирован `accounts.User` через `CustomUserAdmin(UserAdmin)` в `apps/accounts/admin.py`.

### #46. ~~Нет кастомных `handler403`, `handler404`, `handler500`~~ ✅
Добавлены обработчики в `config/views.py` + `handler400`. Подключены в `config/urls.py`. Созданы шаблоны `templates/{400,403,404,500}.html`.

### #47. ~~Stray `{% endblock %}` — `ai/chat_detail.html:655`~~ ✅
Лишний `{% endblock %}` удалён.

### #48. ~~`FORCE_SCRIPT_NAME` определён дважды — `settings.py:82,103`~~ ✅
Дублирующее присвоение удалено. Оставлена единственная строка в секции IIS/FastCGI.

### #49. ~~Отсутствует LOGGING-конфигурация~~ ✅
Добавлен блок `LOGGING` в `settings.py`: console + RotatingFileHandler (10MB, 5 бэкапов), логгеры для `django`, `apps`, `services`. Создан каталог `logs/`.

### #53. ~~`workorders.rate` не валидирует диапазон оценки~~ ✅
Добавлена валидация `1 ≤ rating ≤ 5` в `apps/ai/services.py:rate_workorder_for_actor()` с `ValidationError`.

### #55. ~~Нет ограничения размера prompt в стриминге~~ ✅
Добавлена обрезка prompt до 10000 символов в `apps/ai/views.py:AIChatMessageStreamView.get()`.

### #56. ~~Схема `integration_registry.schema.json` слишком permissive~~ ✅
Схема усилена: `required` поля (`code`, `name`, `owner`, `transport`, `mode`, `direction`, `status`), `enum` для `transport`, `mode`, `direction`, `status`, `source_of_truth`, вложенная схема для `payloads`. Существующий `registry.json` проходит валидацию.

---

## КРИТИЧЕСКИЕ проблемы

### 1. LDAP-авторизация использует неправильную модель User
**`apps/accounts/ldap_backend.py:8,81`** — импортирует `from django.contrib.auth.models import User` вместо `get_user_model()`. LDAP создаёт/ищет записи в `auth_user`, а не в кастомной `accounts.User`. При наличии полей, которые есть только в кастомной модели, это вызовет крах.

### 2. SECRET_KEY с предсказуемым fallback
**`config/settings.py:29`** — `SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-key")`. Если переменная не задана, приложение тихо работает с известным ключом. В продакшене позволяет подделывать сессии и токены.

### 3. DEBUG=True по умолчанию + wildcard ALLOWED_HOSTS
**`config/settings.py:30,43-44`** — если `DJANGO_DEBUG` не задана, DEBUG=True, а `ALLOWED_HOSTS = ["*"]`. Развёрнутое приложение без env-переменной открыто для Host-header атак и отдаёт детальные страницы ошибок.

### 4. Безопасность сессий/CSRF отключена
**`config/settings.py:104-106`** — `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` хардкоднуты в `False`. Даже в продакшене куки передаются по голому HTTP.

### 5. XSS через localStorage-избранное
**`templates/base.html:141-147`** — `renderFavorites()` вставляет данные из `localStorage` через `innerHTML` без экранирования. `f.url`, `f.label`, `f.icon` подставляются как есть. Компрометация localStorage = выполнение произвольного JS.

### 6. AI-шлюз: пользователь определяется из тела запроса
**`apps/ai/views.py:297-308`, `apps/ai/services.py:31-37`** — эндпоинты `AIToolExecuteView` и `AIToolConfirmView` получают `actor` из POST-тела. Единственная защита — статический токен `X-AI-Gateway-Token`. Утечка токена = полный импрессонификационный доступ от имени любого пользователя.

### 7. AI-шлюз: токен gateway с известным fallback
**`config/settings.py:251-252`** — `LOCAL_BUSINESS_AI_GATEWAY_TOKEN` по умолчанию `"dev-ai-gateway-token"`. Без env-переменной шлюз открыт.

### 8. Контейнер работает от root
**`Dockerfile` (оба)** — нет директивы `USER`. Контейнер запускается от root.

### 9. curl в healthcheck, но curl нет в образе
**`docker-compose.prod.yml:14`** — `curl -f http://localhost:8000/health/` не сработает в `python:3.12-slim`, где нет `curl`. Healthcheck всегда падает.

### 10. HTTPS отключён в Caddy
**`Caddyfile:1-2`** — `auto_https off`, слушается только `:80`. Весь трафик — plaintext.

---

## ВЫСОКИЙ приоритет

### 11. SQLite PRAGMA не применяются
**`config/settings.py:113-118`** — `init_command` — параметр MySQL. SQLite-бэкенд его игнорирует. PRAGMA `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000` никогда не выполняются.

### 12. Debug-view доступна без авторизации
**`apps/core/urls.py:17`, `apps/core/debug_views.py`** — `/debug-request/` отдаёт заголовки и env-переменные без логина.

### 13. PathInfoDebugMiddleware пишет в Windows-путь на Linux
**`apps/core/middleware.py:9`** — `C:\\inetpub\\portal\\debug_path.log`. На Linux-сервере этот путь невалиден.

### 14. AI-стриминг: innerHTML без санитизации во время потока
**`ai/chat_detail.html:583`** — `assistantContentDiv.innerHTML = accumulatedContent.replace(...)`. DOMPurify применяется только после завершения стрима. В процессе — XSS-окно.

### 15. Timing attack на токен шлюза
**`apps/ai/views.py:292-294`** — `gateway_token != expected_token` — обычное строковое сравнение. Нужно `hmac.compare_digest()`.

### 16. PendingAction без проверки actor
**`apps/ai/tooling.py:350`** — подтверждение действия ищется только по token. Любой, кто знает token, может подтвердить/отменить, независимо от того, кто инициировал.

### 17. PendingAction без срока годности
**`apps/ai/models.py:54-83`** — нет поля `expires_at`. Токены живут бесконечно.

### 18. `update_user_for_actor` может снять superuser-статус и группы
**`apps/ai/services.py:476-485`** — `.set(groups)` заменяет ВСЕ группы пользователя, а `is_active` можно переключить на `False` для любого, включая последнего superuser.

### 19. `sync_user_groups` только добавляет группы, никогда не убирает
**`apps/accounts/ldap_backend.py:306`** — `user.groups.add(*groups)`. Устаревшие группы не удаляются.

### 20. Нет rate limiting на AI-эндпоинтах
Ни на шлюз, ни на стриминг-чат нет ограничения частоты запросов.

### 21. Health-endpoint утекает конфигурацию
**`apps/core/health_views.py`, `services/agent_runtime/app.py:28-36`** — отдаёт модель, gateway URL, статус API-ключа.

### 22. Ролевые правила пишутся на диск без атомарности
**`apps/ai/services.py:419`, `apps/core/views.py:122-123`** — `write_text()` не атомарно. При многопроцессорном деплое — гонка записи + рассинхрон процессов.

### 23. deploy.sh содержит IP продакшн-сервера
**`scripts/deploy.sh:10`** — `VPS_HOST="${VPS_HOST:-188.120.246.243}"`.

### 24. gevent + SQLite — известная проблема
**`docker/entrypoint.prod.sh:10`** — `--worker-class gevent` + SQLite может вызывать дедлоки и повреждение БД при конкурентной записи.

---

## СРЕДНИЙ приоритет

### 25. Мёртвый код: `User.get_ou_path()` ссылается на удалённое поле
**`apps/accounts/models.py:33-37`** — `self.organizational_unit` удалён миграцией `0003`.

### 26. access-инструменты — мёртвый код в шлюзе
`config/ai/tools.json` содержит 5 `access.*` инструментов, но `tool_definitions.py` их не определяет. Проверка в `tooling.py:148-150` их отклоняет. `sync_ai_tool_registry` перезатрёт их.

### 27. `skills_service.py:2` — `from pathlib import settings` — некорректный импорт
Затеняется `from django.conf import settings`, но должен быть удалён.

### 28. Bare `except:` в AI-стриминге
**`apps/ai/views.py:236`** — глотает все исключения, включая `KeyboardInterrupt` и `SystemExit`.

### 29. WaitingList — нет ролевого контроля
Все view доступны любому аутентифицированному пользователю.

### 30. N+1 запросы
- `Department.full_name` — рекурсивный self-join
- `Department.descendant_ids()` — загружает ВСЕ отделы на каждый вызов
- `WorkOrderBoardView` — `quick_transition_choices_for()` и `can_confirm_closure()` на каждый объект
- `MedicalDeviceListView` — нет `select_related("department")`

### 31. Отсутствующие db_index
- `WorkOrder.status`, `WorkOrder.resolved_at`
- `PendingAction.tool_code`, `PendingAction.status`
- `AgentActionLog.tool_code`, `AgentActionLog.action_kind`
- `WaitingListEntry.status`, `WaitingListEntry.priority_cito`
- `MedicalDevice.operational_status`, `MedicalDevice.is_archived`

### 32. Дублирование CSS в `app.css`
11+ правил определены дважды с разными значениями. Второе определение всегда побеждает. ~1800 строк, из которых существенная часть — мёртвый CSS.

### 33. Неопределённая CSS-переменная `--brand`
Используется в 8 местах, но не определена в `:root`.

### 34. 480 строк инлайн-JS в `ai/chat_detail.html`
Должно быть вынесено в отдельный файл.

### 35. Дублирование JS: маски телефона/даты — 3 копии
`waiting_list/dashboard.html`, `waiting_list/entry_form.html`, `waiting_list/partials/entry_form_partial.html`.

### 36. Hardcoded URLs в JS
`ai/chat_detail.html:636` — `/ai/chat/.../delete/`, `workorders/board.html:242` — `/workorders/${workorderId}/board-move/`.

### 37. CDN-зависимости без SRI
`ai/chat_detail.html:162-170` — 4 внешних скрипта без Subresource Integrity.

### 38. Двойная загрузка Tailwind
`ai/chat_detail.html:162,164` — Tailwind CSS подключён дважды.

### 39. `analytics/dashboard` использует `can_manage_inventory` как привилегию
Семантически неверно — аналитика и управление инвентарём — разные функции.

### 40. `.env.example` не документирует 13 переменных
Отсутствуют: `AD_EMAIL_DOMAIN_OVERRIDE`, `DJANGO_INTERNAL_ALLOWED_HOSTS`, `LOCAL_BUSINESS_AI_MODELS_FILE`, и ещё 10 конфигурационных переменных.

### 41. Нет CORS-конфигурации
`django-cors-headers` не установлен. Кросс-доменные запросы к AI-рантайму или из фронтенда будут блокированы.

### 42. `docker-compose.yml` — нет healthcheck, нет restart-политики, порты на 0.0.0.0

---

## НИЗКИЙ приоритет

### 50. ~~Requirements.txt — диапазоны вместо pinned версий, нет requirements.lock~~ ✅
Зависимости pinned до точных версий. Создан `requirements.lock` с полным деревом транзитивных зависимостей.

### 51. ~~MCP-сервер не включает новые инструменты (`workorders.confirm_closure`, `workorders.rate`, `inventory.devices.*`, `analytics.summary`)~~ ✅
Добавлены MCP-инструменты: `workorders_confirm_closure`, `workorders_rate`, `inventory_devices_create`, `inventory_devices_update`, `inventory_devices_archive`, `analytics_summary` в `mcp_server.py`.

### 52. ~~`stream_agent` не обрабатывает `activate_skill` — система промптов фиксирована~~ ✅
`stream_agent` теперь загружает каталог навыков и динамически обновляет системный промпт при успешном `activate_skill`, как и `run_agent`.

### 54. ~~Streaming GET-эндпоинт передаёт prompt в query string — может логироваться~~ ✅
`AIChatMessageStreamView` конвертирован из GET в POST. Prompt и model_id передаются в JSON-теле запроса. JS-клиент обновлён для `fetch` с `method: 'POST'` и JSON body.

---

## Что сделано хорошо

- Все 27 `<form>` содержат `{% csrf_token %}`
- Нет ни одного использования фильтра `|safe` в шаблонах
- `<html lang="ru">` — корректно
- `staticfiles/` в `.gitignore`
- WSGI-конфигурация стандартная
- Миграции последовательные, кастомный User-модель