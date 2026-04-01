# Local Business Suite: Handoff For Next Agent

Этот документ нужен как стартовая точка для нового ИИ-агента. Его цель: дать рабочее понимание проекта без обязательного сканирования всей кодовой базы.

## 1. Назначение проекта

`local-business-suite` это Django-монорепозиторий для внутренних бизнес-приложений.

Текущий MVP фокусируется на одном приложении:

- общей канбан-доске заявок на техническое обслуживание и ремонты;
- справочнике медицинских изделий;
- комментариях, вложениях, оценке результата и подтверждении закрытия;
- базовой аналитике;
- локальной auth-модели с ролями `customer`, `technician`, `manager`.

Frontend построен на:

- Django Templates
- HTMX
- CSS без отдельного frontend bundler

Backend:

- Django 5.2
- SQLite
- WhiteNoise
- Gunicorn

## 2. Текущее состояние проекта

Проект не пустой и не bootstrap-only. Это уже рабочий вертикальный срез.

Что уже реализовано:

- базовая инфраструктура Django-проекта;
- локальная аутентификация;
- seed стартовых ролей;
- CRUD и архивирование медизделий;
- заявки с workflow, аудитом переходов, комментариями и вложениями;
- role-based policy layer;
- HTMX UX для доски;
- параметрические колонки канбана;
- inline rename заголовков колонок;
- базовая аналитика по заявкам;
- автоматические тесты.

Текущее дерево коммитов по смысловым этапам:

- `85dad33` Initial Django MVP scaffold
- `1b0cd41` Add HTMX interactions for work orders
- `143501b` Add analytics dashboard
- `5f7cc52` Add closure confirmation and rating workflow
- `07c0997` Validate and preview work order attachments
- `65b6acb` Add inventory update and archive flow
- `7e4fb0f` Enforce role-based work order policies
- `306bfb0` Improve work order board UX
- `c687416` Add inline actions to work order board
- `a3ca2b6` Make kanban columns configurable
- `825a238` Refine kanban column rename UX

## 3. Главные каталоги

### Корень проекта

- `manage.py`
- `requirements.txt`
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `PROJECT_HANDOFF.md`

### Приложения

- `apps/core`
  Базовый dashboard и общие entry views.
- `apps/accounts`
  Пока только seed ролей и подготовка под auth layer.
- `apps/inventory`
  Медицинские изделия.
- `apps/workorders`
  Основное доменное приложение: заявки, workflow, канбан, policy layer, HTMX UX.
- `apps/analytics`
  Базовые агрегаты по заявкам.

### Конфигурация

- `config/settings.py`
- `config/urls.py`
- `config/wsgi.py`
- `config/asgi.py`

### Шаблоны

- `templates/base.html`
- `templates/core/*`
- `templates/inventory/*`
- `templates/workorders/*`
- `templates/workorders/partials/*`
- `templates/analytics/*`

### Данные

- `db/main_vault.sqlite3`
- `media/`
- `static/`
- `staticfiles/` после `collectstatic`

## 4. Архитектура приложения

### 4.1 Backend style

Архитектура серверная и довольно простая:

- модели в `models.py`;
- role/policy decisions в `apps/workorders/policies.py`;
- workflow actions в `apps/workorders/services.py`;
- request-level orchestration во `views.py`;
- partial UI через HTMX.

Главный принцип: не доверять шаблону. Важные ограничения реализованы на сервере.

### 4.2 AI layer

В проекте теперь есть отдельный AI-контур поверх Django domain layer.

Ключевые части:

- `apps/ai`
  Django-side gateway, chat surface, action audit, confirmation flow.
- `services/agent_runtime`
  Отдельный runtime/orchestration слой.
- `config/ai/tools.json`
  Генерируемый registry tools.
- `config/ai/task_types.json`
  Декларативный task type catalog.

Что важно понимать:

- source of truth для tool definitions теперь code-first:
  `apps/ai/tool_definitions.py`
- `config/ai/tools.json` синхронизируется из кода через:
  `python manage.py sync_ai_tool_registry`
- write-tools не должны исполняться напрямую без confirmation flow;
- подтверждение write-path сейчас реализовано через `PendingAction`;
- executable task-type contracts уже существуют для всех текущих task types из `config/ai/task_types.json`;
- contract drift проверяется через:
  `python manage.py validate_architecture_contracts`

Для короткого agent protocol и обязательных execution rules теперь есть отдельный файл:

- `AGENTS.md`

### 4.3 Data model

#### Inventory

Файл:

- `apps/inventory/models.py`

Основная сущность:

- `MedicalDevice`

Ключевые поля:

- `name`
- `manufacturer`
- `model`
- `serial_number`
- `inventory_number`
- `department`
- `location`
- `operational_status`
- `commissioned_at`
- `notes`
- `is_archived`
- `archived_at`

Удаление заменено мягкой архивацией.

#### Workorders

Файл:

- `apps/workorders/models.py`

Основные сущности:

- `WorkOrder`
- `WorkOrderComment`
- `WorkOrderAttachment`
- `WorkOrderTransitionLog`
- `KanbanColumnConfig`

`WorkOrder`:

- бизнес-номер `number`
- `title`
- `description`
- `department`
- `priority`
- `status`
- `rating`
- `closure_confirmed`
- `closure_confirmed_at`
- `author`
- `assignee`
- `device`
- `created_at`
- `updated_at`
- `resolved_at`
- `closed_at`

`WorkOrderAttachment`:

- файл хранится в `media/workorders/...`
- есть content type
- есть helper’ы `is_image` и `filename`

`KanbanColumnConfig`:

- `code`
- `title`
- `position`
- `statuses` через `JSONField`

Это источник правды для колонок доски.

Текущая инициализация колонок:

- `new` -> `Новые` -> `["new"]`
- `in_progress` -> `В работе` -> `["accepted", "in_progress", "on_hold"]`
- `done` -> `Выполнены` -> `["resolved"]`
- `archive` -> `Архив` -> `["closed", "cancelled"]`

Создаются миграцией:

- `apps/workorders/migrations/0003_kanbancolumnconfig.py`

## 5. Workflow заявок

Файл:

- `apps/workorders/policies.py`
- `apps/workorders/services.py`

Статусы `WorkOrderStatus`:

- `new`
- `accepted`
- `in_progress`
- `on_hold`
- `resolved`
- `closed`
- `cancelled`

Ключевая доменная логика:

- `resolved` и `closed` это разные состояния;
- `resolved` означает техническое выполнение;
- `closed` означает подтвержденное закрытие;
- закрытие подтверждается отдельно;
- `rating` доступен только после `closed`.

### Transition rules

Технический переход управляется через:

- `can_transition(...)`
- `transition_workorder(...)`

Подтверждение закрытия:

- `can_confirm_closure(...)`
- `confirm_closure(...)`

## 6. Role model

Текущие роли:

- `customer`
- `technician`
- `manager`

Начальные группы создаются management command:

- `apps/accounts/management/commands/seed_roles.py`

### Поведение ролей

#### customer

- видит заявки;
- может создавать заявки;
- может редактировать свои заявки;
- может комментировать;
- может подтверждать закрытие;
- может ставить рейтинг;
- не должен выполнять технические переходы типа `accepted/in_progress/resolved`.

#### technician

- видит назначенные ему заявки, заявки без исполнителя и свои;
- может выполнять технические переходы;
- может комментировать;
- может загружать вложения;
- не может подтверждать закрытие;
- не может ставить рейтинг;
- не должен администрировать колонки/справочник.

#### manager

- видит все;
- может управлять справочником;
- может управлять всеми статусами;
- может редактировать колонки доски;
- имеет доступ к аналитике.

## 7. Главные серверные точки

### Settings

Файл:

- `config/settings.py`

Важно:

- SQLite база: `db/main_vault.sqlite3`
- используется WhiteNoise
- media хранится в `media/`
- static в `static/`
- локаль `ru-ru`
- timezone `Europe/Moscow`

### URL map

Файл:

- `config/urls.py`

Основные разделы:

- `/`
- `/inventory/`
- `/workorders/`
- `/analytics/`
- `/admin/`
- `/accounts/login/`
- `/accounts/logout/`

## 8. Workorders: ключевые файлы

Если нужно продолжать разработку канбана, почти всегда придется смотреть сюда:

- `apps/workorders/models.py`
- `apps/workorders/forms.py`
- `apps/workorders/policies.py`
- `apps/workorders/services.py`
- `apps/workorders/views.py`
- `apps/workorders/urls.py`
- `apps/workorders/tests.py`

Шаблоны:

- `templates/workorders/board.html`
- `templates/workorders/workorder_detail.html`
- `templates/workorders/workorder_form.html`
- `templates/workorders/partials/board_columns.html`
- `templates/workorders/partials/detail_panel.html`
- `templates/workorders/partials/detail_panel_empty.html`
- `templates/workorders/partials/detail_sections.html`
- `templates/workorders/partials/status_section.html`
- `templates/workorders/partials/rating_section.html`
- `templates/workorders/partials/comments.html`
- `templates/workorders/partials/attachments.html`
- `templates/workorders/partials/column_config_card.html`
- `templates/workorders/partials/column_config_form.html`

## 9. UX состояния доски

Сейчас канбан устроен так:

- board рендерится по `KanbanColumnConfig`;
- колонки тянутся на полную ширину и живут в горизонтальном скролле;
- быстрый просмотр карточки скрыт по умолчанию;
- при клике по карточке открывается HTMX drawer/panel;
- быстрые transition-кнопки доступны прямо на карточке;
- менеджер может переименовывать колонки inline.

Важно:

- окно быстрого просмотра не должно быть постоянно видимо;
- список колонок больше не должен хардкодиться в шаблоне или во view;
- колонка определяется данными, а не списком статусов в коде.

## 10. Inventory: ключевые файлы

- `apps/inventory/models.py`
- `apps/inventory/forms.py`
- `apps/inventory/views.py`
- `apps/inventory/urls.py`
- `apps/inventory/tests.py`
- `templates/inventory/device_list.html`
- `templates/inventory/device_form.html`

Что уже есть:

- create
- update
- archive
- фильтры
- скрытие архивных по умолчанию

## 11. Analytics

Файлы:

- `apps/analytics/views.py`
- `apps/analytics/urls.py`
- `templates/analytics/dashboard.html`

Сейчас это базовая сводка:

- по статусам;
- по подразделениям;
- по исполнителям;
- по resolved/closed;
- среднее время решения.

Доступ ограничен менеджером.

## 12. Тесты

Основные тесты лежат в:

- `apps/workorders/tests.py`
- `apps/inventory/tests.py`
- `apps/analytics/tests.py`

Тестовое покрытие уже не нулевое. Сейчас проверяются:

- role matrix по заявкам;
- HTMX partials;
- inline board UX;
- рейтинг и подтверждение закрытия;
- вложения и их валидация;
- inventory update/archive;
- analytics access;
- configurable kanban columns и rename UX.

Перед значимыми изменениями стандартный цикл:

```bash
. .venv/bin/activate
python manage.py check
python manage.py test
```

Если меняются модели:

```bash
python manage.py makemigrations
python manage.py migrate
```

## 13. Как поднять проект

### Локально

```bash
make venv
make install
make check
make test
make contracts
python manage.py migrate
python manage.py seed_roles
python manage.py runserver
```

### Docker

```bash
cp .env.example .env
docker compose up --build
```

## 14. Что важно не сломать

- role-based access должен оставаться серверным, а не только шаблонным;
- `resolved` и `closed` нельзя снова схлопывать в одно состояние;
- канбан-колонки должны оставаться конфигурируемыми через БД;
- drawer быстрого просмотра должен быть скрыт по умолчанию;
- inventory удаляется только мягко через архив;
- вложения должны продолжать валидироваться по типу и размеру.

## 15. Что, вероятно, делать дальше

Наиболее логичные направления развития:

- drag-and-drop карточек между колонками;
- отдельное управление составом колонок, а не только rename;
- inline create заявки на доске;
- richer analytics/SLA метрики;
- LDAP этап;
- более явный settings-driven env management;
- улучшение admin для `KanbanColumnConfig`.

## 16. Если у нового агента мало времени

Минимальный набор файлов для входа:

- `config/settings.py`
- `config/urls.py`
- `apps/workorders/models.py`
- `apps/workorders/policies.py`
- `apps/workorders/services.py`
- `apps/workorders/views.py`
- `apps/workorders/tests.py`
- `templates/workorders/board.html`
- `templates/workorders/partials/board_columns.html`
- `PROJECT_HANDOFF.md`

Для agent-facing execution protocol (tool registry, bounded task types, confirmation flow, verification commands) — см. `AGENTS.md`.

Этого достаточно, чтобы продолжать работу по канбану почти без дополнительной разведки.

## 17. Лист ожидания (Waiting List)

Новое приложение для управления списком пациентов, ожидающих медицинские услуги.

### Маршруты

- `waiting_list:dashboard` — `/waiting-list/` — главная панель со списком
- `waiting_list:create` — `/waiting-list/new/` — форма создания записи
- `waiting_list:detail` — `/waiting-list/<pk>/` — детальная информация
- `waiting_list:update` — `/waiting-list/<pk>/edit/` — редактирование
- `waiting_list:transition` — `/waiting-list/<pk>/transition/` — смена статуса

### Модели

#### WaitingListEntry

- `external_id` — UUID для внешних интеграций (не первичный ключ)
- `patient_name` — ФИО пациента
- `patient_dob` — дата рождения (ДД.ММ.ГГГГ)
- `patient_phone` — телефон (+7 формат)
- `service_id` — услуга (s1, s2, s3)
- `date_tag` — целевая дата
- `date_end` — крайняя дата
- `priority_cito` — флаг срочности
- `status` — статус: waiting, scheduled, confirmed, cancelled
- `comment` — комментарий

#### WaitingListAuditLog

- `entry` — ссылка на запись
- `actor` — пользователь
- `action` — описание действия
- `created_at` — время

### Визуальная система

Лист ожидания использует общую визуальную систему:

- CSS переменные из `app.css` (primary, surface, badges, etc.)
- Компоненты: toolbar, table-container, drawer, badges, timeline
- Классы: `.btn-primary`, `.btn-status-*`, `.badge-*`, `.cito-indicator`

### HTMX взаимодействия

- Таблица обновляется через HTMX при изменении фильтров
- Смена статуса работает без перезагрузки страницы
- Drawer панель открывается при клике на запись
- Клавиатурные сокращения: Alt+N (новая запись), Esc (закрыть drawer)

### Ключевые файлы

- `apps/waiting_list/models.py`
- `apps/waiting_list/forms.py`
- `apps/waiting_list/views.py`
- `apps/waiting_list/services.py`
- `apps/waiting_list/urls.py`
- `apps/waiting_list/tests.py`
- `templates/waiting_list/dashboard.html`
- `templates/waiting_list/entry_form.html`
- `templates/waiting_list/entry_detail.html`
- `templates/waiting_list/partials/entry_table.html`
- `templates/waiting_list/partials/entry_detail_panel.html`

### Сервисный слой

Все операции создания, обновления и смены статуса проходят через сервисные функции:

- `create_entry()` — создание с валидацией
- `update_entry()` — обновление с аудитом
- `transition_entry()` — смена статуса

Валидация телефона и даты рождения — серверная.

### Тесты

```bash
python manage.py test apps.waiting_list.tests
```

Тесты покрывают:
- модель (int PK, UUID external_id, статусы)
- валидацию (телефон, DOB, имя)
- маршруты и HTMX поведение
- аудит изменений
