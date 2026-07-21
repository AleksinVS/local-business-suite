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

### Дрейф default/runtime

`get_contract_path` (`config/settings.py`) копирует дефолт из `contracts/` в
`data/contracts/` только один раз — при первом обращении к настройке на этой
установке. Дальше `contracts/` и `data/contracts/` — два независимых файла:
обновление дефолта в git (новая версия контракта в коде) само по себе не
попадает в уже работающую установку. Раньше это расхождение никак не было
видно, кроме частного случая AI tools (`validate_ai_tools_drift` сверяет
Python-каталог инструментов с JSON, а не default-файл с runtime-файлом).

Команда `python manage.py validate_architecture_contracts` теперь дополнительно
печатает отчет о дрейфе по всем контрактам реестра Settings Center
(`apps.core.contract_drift`, ADR-0031 п.4). Для каждого контракта сравниваются
ключи верхнего уровня и хеш нормализованного JSON, три исхода:

- **совпадает с дефолтом** — рабочая копия идентична git-версии;
- **рабочая копия изменена (ожидаемо, не ошибка)** — набор ключей верхнего
  уровня тот же, но значения отличаются: это штатный результат правки через
  Settings Center (или неглубокое изменение дефолта в git), тревоги не требует;
- **кандидат на перенос из дефолта** — в дефолте появились ключи верхнего
  уровня, которых нет в рабочей копии. Это самый ценный сигнал отчета:
  разработчик добавил новую опцию контракта, а работающая установка ее не
  увидит, пока кто-то не перенесет значение вручную. Сама команда это не делает
  (только диагностика, без автослияния) — откройте нужную настройку в Settings
  Center, добавьте недостающий ключ в JSON (посмотрев его значение в
  `contracts/.../<файл>.json`) и сохраните через обычный diff/confirmation flow.

По умолчанию дрейф — не ошибка команды (exit code 0), отчет только печатается.
Флаг `--fail-on-drift` (`python manage.py validate_architecture_contracts --fail-on-drift`)
дает ненулевой код при любом дрейфе — используйте его в CI/pre-deploy проверках,
если для конкретного окружения нужно требовать полного соответствия дефолту.

Методическая заметка: дефолт (`contracts/`) и рабочая копия (`data/contracts/`)
намеренно разделены (`AGENTS.md`, "Разделение кода и данных") — рабочая копия
может отличаться от git на легитимных основаниях (администратор настроил
правила под конкретную организацию). Поэтому дрейф — это состояние, требующее
осмысленного решения человека (перенести новую опцию или оставить как есть),
а не автоматическая синхронизация: тихое перетирание рабочей копии дефолтом
уничтожило бы намеренные локальные настройки, а тихое игнорирование новых
опций дефолта оставило бы старые установки без новой функциональности без
единого предупреждения.

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
