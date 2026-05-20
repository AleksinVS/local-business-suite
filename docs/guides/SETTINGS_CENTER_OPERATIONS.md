# Settings Center Operations

Статус: initial operations guide.

Дата: 2026-05-20.

## Назначение

Settings Center находится по маршруту `/settings/` и дает управляемый GUI для:

- runtime JSON contracts;
- локальных пользователей портала;
- явной привязки пользователей к Active Directory identity;
- `.env` status/proposal workflow;
- contextual help mini-chat по каждому значимому `setting_id`;
- memory ACL inheritance diagnostics.

## Доступ

Открывать Settings Center могут staff/superuser пользователи. Управление пользователями и AD link доступно только superuser.

Все write paths должны проходить через server-side views/services. Не полагаться на скрытие кнопок в UI как на механизм безопасности.

## Runtime Contracts

Runtime contracts редактируются как полный JSON payload:

1. открыть нужную настройку;
2. изменить JSON;
3. нажать `Проверить diff`;
4. проверить masked diff;
5. поставить подтверждение;
6. нажать `Применить`.

Write выполняется атомарно через runtime contract path в `data/contracts/`. Default contracts в `contracts/` остаются Git-managed baseline.

После изменения memory sources/profiles/routing/ingestion profiles может потребоваться reindex. После изменения role/workflow rules нужно проверить доступы на тестовом пользователе.

## Users And AD Link

Пользователи портала создаются и отключаются локально. AD link хранит metadata:

- provider;
- SID/subject id;
- sAMAccountName;
- UPN;
- distinguished name;
- domain;
- sync status.

AD link не перезаписывает локальные группы и роли сам по себе. AD metadata используется для ACL resolution и будущих audited sync policies.

## Memory ACL Inheritance

Для file-backed sources поддержан fail-closed contour:

```text
source ACL metadata -> AD/user/group mapping -> portal scope tokens -> snapshot/chunk/fact tokens
```

Если ACL metadata не прочитан, содержит deny entries или principal не сопоставлен с portal user/group, ingestion создает `acl_unresolved` issue и не публикует документ обычным пользователям.

MVP resolver использует нормализованные ACL metadata/overrides в source config. Windows ACL collector можно заменить адаптером без изменения retrieval policy.

## Contextual Help

Каждый descriptor имеет `setting_id`, tooltip и help topic. Кнопка справки открывает плавающее HTMX окно. Вопросы отправляются вместе с descriptor context; secret-like fields маскируются до формирования context.

AI/help ответ не применяет изменения. Любое изменение должно идти через обычный diff/confirmation/service-layer workflow.

## `.env` Proposals

`.env` значения являются deployment bootstrap settings. Production режим по умолчанию:

```dotenv
SETTINGS_CENTER_ENV_APPLY_MODE=proposal
```

GUI показывает effective status и создает proposal-файл в `data/settings_center/env_proposals/`. Оператор переносит изменение в private deployment silo и перезапускает affected processes.

Raw secrets в proposal не сохраняются: secret-like values маскируются.
