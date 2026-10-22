# Границы переноса продуктивного Waiting List

Статический исходный отчёт P0; общий статус и результаты запусков — в
[проверках](VERIFICATION.md), навигация — [P0](../13_P0_BASELINE.md).


## Оглавление

- [1. Что действительно связано в актуальных моделях](#1-что-действительно-связано-в-актуальных-моделях)
- [2. Минимальный сохраняемый набор](#2-минимальный-сохраняемый-набор)
- [3. Условный набор и чёткие исключения](#3-условный-набор-и-чёткие-исключения)
- [4. Миграционная зависимость не равна переносимым данным](#4-миграционная-зависимость-не-равна-переносимым-данным)
- [5. Существующие импортёры: существенные ограничения](#5-существующие-импортёры-существенные-ограничения)
- [6. Предлагаемые проверки до переключения (не выполнены)](#6-предлагаемые-проверки-до-переключения-не-выполнены)
- [7. Открытые вопросы перед реальным переносом](#7-открытые-вопросы-перед-реальным-переносом)
- [Проверка на Windows-сервере](#проверка-на-windows-сервере)
- [Локальный снимок и план восстановления](#локальный-снимок-и-план-восстановления)

Дата: 2026-10-22. Основание: последнее уточнение владельца — существует одно продуктивное внедрение Windows + IIS, используется только Waiting List. Заявленный перенос: лист ожидания, пользователи, права, подразделения, оборудование. Это подтверждение владельца, а не результат доступа к серверу. Фактическая СУБД, версия развёрнутого кода, число строк, настройки входа и состояние данных не проверялись. Реальная БД, secrets и host settings не читались; тесты и команды приложения не запускались.

## 1. Что действительно связано в актуальных моделях

| Объект | Прямые связи | Следствие |
|---|---|---|
| WaitingListEntry | nullable author → AUTH_USER_MODEL, PROTECT (`apps/waiting_list/models.py:36`) | Для всех ненулевых author_id нужен тот же пользователь; существующий NULL нельзя заменять импортирующим |
| WaitingListAuditLog | entry → WaitingListEntry CASCADE; actor → User PROTECT (`:93`, `:99`) | История — отдельные обязательные переносимые строки, включая точные actor_id и времена |
| User | AbstractUser, department → Department PROTECT (`apps/accounts/models.py:7`, `:12`) | Нужны учётки со всеми flags/password hash и Django M2M groups/user_permissions; Department обязателен в текущей версии |
| GroupProfile | OneToOne Group CASCADE (`apps/accounts/models.py:63`) | Сохранить собственные описания и predefined metadata вместе с группами |
| AccessAssignmentAudit | actor nullable User PROTECT; target User PROTECT (`apps/accounts/models.py:105`, `:113`) | История полномочий не равна текущему членству; переносится отдельно, корреляция/preview fingerprints сохраняются |
| ExternalIdentity | User CASCADE; уникальность provider+subject_id, provider+domain+username, user+provider (`apps/accounts/models.py:170`, `:199`) | Нужна для уже связанного AD/IIS пользователя, не создавать новые связи по похожим именам |
| Department | parent self-FK PROTECT (`apps/core/models.py:6`), oid обычная строка, не unique (`:14`) | Перенести всё дерево/предков; OID или name сами по себе не являются безопасной заменой PK |
| MedicalDevice | department → Department PROTECT, больше FK/M2M нет (`apps/inventory/models.py:53`) | Оборудование входит по запросу владельца, а не вследствие FK из Waiting List; перенести полные поля, archive state и даты |

У WaitingListEntry/AuditLog нет связей с MedicalDevice, Board, WorkOrder, StockDocument, Patient/PatientAlias, нет M2M, FileField/ImageField/GenericForeignKey. В актуальном приложении нет отдельного реляционного Patient: patient_name/dob/phone находятся в самой строке записи (`apps/waiting_list/models.py:44`). service_id — строка choices, отдельного справочника услуг в БД нет (`:14`, `:47`).

Это вывод о текущих исходниках. Наличие старых расширений/таблиц/вложений на продуктивном сервере пока неизвестно; перед переносом нужна инвентаризация схемы и пользовательских файлов на исходной версии.

### Псевдоним пациента и производные сведения

Отдельного сохранённого patient alias в моделях не найдено. Source adapter вычисляет псевдоним из `external_id:pk` и SECRET_KEY (`apps/waiting_list/source_adapter.py:182`); запись памяти использует object_id=PK, business_key=waiting-list:PK и external_id в payload (`:55`, `:151`). Поэтому смена PK/external_id/ключа меняет псевдоним и ссылки в производных проекциях. Это не основание переносить SECRET_KEY в Git: при необходимости непрерывности псевдонимов ключ/стратегия должны переноситься приватно либо проекции перестраиваются с явно согласованной сменой идентификаторов. В текущем scope, где используется только Waiting List, Memory/Analytics-проекции не требуются, но их наличие следует проверить и явно классифицировать.

## 2. Минимальный сохраняемый набор

Минимум здесь означает сохранение заявленного содержимого и происхождения без превращения истории в новые события. Не означает минимальное число таблиц, достаточное лишь для запуска страницы.

1. `core_department` — все подразделения, дерево родителей, PK и OID. Полный справочник соответствует заявленному scope и снимает риск пропуска предков/подразделений пользователей или оборудования.
2. `accounts_user` — все пользователи, включая inactive и исторических авторов/акторов; PK, username, encoded password, is_active/is_staff/is_superuser, department_id, dates и профиль. Хеши паролей и идентификаторы не выводить в отчёты; поддерживаемые password hashers проверить на восстановленном контуре. Не пересоздавать учётки через create_user/AD auto-provisioning.
3. `auth_group`, `accounts_groupprofile`, `accounts_user_groups` — весь каталог ролей и технических групп и точные memberships. Технические группы могут участвовать во входе/ACL; их нельзя выкинуть по отсутствию в role_rules.
4. Django permissions: `auth_group_permissions`, `accounts_user_user_permissions` и связанные Permission/ContentType semantics. При полной совместимой копии БД сохраняются таблицы и ID; при переносе в новую схему сопоставление по `(content_type.app_label, content_type.model, permission.codename)`, поскольку численные Permission/ContentType PK могут отличаться после migrate. Пользовательские permissions не терять; значения/строки не раскрывать в публичном отчёте.
5. Полный фактически действующий `core.contract.role_rules`: рабочие определения ролей, `$capabilities`, protected metadata, `$defaults.new_user_role` и версионные hashes/revision. Это источник бизнес-прав сверх Django permissions. Перенос одних groups/M2M не сохраняет полномочия.
6. `waiting_list_waitinglistentry` — все исходные PK, unique external_id UUID, author_id (включая NULL), все поля данных, status, created_at, updated_at без перегенерации.
7. `waiting_list_waitinglistauditlog` — все строки с исходными PK, entry_id, actor_id, action, created_at. Исходная история содержит авторство и даты независимо от текущего состояния записи.
8. `accounts_accessassignmentaudit` — все исходные audit rows для сохранения истории прав, включая roles/flags before/after, source, reason, correlation_id, preview_fingerprint, risk confirmation, created_at. При более узкой выборке users потребовалось бы рекурсивно включить всех actor/target, но здесь заявлены все пользователи.
9. `inventory_medicaldevice` — весь заявленный набор оборудования, включая архивное; исходные PK и department_id, nullable values, текстовые model/inventory_number, даты и archive consistency. Это не Warehouse: складские таблицы не входят в заявленное оборудование.

Для рабочей конфигурации также нужен фактически действующий `core.contract.workflow_rules`: role document связан с ним cross-validation (`apps/accounts/config_documents.py:30`). Реестр требует полную connected validation scope при DB backend (`apps/settings_center/document_registry.py:191`), что может включать и `workorders.contract.status_colors` через workflow. Это зависимость документа/валидатора, не требование переносить WorkOrder/Board business rows. Палитру `waiting_list.contract.status_colors` сохранить при наличии override (`apps/waiting_list/config_documents.py:8`). Бизнес-переходы Waiting List заданы локально в `WAITING_LIST_TRANSITIONS`, а не в WorkOrders workflow (`apps/waiting_list/policies.py:9`).

## 3. Условный набор и чёткие исключения

| Набор | Когда нужен | Условие сохранности |
|---|---|---|
| `accounts_externalidentity` | Существующие AD/IIS/LDAP связи | Перенести вместе с пользователями, уникальными ключами и статусом проверки; не привязывать по совпавшему email/имени |
| `settings_center_runtimesettingdocument` | Документы переведены на DB backend | Нужны payload/schema_version/revision/content_hash/default_hash/updated_by; отсутствие override означает конкретный Git default исходной версии, его тоже фиксировать |
| `settings_center_settingschange`, `settings_center_settingschangecomment` | Сохранение происхождения ролей/настроек и возможности rollback | Рекомендуется сохранить все относящиеся к scope истории; при фильтрации рекурсивно включать rollback_of и comments, всех actor; immutable snapshot/hash не пересчитывать как новое изменение |
| Legacy runtime contract files и backups/audit артефакты | Рабочий backend file либо история старых миграций | Приватная копия файлов + хеши + путь в закрытом manifest; подтвердить выбор backend, не активировать одновременно конфликтующие authority |
| `notifications_notificationpreference` | Пользовательские настройки уведомлений требуется сохранить и таблица используется | Сохранить user/channel/event_type/enabled/quiet_hours, не подставлять default=True всем |
| Browser notification clients/event+recipient history | Если это явно сохраняемая функция установки | Самостоятельный набор; события имеют source_object_id в строке, не FK — проверить ссылки после переноса. Browser permission не выдаётся сервером автоматически |
| `django_admin_log` | Требуется полная история административных действий | Сохранить user и content_type mapping; object_id текстовый, нужен контроль ссылок |
| Memory/Analytics projections, source objects, files | Только если реально созданы и должны сохраниться | Это расширение scope; source_object_id/business_key/derived URLs используют исходные идентификаторы. Обычно отдельное решение: сохранить либо перестроить |
| Файловые документы/attachments | Только если найдены в старой установке или связанных дополнительных модулях | В актуальной WL модели файлов нет; не предполагать наличие и не объявлять потерю файлов допустимой без обследования |

Отдельной универсальной модели UserPreference в просмотренных актуальных models нет. Настройки уведомлений — указанная модель; favourites/sidebar state находятся в localStorage (`templates/base.html:200`, `:213`, `static/src/js/sidebar_resize.js:11`), а не в User table. Они не мигрируют SQL backup между browser origins. Это не влияет на полномочия. Browser localStorage не собирать без отдельной необходимости.

`new_user_policy` — не отдельная модель: текущая политика находится в `$defaults.new_user_role` role document; записывает её специальный superuser workflow (`apps/settings_center/contract_services.py:71`, `:105`). Git default null не доказывает production value. Она назначает роль только новым пользователям и создаёт audit (`apps/accounts/services.py:1198`); перенос существующих пользователей через этот service ошибочно меняет историю.

Sessions, активные previews/PendingAction, credentials хостов, queues, тестовые/демонстрационные данные и production host конфигурация не становятся частью репозитория. Для корректного переноса runtime secrets и IIS/AD настройки нужны приватному deployment-пакету; этот аудит не читает и не копирует их. Сохранение sessions не является обязательным условием сохранения пользователей; повторный вход после переключения допустим при подтверждённой настройке входа.

## 4. Миграционная зависимость не равна переносимым данным

- Waiting List migrations `0001`, `0003`, `0004` зависят от AUTH_USER_MODEL, а не от Inventory/WorkOrders (`apps/waiting_list/migrations/0001_initial.py:13`, `0003_waitinglistentry_author_and_more.py:10`). Это схема, не обязательство копировать все пользовательские обратные связи.
- Accounts initial → Core 0003; Core 0004 → Accounts 0003; Accounts 0008 → Core 0006. Сохраняется исторический порядок конкретных миграций, а не простой DAG приложений.
- Inventory initial ещё хранит department текстом; 0003 переводит в Core FK; последующие 0005/0006/0007/0008 зависят от Core и меняют поля/ограничения (`apps/inventory/migrations/0003_department_reference.py:37`, `0006_medicaldevice_building_and_more.py:9`, `0008_alter_medicaldevice_serial_and_more.py:21`). Старая продуктивная схема может не совпасть с HEAD; нельзя копировать строки по пересечению колонок и заявлять lossless.
- Accounts 0008 автоматически создаёт служебные подразделения и заполняет NULL department (`apps/accounts/migrations/0008_mandatory_user_department.py:10`). Эти изменения — явный upgrade delta, который нужно учитывать отдельно от равенства исходных строк. Нельзя скрывать перераспределение пользователей как «обычный restore».
- Текущий runtime всё ещё импортирует WorkOrders через Accounts/Core и Waiting List policies, реестры и маршруты. Наличие этих apps/таблиц при запуске не означает наличие в них productive данных и не расширяет заявленный перенос на Kanban/Warehouse. Отключение/удаление apps — отдельные последующие этапы.
- `django_migrations` фиксирует состояние исходной схемы. При полном restore оно сохраняется с БД; при осмысленном выборочном переносе в уже созданную новую схему его нельзя слепо поверх переписывать исходными строками.

## 5. Существующие импортёры: существенные ограничения

**Текстовый импорт Waiting List не годится для точного переноса продуктивной БД.** `WaitingListImportRow` не содержит source PK/external_id/author/updated_at (`apps/waiting_list/data_operations.py:61`). `import_waiting_list_rows` создаёт новые записи/UUID и всем назначает одного переданного author (`:158`); source created_at сохраняется, но updated_at тоже заменяется created_at (`:180`); audit actor всегда импортирующий author (`:200`). История строк и часть дат сохраняются, происхождение событий — нет. Существующий тест этого importer подтверждает его заявленную семантику, но не является проверкой lossless DB migration.

**Общий SQLite → PostgreSQL helper требует отдельной проверки для этого scope.** `apps/core/postgresql_migration.py:18` исключает auth_group_permissions/auth_permission/content_types/admin log/sessions; `current_schema_tables` использует эти исключения (`:98`). Поэтому он не подтверждает сохранность заявленных permissions, а перенос `accounts_user_user_permissions` без mapping Permission PK может привязать неверные права/нарушить FK. Сборщик пересекает source/target columns (`:142`), а importer подставляет defaults для отсутствующих обязательных колонок (`:315`), что не равно проверке отсутствия потерь. Manifest хранит counts/columns и источник (`:187`), но не полноценную проверенную матрицу полномочий. `--replace` для PostgreSQL использует TRUNCATE CASCADE (`:298`) и потому может затронуть данные за пределами выбранных таблиц. Никакие эти команды в аудите не запускались; область действия должна быть уточнена до применения.

## 6. Предлагаемые проверки до переключения (не выполнены)

### Идентификаторы и происхождение

- Зафиксировать приватный manifest: installation/source snapshot ID, версия/commit кода, applied migrations, engine/version, schema fingerprint, момент согласованного снимка/окна записи, список таблиц/колонок, backend role document, Git default hash и runtime override revision/hash, timezone/encoding. Без содержимого персональных строк в публичном отчёте.
- Для восстановления в пустую совместимую БД сохранять PK всех бизнес-объектов, M2M, UUID и audit references. При необходимости нового ID — явная one-to-one карта `(source installation, model, source PK) → target PK`, отдельные проверки всех FK и текстовых внешних ссылок. Не сопоставлять User по совпавшим ФИО/email, Department по одному name/OID, Device только по nullable inventory number.
- Проверить точные множества `(entry PK, external_id)`, `(entry PK, author_id)`, `(audit PK, entry_id, actor_id, timestamp)`, user↔department, device↔department, group memberships и natural-key permissions. В отчёт — только результат/число нарушений.
- Не модифицировать исторические audit actor, timestamps/correlation и source при restore; не делать вид, что импортёр был автором исходных событий.

### Counts, hashes и целостность

- Сравнить counts всех включённых таблиц и M2M; распределение Waiting List по status/service/cito, число NULL author, число history rows на entry и времена min/max; пользователей по flags и role memberships; equipment archive state и подразделения. Счётчик сам по себе не доказывает равенство.
- Приватно сравнить детерминированные хеши канонических записей/наборов с сортировкой по устойчивому PK; DateTime привести к UTC с одинаковой точностью, JSON сортировать по ключам, UUID к единому виду, различать NULL/empty string. Для персональных данных использовать закрытый manifest/HMAC, не публиковать сырые значения или отдельные легко перебираемые digest пациентов.
- Два вида контроля: файл backup/export SHA-256 для целостности артефакта и canonical row/set hashes для равенства данных после restore. При upgrade явно перечислить разрешённые schema/data deltas; всё остальное — 0 различий.
- Zero orphan FK: entry.author, audit.entry/actor, user.department, department.parent, device.department, memberships и permissions, audit actor/target, ExternalIdentity.user, RuntimeSettingDocument.updated_by и SettingsChange.rollback_of/comments. Zero duplicate external_id, usernames, identity unique tuples; ни циклов Department, ни потерянных предков.
- Проверить timezone/дату рождения/даты цели и окончания без сдвигов, допустимые source status/service values, constraints дат; optional old-schema columns нельзя терять без явной карты преобразования.
- После сохранения explicit IDs reset sequences и отдельная пробная запись в изолированном восстановленном контуре: новые User/Entry/Audit/Device не конфликтуют с max PK. Эта проверка не выполняется в production в рамках аудита.
- Проверить комплект резервирования и restore в чистую изолированную БД с целевым кодом. Полный backup source до преобразований нужен независимо от selective export; резервный архив должен быть читаем/восстановим, а не только существовать.

### Поведение и возможность возврата

- На восстановленном контуре подтвердить вход Local/AD/IIS согласно выбранному deployment, fresh inactive/revoked user deny, roleless deny, explicit waiting grants, чужую authored запись deny, global state graph, audit события после разрешённой записи, forbidden role/flag escalation и наличие минимум одного активного superuser.
- Сопоставить итоговые решения прав с исходным контуром на синтетической/разрешённой матрице users×roles×actions, включая no-role/inactive/protected/technical groups. Сохранность memberships не доказывает сохранность авторизации при смене role_rules.
- До cutover удерживать один писатель; подтвердить финальный snapshot после остановки/окна без записи. Нельзя принимать source и target записи одновременно без стратегии reconcile. Возврат до возобновления записи — исходный контур+исходный snapshot. Возврат после новых productive writes требует отдельной процедуры обратной сверки, его нельзя обещать простым restore старой копии.

## 7. Открытые вопросы перед реальным переносом

1. Каковы source commit/applied migrations и СУБД (Windows + IIS не определяют SQLite/PostgreSQL)? Нужен разрешённый read-only manifest исходной схемы без patient data в отчёте.
2. Куда переносим: та же БД после обновления, новый PostgreSQL, иной target? Чистая БД или есть данные с пересекающимися ID?
3. Режим входа: Local/LDAP/remote_user/hybrid; есть ли реальные ExternalIdentity и технические AD группы? Какие приватные IIS/AD настройки должны остаться совместимыми?
4. Что означает «права»: бизнес-role document, все Django permissions, audits и settings history? Для сохранения текущего поведения минимально нужны оба механизма полномочий; история также включена в предложенный набор.
5. Какой actual role document backend (legacy file или DB allowlist), есть ли незавершённые pending/inconsistent SettingsChange? Их нельзя автоматически «починить» копированием defaults.
6. Включены ли notification preferences, существуют ли Memory/Analytics projections, вложения старой версии или иные user data? Они условны и не выводятся из заявления «используется только Waiting List» без инвентаризации.
7. Нужна ли непрерывность производных patient псевдонимов/URLs? Тогда согласовать политику ключа и ID отдельно; секрет не запрашивать в чате и не сохранять в репозитории.
8. Окно приостановки записи, допустимое время простоя, хранение резервов и критерии rollback после новых записей ещё не зафиксированы.

Этот аудит завершает статическое определение границ. Он не является приёмкой production migration, разрешением удалить другие таблицы или утверждением об уже выполненном backup/restore.

## Проверка на Windows-сервере

Это следующий эксплуатационный шаг P0, пока **не выполненный**. Владелец
подтвердил отсутствие доступа к серверу из среды агента. Утилита подготовлена,
но перенос приложения/БД и обновление исходного сервера ради её запуска не нужны.

1. Оператор использует текущий Python исходной установки и её настройки.
   [host_inventory.py](../../../../workflow/active/lbs-factory-p0/host_inventory.py)
   копируется отдельно в `.local/lbs-factory-p0/host_inventory.py` исходного
   проекта. Утилита не требует установки нового приложения или зависимостей.
2. Запустить в PowerShell, подставив **приватный** путь установки:

   ```powershell
   $LbsProjectRoot = "<каталог текущей установки>"
   Set-Location $LbsProjectRoot
   & "$LbsProjectRoot\.venv\Scripts\python.exe" `
     "$LbsProjectRoot\.local\lbs-factory-p0\host_inventory.py" `
     --project-root $LbsProjectRoot
   $LASTEXITCODE
   ```

   При другом расположении Python использовать фактический интерпретатор IIS.
   Настройки отдельного процесса должны совпадать с IIS environment: запуск
   `config.settings` сам по себе **не доказывает**, что работающий worker
   использует те же environment variables/версию кода. Это сверяет оператор.
3. Результат — `.local/lbs-factory-p0/host-inventory.json`. В нём только
   кодовый SHA, известные параметры режима, тип БД, количества строк известных
   таблиц, контрольные отпечатки состояния миграций и документа ролей.
   Значения пациентских полей, имена пользователей, пароли/токены, адреса серверов,
   строки подключения и содержимое role document не экспортируются.
4. Утилита не запускает check/migrate/bootstrap/reindex и не экспортирует строки.
   PostgreSQL-сессия переводится в read-only repeatable-read транзакцию;
   SQLite открывается `mode=ro` и `query_only=ON`. Запись результата разрешена
   только в `.local/`; приложение и его конфигурация не меняются.
5. Код выхода 0 означает, что доступная часть сбора сведений завершилась.
   Код 1 означает ошибку/недоступные обязательные таблицы или документ ролей,
   код 2 — ошибку аргументов. Ошибки в отчёте содержат **тип**, без потенциально
   чувствительного текста исключения. На старом коде новый settings registry
   может отсутствовать: это основание отдельно снять backend, не считать его
   пустым или Git-default. Успех утилиты не доказывает успешный перенос.
6. Дополнить закрытый операторский протокол: версия Windows/IIS/Python и
   активный путь установки; используемый способ SSO/AD и verified identity
   linking; какая именно конфигурация worker применена; references штатных
   резервных копий и последней проверки восстановления. Секреты и дамп БД
   остаются в защищённом deployment/backup хранилище, **не в Git и чате**.

Самостоятельно проверить, есть ли данные memory/source_data/индексов/knowledge
Git и нужны ли они вообще. Нулевые counts сами по себе не исключают внешние
файловые индексы. Не открывать реальное содержимое через LLM для инвентаризации.

**Проверка самой утилиты локально:** выполнены чтение отдельной копии SQLite,
сравнение SHA256 БД до/после (не изменилась) и отказ записи отчёта вне `.local`.
Это не Windows/PostgreSQL-проверка. Окончательные результаты — VERIFICATION.

## Локальный снимок и план восстановления

Основной агент сохранил код исходного HEAD, consistent SQLite backup API-снимок
и файловый `data/` (включая `.git` Wiki) в закрытом локальном каталоге
`.local/lbs-factory-p0/snapshot/`. Контрольные суммы — в соседнем
`local-snapshot.json`. Полная конфигурация хоста и секреты туда не копировались.
Файловый архив локального стенда не заявлен как атомарный snapshot активного
сервера: в работе Windows/IIS требуется согласованная точка резервирования.

Локальная копия распакована отдельно в `.local/lbs-factory-p0/restore-check/`,
база прошла integrity/FK и сравнение counts по 80 таблицам; knowledge Git — fsck.
Рабочий `data/` не заменялся. Reconcile в восстановленной копии не запускался:
его current known gaps и незаданные пути индексов не позволяют считать его
безопасным восстановлением одним изменением DATA_DIR. Это проверка восстановления
снимка, **не** полная проверка запуска приложения после аварии.

Для production перед переносом:

1. Снять SHA исходного кода, migration state, реальный backend/config roles и
   минимальный состав выше; отдельно учесть версии схемы и custom extensions.
2. Согласовать короткое прекращение записей Waiting List; сохранить БД и
   необходимые файлы/настройки согласованным backup, проверить контрольные суммы.
   PostgreSQL — штатный dump/snapshot; SQLite — backup API либо согласованная
   остановка писателей, а не случайная копия открытого файла без WAL.
3. Восстановить **отдельную** приватную копию, не перезаписывая исходник.
   Сверить counts, идентификаторы и FK; закрытые канонические хеши переносимых
   строк/истории/назначений; действующие роли и permissions по естественным ключам.
4. Проверить вход IIS/AD, врачебный просмотр, собственные изменения и отказ чужой
   записи, временные метки и аудит. Если есть миграционный delta вроде заполнения
   обязательного Department — перечислить его отдельно, не скрывать расхождение.
5. Перед переключением дать заключение по исходным данным, преобразованиям,
   новым миграциям, исключениям и сохранению пользователей/прав. Переключение и
   конкретный способ переноса требуют отдельного этапа; P0 их не исполняет.
6. До возобновления записей откат возвращает согласованную исходную установку
   и её backup. После новых записей в целевой БД нужен перенос дельты/разбор;
   простое переключение на старую копию потеряет новые события. Исходный backup
   не удаляется до отдельной приёмки и завершения окна отката.

Ни существующий текстовый импорт, ни общий SQLite→PostgreSQL helper пока
не принимаются как достаточный перенос заявленного scope. Выбор между полным
совместимым восстановлением и выборочным переносом с mapping делается после
отчёта хоста и сравнения схем. Исключение Kanban/Warehouse business rows не
означает немедленное удаление их приложений/таблиц из графа Django migrations.
