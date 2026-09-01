# Settings Center Operations

Статус: актуальное эксплуатационное руководство.

Дата обновления: 2026-09-01.

## Назначение

Settings Center находится по маршруту `/settings/` и дает управляемый GUI для:

- runtime JSON contracts;
- локальных пользователей портала;
- явной привязки пользователей к Active Directory identity;
- `.env` status/proposal workflow;
- contextual help mini-chat по каждому значимому `setting_id`;
- memory ACL inheritance diagnostics;
- палитр статусов доски заявок и листа ожидания.

## Доступ

Продуктовые настройки доступны активному superuser или участнику
контрактной роли с `manage_settings=true` (в поставляемом контракте это
роль `admin`). `is_staff` даёт только вход в Django Admin и не открывает
продуктовые настройки. Управление профилями пользователей и AD link
остаётся резервной операцией superuser.

Все write paths должны проходить через server-side views/services. Не полагаться на скрытие кнопок в UI как на механизм безопасности.

## Runtime Contracts

### Типизированное хранилище PostgreSQL

В рамках ADR-0048 добавлен новый контур рабочих документов:

- `ConfigDocumentSpec` задаёт владельца, валидаторы, зависимости, политику
  сбоя и активный backend;
- `ConfigDocumentRepository` читает один проверенный снимок связанной группы;
- `RuntimeSettingDocument` хранит только текущую полную рабочую версию;
- `SettingsChange` хранит снимки до/после и номера ревизий;
- `ConfigDocumentWriter` записывает значение и аудит в одной транзакции.

Отсутствие строки `RuntimeSettingDocument` означает использование Git-дефолта.
Первая рабочая версия имеет ревизию `1`, каждое следующее изменение увеличивает
её ровно на единицу. Для CAS-проверки используются одновременно ожидаемая
ревизия и SHA-256 полного канонического JSON. Формат нового хеша — 64 строчных
шестнадцатеричных символа; `NaN`, `Infinity` и не-JSON значения запрещены.

Writer поддерживается только на PostgreSQL: он берёт transaction-level advisory
locks для всей связанной группы в сортированном порядке, затем блокирует
существующие строки, повторно проверяет пользователя, версию, доменные и
кросс-документные правила. SQLite остаётся средой локального чтения и unit-
проверок; попытка записи завершается до изменения документа или аудита.

Политики ошибок различаются:

- `fail_closed` не подменяет повреждённую рабочую security/privacy-настройку
  дефолтом;
- `visible_default_fallback` разрешён только для некритичного представления
  (палитры, настройки чата) и обязательно выставляет видимый сигнал деградации.

Текущее добавление модели и сервисов само по себе не переключает рабочие
документы. Поле `active_backend` в реестре остаётся `legacy_file`, пока document
ID не включён в `LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST`; `git_static`
читается из `contracts/`. Allowlist пуст по умолчанию, не принимает wildcard,
проверяет полный связный срез и применяется только после restart процессов.

В коде выпущены `waiting_list.contract.status_colors` и связанный срез
`core.contract.role_rules`, `core.contract.workflow_rules`,
`workorders.contract.status_colors`, а также `ai.contract.chat_settings`.
Выпуск означает только возможность явно
добавить полный срез в allowlist. На текущем тестовом хосте включён только pilot
листа ожидания; access-срез остаётся legacy до отдельного решения владельца по
точным хешам роли и операционного окна.

Для memory/FileHub выпущен полный connected DB-ready срез из восьми
документов: `memory.contract.sources`, `memory.contract.profiles`,
`memory.contract.routing`, `memory.contract.trust_policy`,
`memory.contract.retrieval_budget`, `memory.contract.ingestion_profiles`,
`memory.contract.file_organization_profiles` и `memory.contract.graph_schema`.
Исключение — `memory.contract.claims_policy`: это `git_static`-документ и в
DB allowlist не входит. Выпуск не меняет приватный deployment allowlist. Для
memory-документа с `requires_reindex` writer в той же PostgreSQL-транзакции
после записи документа и `SettingsChange` создаёт идемпотентную durable
outbox job с ключом
`settings-memory-reindex:<document>:<revision>:<hash>`; при rollback, ошибке
вставки или внешнем откате ни документ, ни job не остаются. Тяжёлый reindex
выполняется только worker-ом после commit.
Нельзя вручную создавать или исправлять строки `RuntimeSettingDocument` через
Django Admin: раздел доступен только для просмотра. Нельзя также копировать
runtime-файл поверх уже переключённого DB-документа — такой файл больше не
является эффективным значением.

Перед переключением обязательны план миграции, резервная копия и PostgreSQL-
проверки конкурентной первой записи, stale conflict, rollback и общего отката
документа с аудитом. Production cutover выполняется только отдельным
операционным решением владельца.

### AI gateway и aggregate snapshot

Agent-runtime не читает AI-контракты из `data/contracts/` и не раскрывает их
пути. Django предоставляет только фиксированный read-only набор по маршруту
`GET /ai/gateway/contracts/?ids=...` при наличии service token
`X-AI-Gateway-Token`. Нужно передавать явные IDs; неизвестные IDs не превращают
маршрут в перечисление документов. В каждом документе передаются
`document_id`, `schema_version`, `revision`, `content_hash` и `payload`. Общий
strong ETag учитывает отсортированные ID, версии схемы, ревизии и хеши;
совпадающий `If-None-Match` получает `304` без тела.

Runtime проверяет полный requested set, schema version `1`, канонический
SHA-256 payload и ETag, после чего одной операцией заменяет LKG-снимок. Успешные
`200` и `304` обновляют время последней проверки. Ошибка шлюза не заменяет LKG;
по умолчанию он используется не более 300 секунд
(`LOCAL_BUSINESS_AI_CONTRACT_MAX_STALE_AGE_SECONDS`). До первого валидного
снимка и после истечения срока runtime работает fail-closed.
`/health/details` показывает только источник, возраст, ревизии, хеши и безопасный
код ошибки — без payload, секретов и абсолютных путей.

Перед binding инструмента agent-runtime пересекает статический Python-реестр,
доставленный `ai.contract.tools` и mode-совместимые `allowed_tools` из
`ai.contract.task_types`. Django повторяет эту проверку непосредственно перед
исполнением или подтверждением действия. Поэтому отсутствие, конфликт или
дрейф policy запрещает вызов, а вспомогательный read-инструмент из write-задачи
не получает подтверждение ошибочно. При отсутствии LKG возраст в health API
сериализуется как `null`.

`ai.contract.chat_settings` включён в список выпущенных DB-документов. После
переключения backend в приватном deployment allowlist Django видит изменение
на следующем request, а runtime — на следующей операции после успешной проверки
gateway; перезапуск для изменения самого документа не требуется. Изменение
allowlist backend по-прежнему является deployment-настройкой и требует
перезапуска процессов.

Git-static документы (`ai.contract.registry`, `tools`, `task_types`, `models`)
в Settings Center доступны только как JSON viewer: для них нет textarea,
preview и apply. Endpoint preview также проверяет `write_policy` и не создаёт
`SettingsChange` для read-only документа. `chat_settings` остаётся единственным
редактируемым AI-документом этого среза и читается из постоянной
`RuntimeSettingDocument` после DB cutover.

### Legacy file backend

Runtime contracts редактируются как полный JSON payload:

1. открыть нужную настройку;
2. изменить JSON;
3. нажать `Проверить diff`;
4. проверить masked diff;
5. поставить подтверждение;
6. нажать `Применить`.

До DB cutover legacy-write выполняется атомарно через существующий runtime path
в `data/contracts/`. После cutover запись идёт только в PostgreSQL; Git-дефолты
в `contracts/` остаются неизменяемой базовой версией.

После ADR-0031 чтение `role_rules`, `workflow_rules`, `workorder_status_colors` и
`waiting_list_status_colors` идёт через
`apps.core.contract_store.get_contract(name)`. Для legacy backend каждый процесс
перечитывает рабочую копию по ключу метаданных файла
`(st_mtime_ns, st_size, st_ino)`. Для выпущенного документа, включённого в DB
allowlist, тот же совместимый вход получает проверенный request-local снимок из
`ConfigDocumentRepository`; middleware фиксирует связанную ревизию даже для
старых вызовов без аргумента `request`. После успешной записи request-local кэш
сбрасывается, поэтому HTMX-ответ того же запроса уже строится по новой ревизии,
а другой процесс видит её следующим запросом без перезапуска.

Legacy-запись выполняет
`apps.settings_center.contract_services.apply_contract_payload`: валидация,
атомарный файл и audit `SettingsChange`. DB-запись проходит через тот же
прикладной сервис, но использует `ConfigDocumentWriter`, ожидаемые revision/hash
и одну PostgreSQL-транзакцию для документа и аудита. Несовпадение версии
отклоняется с предложением перечитать форму.

Если рабочая копия контракта перестала читаться после валидного старта (битый JSON, ошибка
валидации), store продолжает отдавать последний валидный снимок, пишет ERROR в лог и
выставляет сигнал деградации: он виден в `/health/details/` в блоке `services.contracts`
(endpoint активно перечитывает зарегистрированные контракты) и доступен программно через
`apps.core.contract_store.get_degradation_state()`. Деградация — повод немедленно починить
файл в `data/contracts/`, а не штатный режим.

Store отдает файл как есть, без legacy-нормализации: на старых копиях `role_rules` без
ключей `view_analytics`/`manage_departments`/`manage_roles` роли не получат этих прав
(fail-closed). Новые capability-ключи нельзя дописывать обычным сохранением:
для них используется deployment-процедура ниже.

### Замороженный `$capabilities`

Обычный Settings Center, rollback и ограниченный редактор роли могут менять
только определения ролей. Под общей access-блокировкой сервис всегда проверяет:

```text
hash(effective role_rules.$capabilities)
  == hash(contracts/role_rules.json.$capabilities)
candidate.$capabilities == runtime.$capabilities
```

Несовпадение закрывает любую обычную запись. Не пытайтесь исправить его через raw JSON
или rollback: это защита от изменения security-semantics во время работы.

Для планового deployment-изменения:

1. В Git обновите `contracts/role_rules.json`, enforcement points и тесты.
2. Из текущего runtime-контракта подготовьте полный reviewed candidate JSON. В нем можно
   изменить только catalog metadata и соответствующие значения этих capability в каждой
   роли. Набор ролей, `$administration`, описания, признаки защиты и значения неизменённых
   capability должны остать прежними.
3. Получите три полных SHA-256: текущего runtime catalog, целевого Git catalog и всего
   текущего runtime-контракта. Хеши вычисляются по нормализованному JSON, как
   `apps.core.contract_store.normalized_hash`.
4. Запустите от deployment-оператора:

```bash
python manage.py migrate_role_capabilities \
  --operator-id <active-superuser-id> \
  --candidate <reviewed-full-role-rules.json> \
  --expected-runtime-catalog-hash <sha256> \
  --expected-git-catalog-hash <sha256> \
  --expected-runtime-hash <sha256> \
  --reason "<change-ticket/review reason>"
```

Команда повторно загружает active superuser, сверяет все хеши под общей
блокировкой и повторно валидирует полный candidate. На legacy backend она
атомарно заменяет runtime-файл через staged audit. На DB backend она увеличивает
ревизию `RuntimeSettingDocument`, обновляет `default_hash` и создаёт
`SettingsChange` в одной транзакции. В обоих случаях сначала создаётся и
проверяется копия в `data/contracts/backups/`. No-op и любое несовпадение
отклоняются. В stdout выводятся только ID аудита, короткие хеши и имя backup;
JSON и значения прав не печатаются.

Восстановление backup не выполняется обычным rollback: исторический catalog будет отклонён.
Для обратного deployment подготовьте обратный Git commit и reviewed candidate из резервной копии,
затем повторите ту же команду с новыми expected hashes. Не копируйте backup поверх runtime-файла вручную.

### Удаление legacy `$administration`

Полномочие создания, изменения и назначения обычных ролей определяется только
`manage_roles`. Старые `role_definition_editor_roles` и
`role_assignment_allowlist` остаются parseable для совместимого запуска старой
рабочей копии, но полностью игнорируются политиками. Обычная запись и rollback
не могут изменить или удалить `$administration`.

После deployment Git-default без этого блока вычислите нормализованные полные
хеши текущего runtime и Git-default и выполните один раз:

```bash
python manage.py migrate_role_administration \
  --operator-id <active-superuser-id> \
  --expected-runtime-hash <current-runtime-sha256> \
  --expected-git-hash <deployed-git-default-sha256> \
  --reason "<change-ticket/review reason>"
```

Вариант этой команды для legacy-файла нужно выполнить до DB cutover роли.
После переключения `role_rules` запись в legacy-файл запрещена. Та же команда
`migrate_role_administration` при active DB backend маршрутизируется в отдельный
constrained DB writer `migrate_role_administration_metadata`: он изменяет
проверенную PostgreSQL-ревизию через `ConfigDocumentWriter` и создаёт audit в
одной транзакции; legacy-файл при этом не изменяется. Это отдельный
deployment-срез для `$administration`: он не является продолжением миграции
роли `viewer`.

В legacy-варианте команда повторно загружает active superuser под общей
access-блокировкой, требует отсутствия `$administration` в Git-default и
строит кандидат сама: точная runtime-копия без этого единственного блока.
Она создаёт проверенный backup в `data/contracts/backups/`, staged audit,
атомарно заменяет файл и печатает только ID, короткие хеши и имя backup. В
DB-варианте эти действия выполняет constrained writer для строки и аудита БД;
legacy-файл не является write target. Неверный хеш, отсутствующий блок или
любая ошибка не создают успешную миграцию.

Создание новой роли выполняется fail-closed: под общей блокировкой сначала
резервируется пустая предопределённая `Group/GroupProfile`, а затем атомарно
активируется запись контракта и аудит. Поэтому сбой или аварийная остановка до
записи контракта не может превратить техническую/AD-группу в роль. Безопасная
пустая группа-резерв не выдаёт доступ; повтор с теми же кодом, названием и
описанием завершает создание. Любая группа с участниками, Django permissions,
другим профилем или без предопределённого профиля считается посторонней и
отклоняется.

### Дрейф default/runtime

Старые установки могли создать копию Git-дефолта в `data/contracts/`. Если такой
legacy-файл существует, он остаётся независимым от `contracts/`: обновление
дефолта в Git само по себе в него не попадает. Чистый `bootstrap_runtime` больше
не создаёт зеркала; при отсутствии канонического legacy-файла до cutover
repository читает проверенный Git-дефолт. После DB cutover сравниваются уже
Git-дефолт и рабочая версия PostgreSQL.

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

### Цвета статусов разделов

В разделе `/settings/` зарегистрированы две палитры:

- `/settings/workorders/status-colors/` — доска заявок;
- `/settings/waiting-list/status-colors/` — лист ожидания.

Каждый статус имеет основной цвет и цвет заливки. Основной цвет используется для
текста, границы и акцента, заливка — для фона метки, переключателя или строки.
Форма показывает результат сразу в предварительном образце, но записывает изменение
только после явного подтверждения. Дефолты находятся в
`contracts/workorder_status_colors.json` и
`contracts/waiting_list_status_colors.json`. Пока документ работает через legacy,
его рабочее значение находится в одноимённом файле `data/contracts/`. После
явного включения выпущенного `waiting_list.contract.status_colors` в DB allowlist
эффективное рабочее значение хранится в `RuntimeSettingDocument`; legacy-файл
остаётся неизменным и не участвует в записи. Палитра заявок пока всегда остаётся
legacy. В обоих режимах изменение создаёт `SettingsChange` и становится видно
другим процессам без перезапуска.

После успешной записи любого memory-документа с `requires_reindex` worker
обработает ровно одну идемпотентную outbox job после commit; ручной запуск
reindex для этой границы не требуется. После изменения role/workflow rules
нужно проверить доступы на тестовом пользователе.

## Объяснение доступа и передача в редактор

Карточка доступа и AI read-инструменты используют одну privacy-safe проекцию.
В ней отдельно показаны контрактные роли, резерв суперпользователя, обычные
технические группы и группы памяти. Прямые Django permissions, email и AD
identity в объяснение не входят. ACL ресурса и workflow отображаются только
как ограничения, которые сужают уже найденный доступ; полный список ACL не
выгружается.
В машинном ответе это фиксируется признаками `object_scoped=true` и эффектами
`narrows_role_scope`/`narrows_transitions`.

Неактивный пользователь может сохранить назначенные membership-факты для
разбора, но его эффективные capability и резерв суперпользователя пусты.
Инструмент `access.users.explain` доступен свежему active actor с `manage_roles`
или active superuser и не создаёт `PendingAction`.

`access.open_editor` принимает только `target_type=user|role` и `target_id`.
Settings Center provider повторно проверяет цель и строит фиксированный
локальный URL канонического `AccessWorkspaceView`. Ответом является только
HTMX-фрагмент в `#global-right-panel-content`: таблица и навигация не заменяются,
а сохранение остаётся внутри выезжающей панели. ИИ получает команду открытия,
но изменение применяется только кнопкой «Сохранить» в редакторе.
`ui.open_right_panel` остаётся режимом просмотра и не может открыть этот
редактор через произвольный URL.

## Явная роль viewer: операция миграции

На legacy access backend переход с `default_board_viewer` выполняется только
active superuser. Runtime-признак фазы — наличие `viewer` в
`data/contracts/role_rules.json`; постоянный флаг или таблица миграции не
используются.

Миграция `viewer` относится только к legacy access backend и должна быть
полностью завершена до access DB cutover роли (`role_rules`), включая проверку
подписанного результата `cutover`. Поэтому перед включением access-среза в
PostgreSQL нужно закрыть все операции `prepare`/`cutover` по viewer. После DB
cutover команды legacy `prepare_explicit_viewer`,
`cutover_explicit_viewer` и `rollback_explicit_viewer` запрещены, в том числе
для ранее подготовленного manifest. Изменение DB-версии ролей выполняется
только через соответствующий DB writer и не запускает legacy viewer migration.

```bash
python manage.py report_roleless_users --output data/access-migrations/roleless-users.json
python manage.py apply_roleless_user_manifest --manifest data/access-migrations/approved.json --actor-id <id> --reason "..."
python manage.py cutover_explicit_viewer --manifest data/access-migrations/approved.json --actor-id <id> --reason "..."
python manage.py rollback_explicit_viewer --manifest data/access-migrations/approved.json --actor-id <id> --reason "..."
```

Manifest обязан содержать ровно один выбор (`viewer`, `customer`, другая существующая роль или `no_role`) для каждого текущего roleless пользователя и отдельный логический выбор ACL для каждой доски, открытой `customer`. Подготовка создаёт инертную группу и аудируемые назначения/ACL под общей блокировкой; до cutover они не дают продуктового доступа. Любой дрейф пользователей, подразделений, технических флагов, групп, ACL или контракта завершает операцию отказом.

Исходный отчёт показывает точные доски до миграции и точные изменения для
`no_role`, `customer` и других существующих ролей. Для `viewer` итог зависит от
отдельных решений по доскам, поэтому до подготовки он помечен
`requires_board_choices=true`. Команда подготовки записывает в подписанный
operation-файл `final_access_deltas` с точными `before/after/added/removed` уже
с учётом всех решений по доскам и superuser-reserve. Перед `cutover` владелец
обязан проверить этот раздел; подготовленные назначения и ACL ещё инертны, так
что проверка не меняет фактический продуктовый доступ.

Во всех трёх изменяющих командах нужно передавать одну и ту же формулировку `--reason`. Каждая команда атомарно обновляет тот же подписанный файл операции. Если процесс прервался, повторите ту же команду с тем же файлом, суперпользователем и причиной: сервис сверит рабочее состояние с журналами и либо безопасно завершит этап, либо остановится при постороннем изменении. Не редактируйте файл после выполнения команды подготовки.

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
