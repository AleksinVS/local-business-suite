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

После ADR-0031 чтение `role_rules`, `workflow_rules` и `workorder_status_colors` идет через
`apps.core.contract_store.get_contract(name)`: каждый процесс перечитывает рабочую копию по
ключу метаданных файла `(st_mtime_ns, st_size, st_ino)`, поэтому изменение контракта
применяется во всех gunicorn-воркерах без перезапуска. Единственный путь записи —
`apps.settings_center.contract_services.apply_contract_payload` (валидация, атомарная запись,
audit `SettingsChange`). Против потерянного обновления при конкурентной правке запись
принимает `base_hash` — sha256 нормализованной прочитанной версии; при несовпадении с
фактическим файлом запись отклоняется с предложением перечитать.

Если рабочая копия контракта перестала читаться после валидного старта (битый JSON, ошибка
валидации), store продолжает отдавать последний валидный снимок, пишет ERROR в лог и
выставляет сигнал деградации: он виден в `/health/details/` в блоке `services.contracts`
(endpoint активно перечитывает зарегистрированные контракты) и доступен программно через
`apps.core.contract_store.get_degradation_state()`. Деградация — повод немедленно починить
файл в `data/contracts/`, а не штатный режим.

Store отдает файл как есть, без legacy-нормализации: на старых копиях `role_rules` без
ключей `view_analytics`/`manage_departments`/`manage_roles` роли не получат этих прав
(fail-closed), поэтому при обновлении старых установок пересохраните `role_rules` через
Settings Center — запись допишет недостающие ключи.

Для переходов статусов заявок есть отдельный экран `/settings/workflow/transitions/`. Он редактирует тот же `workflow_rules` contract, но показывает матрицу `из статуса -> в статус`. Кнопка `Разрешить все` включает все переходы между разными статусами; права ролей из `role_rules` продолжают применяться отдельно.

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
source ACL metadata -> AD/user/group mapping -> portal scope tokens -> search document / graph evidence tokens
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
