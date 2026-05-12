# Next Steps

Этот документ нужен как рабочий план ближайших шагов без повторного анализа всей кодовой базы.  
Он опирается на текущее состояние проекта после AI-first remediation foundation и expansion block, уже зафиксированных в `main`.

## 1. Текущая базовая точка

Сейчас в проекте уже есть:

- архитектурные документы:
  - [ARCHITECTURE.md](/home/abc/projects/local-business-suite/ARCHITECTURE.md)
  - [DOMAIN_MODEL.md](/home/abc/projects/local-business-suite/DOMAIN_MODEL.md)
  - [POLICY_MODEL.md](/home/abc/projects/local-business-suite/POLICY_MODEL.md)
  - [INTEGRATIONS.md](/home/abc/projects/local-business-suite/INTEGRATIONS.md)
  - [ANALYTICS_MODEL.md](/home/abc/projects/local-business-suite/ANALYTICS_MODEL.md)
  - [PROJECT_MAP.md](/home/abc/projects/local-business-suite/PROJECT_MAP.md)
  - [CHANGE_PATTERNS.md](/home/abc/projects/local-business-suite/CHANGE_PATTERNS.md)
- декларативные контракты:
  - [config/role_rules.json](/home/abc/projects/local-business-suite/config/role_rules.json)
  - [config/workflow_rules.json](/home/abc/projects/local-business-suite/config/workflow_rules.json)
  - [config/integrations/registry.json](/home/abc/projects/local-business-suite/config/integrations/registry.json)
  - [analytics_store/datasets.json](/home/abc/projects/local-business-suite/analytics_store/datasets.json)
- машинно-читаемые артефакты работы:
  - [ai/task_briefs/template.json](/home/abc/projects/local-business-suite/ai/task_briefs/template.json)
  - [ai/change_plans/template.json](/home/abc/projects/local-business-suite/ai/change_plans/template.json)
- AI runtime capabilities:
  - code-first tool registry в [apps/ai/tool_definitions.py](/home/abc/projects/local-business-suite/apps/ai/tool_definitions.py)
  - executable task-type layer в [services/agent_runtime/task_types.py](/home/abc/projects/local-business-suite/services/agent_runtime/task_types.py)
  - agent protocol в [AGENTS.md](/home/abc/projects/local-business-suite/AGENTS.md)
  - завершённый expansion plan в [AI_EXPANSION_BLOCK_PLAN.json](/home/abc/projects/local-business-suite/AI_EXPANSION_BLOCK_PLAN.json)
  - покрытые bounded scenarios:
    - `workorders` (`list`, `detail`, `create`, `transition`, `comment`, `confirm_closure`, `rate`)
    - `lookup` (`departments`, `devices`)
    - `inventory.devices` (`create`, `update`, `archive`)
    - `analytics.summary` (`status`, `departments`, `assignees`)
- команды проверки:
  - `./.venv/bin/python manage.py check`
  - `./.venv/bin/python manage.py validate_architecture_contracts`
  - `./.venv/bin/python manage.py test`

## 2. Ближайшие шаги в порядке приоритета

### Шаг 1. Сделать UI для workflow rules

Цель:

- перестать редактировать [config/workflow_rules.json](/home/abc/projects/local-business-suite/config/workflow_rules.json) только вручную;
- дать управляемый интерфейс для изменения статусов и допустимых переходов;
- сохранить серверную валидацию как обязательную.

Почему это первый шаг:

- role rules уже редактируются через UI;
- workflow rules уже вынесены в конфиг, но пока не имеют того же уровня удобства;
- это завершит основной контур config-driven policy/workflow.

Что нужно изменить:

- добавить форму и view в `apps/core` по аналогии с редактором ролей;
- использовать валидацию из [apps/core/json_utils.py](/home/abc/projects/local-business-suite/apps/core/json_utils.py);
- добавить ссылку в верхнюю навигацию в [templates/base.html](/home/abc/projects/local-business-suite/templates/base.html);
- после сохранения обновлять `settings.LOCAL_BUSINESS_WORKFLOW_RULES`.

Файлы-кандидаты:

- [apps/core/forms.py](/home/abc/projects/local-business-suite/apps/core/forms.py)
- [apps/core/views.py](/home/abc/projects/local-business-suite/apps/core/views.py)
- [apps/core/urls.py](/home/abc/projects/local-business-suite/apps/core/urls.py)
- [templates/core/role_rules_form.html](/home/abc/projects/local-business-suite/templates/core/role_rules_form.html)
- [templates/base.html](/home/abc/projects/local-business-suite/templates/base.html)
- [apps/core/tests.py](/home/abc/projects/local-business-suite/apps/core/tests.py)

Проверка:

- `./.venv/bin/python manage.py check`
- `./.venv/bin/python manage.py test apps.core.tests apps.workorders.tests`

### Шаг 2. Сделать UI для реестра интеграций

Цель:

- позволить вести [config/integrations/registry.json](/home/abc/projects/local-business-suite/config/integrations/registry.json) без ручного редактирования файла;
- превратить список внешних систем в рабочий каталог проекта.

Почему это важно:

- это подготовит почву для настоящих мостов к legacy-системам;
- снимет зависимость от неформального знания о том, какие внешние системы уже учтены.

Что нужно сделать:

- добавить страницу списка интеграций;
- добавить форму редактирования JSON-реестра или CRUD поверх отдельных записей;
- валидировать данные через [apps/core/json_utils.py](/home/abc/projects/local-business-suite/apps/core/json_utils.py);
- в первой итерации достаточно JSON-редактора, как у ролей.

Файлы-кандидаты:

- [apps/core/forms.py](/home/abc/projects/local-business-suite/apps/core/forms.py)
- [apps/core/views.py](/home/abc/projects/local-business-suite/apps/core/views.py)
- [apps/core/urls.py](/home/abc/projects/local-business-suite/apps/core/urls.py)
- [templates/core/role_rules_form.html](/home/abc/projects/local-business-suite/templates/core/role_rules_form.html)
- [apps/core/tests.py](/home/abc/projects/local-business-suite/apps/core/tests.py)

Проверка:

- `./.venv/bin/python manage.py validate_architecture_contracts`
- `./.venv/bin/python manage.py test apps.core.tests`

### Шаг 3. Сделать UI для реестра аналитических датасетов

Цель:

- перевести [analytics_store/datasets.json](/home/abc/projects/local-business-suite/analytics_store/datasets.json) из “служебного файла” в управляемый каталог аналитического слоя;
- подготовить проект к реальному модулю `Evidence + Parquet + DuckDB`.

Что нужно сделать:

- добавить страницу просмотра и редактирования датасетов;
- показывать слой, путь, владельца, режим обновления и уровень детализации данных;
- добавить валидацию при сохранении;
- добавить ссылку из раздела аналитики или системных настроек.

Файлы-кандидаты:

- [apps/core/forms.py](/home/abc/projects/local-business-suite/apps/core/forms.py)
- [apps/core/views.py](/home/abc/projects/local-business-suite/apps/core/views.py)
- [apps/core/urls.py](/home/abc/projects/local-business-suite/apps/core/urls.py)
- [templates/analytics/dashboard.html](/home/abc/projects/local-business-suite/templates/analytics/dashboard.html)
- [apps/core/tests.py](/home/abc/projects/local-business-suite/apps/core/tests.py)

Проверка:

- `./.venv/bin/python manage.py validate_architecture_contracts`
- `./.venv/bin/python manage.py test apps.core.tests apps.analytics.tests`

### Шаг 4. Начать реальный analytics export layer

Цель:

- перейти от описания аналитического слоя к работающему механизму экспорта;
- получить первые `Parquet`-датасеты, которые можно будет читать через DuckDB и затем отдавать в Evidence.

Что нужно реализовать в первой поставке:

- management command для экспорта заявок и журналов переходов;
- запись в пути из [analytics_store/datasets.json](/home/abc/projects/local-business-suite/analytics_store/datasets.json);
- безопасное создание каталогов `analytics_store/raw/` и `analytics_store/marts/`;
- базовую smoke-проверку на успешную генерацию файлов.

Предпочтительный подход:

- экспортировать сначала только `workorders` и `workorder_transitions`;
- не смешивать экспорт и построение marts в одной команде;
- отдельно описать команду экспорта в документации.

Файлы-кандидаты:

- новый management command в `apps/analytics/management/commands/`
- [analytics_store/datasets.json](/home/abc/projects/local-business-suite/analytics_store/datasets.json)
- [ANALYTICS_MODEL.md](/home/abc/projects/local-business-suite/ANALYTICS_MODEL.md)
- [apps/analytics/tests.py](/home/abc/projects/local-business-suite/apps/analytics/tests.py)

Проверка:

- `./.venv/bin/python manage.py test apps.analytics.tests`
- `./.venv/bin/python manage.py validate_architecture_contracts`

### Шаг 5. Подготовить каркас модуля Evidence

Цель:

- создать каталог `analytics_evidence/` как отдельный analytics-as-code слой;
- не внедрять его глубоко в Django, а держать как самостоятельный сервис.

Что нужно сделать:

- создать структуру каталогов `analytics_evidence/pages`, `analytics_evidence/sources`, `analytics_evidence/components`;
- добавить README c объяснением запуска;
- описать связь с `analytics_store`;
- подготовить пример страницы для одного датасета.

Важно:

- на этом шаге можно не доводить интеграцию до production-ready;
- задача шага в том, чтобы заложить управляемую структуру.

## 3. Рекомендуемый способ работы для следующего агента

Перед любой доработкой:

1. взять [ai/task_briefs/template.json](/home/abc/projects/local-business-suite/ai/task_briefs/template.json) и создать новый task brief;
2. сгенерировать change plan через:
   `./.venv/bin/python manage.py generate_change_plan path/to/brief.json --output path/to/plan.json`
3. только после этого вносить изменения;
4. в конце обязательно запускать:
   - `./.venv/bin/python manage.py check`
   - `./.venv/bin/python manage.py validate_architecture_contracts`
   - `./.venv/bin/python manage.py test`

## 4. Что пока не делать без отдельного обсуждения

- не внедрять сложный оркестратор наподобие Airflow;
- не переносить OLTP c SQLite на PostgreSQL только “на будущее”;
- не делать UI-редактор для всех конфигов сразу в одной задаче;
- не добавлять metadata registry для всего проекта целиком;
- не строить deep integration с внешними системами до появления управляемого integration UI.

## 5. Короткая рекомендуемая следующая задача

Если нужен один конкретный следующий шаг без дополнительных обсуждений, брать нужно это:

`Добавить end-to-end regression tests для новых AI-сценариев через gateway: inventory.devices.create/update/archive, analytics.summary, workorders.confirm_closure и workorders.rate.`

Это лучший следующий шаг, потому что он:

- проверяет не только наличие JSON-контрактов, но и реальное исполнение нового AI surface;
- снижает риск регрессий после уже выполненного expansion block;
- опирается на уже существующий gateway и паттерны тестов в `apps/ai/tests.py`;
- даст более надёжную базу перед следующими продуктовыми AI-сценариями.
