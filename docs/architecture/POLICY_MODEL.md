# Policy Model

Policy decisions follow four rules:

1. `models.py` stores data and local invariants.
2. `policies.py` answers who can do what.
3. `services.py` performs state changes and audit logging.
4. `views.py` orchestrates requests and chooses responses.

## Механизмы авторизации

В проекте сознательно сосуществуют три механизма (ADR-0034):

1. **Capability-роли из контракта** — основной механизм для бизнес-прав.
   Роль = группа Django (`django.contrib.auth.Group`) с тем же именем, что ключ
   роли в контракте. Дефолт контракта: [contracts/role_rules.json](../../contracts/role_rules.json),
   рабочая копия: `data/contracts/role_rules.json` (читается через
   `apps.core.contract_store`, ADR-0031). Проверки — `apps/workorders/policies.py`
   (`has_role_capability`, `scope_matches`) и доменные `policies.py` приложений.
2. **Флаги `is_staff` / `is_superuser`** — только «жёсткие» технические гейты:
   Django-админка, settings_center, health-детали. Суперпользователь получает
   все capability автоматически (`superuser_rules()` строится из справочника
   `$capabilities` — ручного списка нет).
3. **Django `Permission`** — точечно в `apps.memory` (`memory.view_review_queue`
   и др.); имена permissions человекочитаемые, на русском.

Workflow transitions are defined in [contracts/workflow_rules.json](../../contracts/workflow_rules.json).

## Понятность прав для нетехнических пользователей

- Блок `$capabilities` в контракте ролей хранит для каждого права `label` и
  `description` на русском — их показывает редактор ролей (`core:role_rules`).
- У каждой роли контракта есть `display_name` и `description`.
- Модель `apps.accounts.models.GroupProfile` добавляет любой группе Django
  название и комментарий; для предопределённых групп профили синхронизирует
  команда `seed_roles`.

## Предопределённые группы

Создаются и обновляются командой `python manage.py seed_roles`:

- `customer` (Заказчик), `technician` (Техник), `manager` (Менеджер) — роли
  канбан-доски заявок;
- `admin` (Администратор портала) — все capability-права; вход в Django-админку
  дополнительно требует `is_staff`;
- `doctor` (Врач) — доступ к листу ожидания (`view_waiting_list`,
  `create_waiting_list`); лист ожидания доступен только врачам;
- `memory_admin`, `memory_auditor`, `memory_index_operator`, `memory_observer` —
  обслуживание памяти ИИ (`apps/memory/policies.py`).

This allows policy changes without rewriting view logic and keeps UI conditions
secondary to server-side checks (см. также ADR-0023: доступ применяется в
селекторах и endpoints, а не только скрытием элементов интерфейса).
