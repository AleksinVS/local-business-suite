# Упрощение хранения и доставки настроек

Статус: planning complete, implementation not started. Старт реализации требует
принятия ADR-0047 владельцем.

## Цель

Заменить зеркальные runtime JSON-копии управляемых настроек одним
транзакционным хранилищем рабочих версий в PostgreSQL, сохранив Git-дефолты,
доменные границы, права, audit и безопасный rollback.

## Бизнес-ценность

- администратор и все процессы используют одну ревизию настройки;
- изменение AI/memory/access не зависит от того, какой worker обслужил запрос;
- уменьшается число случаев «интерфейс показывает новое, runtime использует
  старое»;
- связанные параметры можно редактировать на одном экране без общего
  god-document;
- восстановление и журналирование становятся транзакционными и проверяемыми.

## Архитектурная ценность

- один `ConfigDocumentSpec` registry;
- один repository для Django consumers;
- PostgreSQL transaction для value + `SettingsChange`;
- Git default без обязательной runtime-копии;
- явная схема доставки agent-runtime через Django gateway;
- удаление file/DB staged protocol после миграции.

## Источники решения

- `docs/adr/ADR-0047-typed-setting-documents-and-postgresql-runtime-state.md`;
- `docs/architecture/SETTINGS_STORAGE_TARGET_ARCHITECTURE.md`;
- `docs/planning/active/settings-storage-simplification.md`;
- ADR-0007, ADR-0029, ADR-0031;
- `docs/guides/SETTINGS_CENTER_OPERATIONS.md`.

## Read Scope подготовки

- `config/settings.py`;
- `apps/settings_center/`;
- `apps/core/contract_store.py`, `contract_drift.py`, `json_utils.py`;
- доменные settings descriptors и contract validators;
- runtime consumers в accounts/workorders/waiting_list/ai/memory/filehub/analytics;
- `services/agent_runtime/config.py`, `contract_cache.py`;
- связанные ADR, deployment и operations docs.

## Предполагаемый Write Scope реализации

- `apps/settings_center/` — generic document infrastructure, models, services,
  migration tooling, UI adapters;
- `apps/core/` — shared checks/utilities без доменной семантики;
- `apps/*/config_documents.py` — доменные спецификации и validators;
- текущие consumers и tests перечисленных доменов;
- существующий Django AI gateway и agent-runtime config delivery;
- `config/settings.py`, `bootstrap_runtime` после cutover;
- документация, planning/workflow и карта проекта.

Точный write scope задаётся каждым task packet. Исполнитель не расширяет его
молчаливо.

## Non-goals

- один общий JSON/YAML всех настроек;
- физическое объединение документов ради уменьшения счётчика;
- изменение ролевой модели, workflow или memory architecture;
- secret values в БД документов или audit;
- Redis/pub-sub/Celery и новые runtime services;
- постоянный dual-write;
- перенос knowledge repo, media, AI skills или schema files в PostgreSQL;
- изменение AG-UI/CopilotKit wire contract или версии;
- YAML как канонический runtime backend.

## Обязательные ограничения

- ADR-0047 должен стать `Accepted` до пакета 02; пакет 01 может выполняться как
  уточняющий inventory только после согласования старта;
- текущие незакоммиченные изменения владельца сохраняются;
- каждый cutover имеет backup, freeze, final plan, smoke и rollback window;
- неоднозначный legacy drift не импортируется автоматически;
- роли/workflow, AI и memory получают независимую проверку;
- изменения contracts сопровождаются schema validation и drift plan;
- временные отчёты и export packages пишутся только в `.local/`;
- production cutover не следует из выполнения кода и требует отдельного
  разрешения владельца.

## Порядок

```text
01 inventory/registry
  -> 02 DB store
  -> 03 migration tooling
  -> 04 status-colors pilot
  -> 05 access/workflow
  -> 06 AI + agent-runtime gateway
  -> 07 memory/FileHub + static classification
  -> 08 cleanup/recovery/final acceptance
```

После pilot подготовительные части 05 и 06 могут выполняться параллельно, но
production cutover slices не совмещаются.

## Acceptance

Блок принимается, когда:

- все конфигурационные документы классифицированы;
- каждый управляемый документ имеет одну спецификацию;
- текущая рабочая версия и audit записываются одной PostgreSQL transaction;
- stale writer, rollback и schema migration проверены;
- Django workers видят новую ревизию без restart;
- role/workflow используют согласованный request snapshot и fail closed;
- agent-runtime получает ту же AI-ревизию через allowlisted gateway;
- startup payload constants и legacy readers удалены для мигрированных
  документов;
- default/runtime file drift для них больше не существует;
- backup/restore подтверждает документы и audit continuity;
- unit/integration/e2e и один финальный `make verify-full` пройдены;
- executor/acceptance reports и retrospective заполнены;
- пользователь принял результат, после чего блок архивирован.

## Остаточные риски, которые нельзя принять молча

- legacy runtime отличается от Git default без audit evidence;
- найден неизвестный прямой consumer файла или `settings.LOCAL_BUSINESS_*`;
- security matrix изменилась после role/workflow cutover;
- agent-runtime принимает неизвестную schema version;
- backup не включает PostgreSQL rows/audit;
- rollback требует потерять новые ревизии;
- реализация предлагает второй writable source или новый runtime service.

Любой из этих случаев останавливает соответствующий cutover и фиксируется в
executor report.
