# Executor report: memory review scope

## Результат

Закрыты границы очереди ревью памяти и прямых сервисных вызовов:

- любой memory actor обязан быть сохранённым активным пользователем; это правило применяется также к активному superuser и техническим группам;
- `role:<code>` выдаётся только для ролей из текущего snapshot `role_rules`, остальные Django/AD-группы получают `group:<name>`;
- организационное accept/reject требует одновременно технической возможности `review_issues` и продуктового `memory_organization_review`;
- `adapter_check` проверяется при выборке и повторно непосредственно перед изменением; неизвестный адаптер, режим или исключение дают отказ;
- issue/document/pending write-path перечитывает и блокирует actor и target внутри транзакции, после чего повторяет проверки полномочий;
- текущие и предлагаемые `scope_tokens` frontmatter проверяются при accept/reject;
- source-wide issues/jobs не получают доступ через один видимый объект, а задания с пустым `source_code` скрываются для обычных операторов;
- история git-коммитов и access-аудит фильтруются по видимой области, личная история чужого пользователя не раскрывается;
- список assignee ограничен активными операторами с техническим правом и доступом к целевому объекту;
- `render_source_object_text` работает только с активным actor и не возвращает кешированный текст при отказе адаптера; digest без actor и без явной области запрещён;
- для JSON scope-массивов увеличен защитный positional fallback до 256 элементов вместо прежних 16.

## Изменённые файлы

- `apps/memory/policies.py`
- `apps/memory/acl.py`
- `apps/memory/review_selectors.py`
- `apps/memory/review_services.py`
- `apps/memory/services.py`
- `apps/memory/knowledge_files.py`
- `apps/memory/views.py`
- `apps/memory/tests/test_policy_and_privacy.py`
- `apps/memory/tests/test_ingestion.py`
- `apps/memory/tests/test_review_boundaries.py`

Runtime-контракты, базу и Git не изменял; commit/push не выполнял.

## Проверки

Последние два последовательных запуска:

```text
.venv/bin/python manage.py test apps.memory.tests.test_review_boundaries --verbosity=1
Ran 7 tests ... OK

.venv/bin/python manage.py test apps.memory.tests.test_ingestion --verbosity=1
Ran 9 tests ... OK
```

Перед ними объединённый прогон `test_policy_and_privacy`, `test_admin_and_review_ui`, `test_ingestion` выявил один устаревший ожидаемый `role:privacy-readers`; ожидание обновлено на `group:privacy-readers`. Два первоначальных теста старого формата токенов также обновлены. После этого узкий `test_ingestion` прошёл.

## Остаточные риски и границы

- Полный memory/UI профиль и полный прогон не запускались по ограничению пакета; итоговую приемку выполняет основной агент.
- `memory.source.acl_mode` в `apps/memory/settings_descriptors.py` по-прежнему не имеет `settings_path`; это отдельная задача центра настроек и не исправлялась в этом пакете.
- Positional fallback ограничен 256 элементами; контрактный валидатор должен сохранять разумный верхний предел списка областей, иначе потребуется перенос фильтрации на полноценный JSON-overlap lookup.
- Filehub source/proposal/move boundaries остаются отдельным пакетом 17b-C.

## Correction 17b-B

После независимого критического аудита дополнительно исправлено:

- `is_staff` и Django `has_perm` больше не дают memory-полномочия; операторские возможности выдаются только активному superuser или явным техническим группам из `MEMORY_REVIEW_GROUP_CAPABILITIES`, а общее управление — `memory_admin`;
- read-policy использует свежий active actor snapshot с prefetched groups; селекторы передают этот snapshot через одну операцию;
- scope объекта теперь учитывается вместе с ACL/source fallback, а cached safe text не возвращается при foreign scope;
- mixed querysets сохраняют source-wide строки при фильтрации object rows;
- memory jobs сопоставляются по точной паре `source_code + object_id/document_id`, source-wide fallback разрешён только без object/document target;
- assignee повторно выбирается `select_for_update`, проверяет active/technical/scope, а список assignees проверяет полномочия самого actor;
- review action и accept/reject сериализуются общим `access_control_write_lock_path` вне внутренней `transaction.atomic`;
- публичный digest требует actor даже при переданных `scope_tokens`;
- `_jobs_for_document` стал actor-aware и возвращает пустой набор без подтверждённого доступа к документу.

Correction-тесты добавлены в `apps/memory/tests/test_review_boundaries.py`, но по запросу критика до отдельного разрешения не запускались. Статически выполнены `compileall` и `git diff --check`.

## Correction 17b-B после FAIL 12/12

Внесены дополнительные исправления в прежнем scope (без commit/push и без изменения runtime data):

- `resolve_active_actor(..., force_refresh=True)` добавлен для security-sensitive чтений; `can_access_source_object` передаёт в scope/adapter именно свежий actor, поэтому stale superuser после demotion или revoke не сохраняет доступ;
- `read_search_document_text` теперь требует активного actor и `can_access_search_document`; при отказе выбрасывается `PermissionDenied`, filename/path/object id не возвращаются, внутренний retrieval-вызов передаёт actor;
- ACL со статусом `unresolved`/`blocked`/`unreadable`/`disabled` закрывается по умолчанию; разрешены только явные политики `admin_only`/`root_only` или `fallback_scope_rule`, а selector object-scope больше не отбрасывает ACL fallback предварительным JSON-фильтром;
- unrestricted `recent_knowledge_commits` сделан приватным; actor-bound feed читает `--name-only` полного commit и отбрасывает commit с любым foreign personal path или смешанным непредусмотренным путём;
- прямые issue/document detail и queue-item helpers сами проверяют actor scope и закрываются через `PermissionDenied`; mismatched `issue.source`/`issue.source_object.source` отфильтровывается на чтении и блокируется при записи/reindex;
- добавлены регрессионные проверки stale superuser, anonymous/foreign document read, unresolved ACL, mixed git commit, direct hidden contexts и mismatched issue в `apps/memory/tests/test_review_boundaries.py`.

Проверки этой коррекции выполнены только статически:

```text
AST compile OK: 7 files
git diff --check: OK
```

Тесты после последней коррекции намеренно не запускались: критик запросил сначала завершить код и дождаться отдельного разрешения на узкий последовательный прогон. Остаточный риск — runtime/test-интеграция этих новых границ ещё требует такого прогона и финальной приемки основного агента.

## Correction 17b-B: повторный критик

- discovery теперь сохраняет эффективный `profile.unresolved_acl_policy` в `metadata.acl.unresolved_policy`; это различает `admin_only` (доступ только `role:superuser`) и `block` (отказ также superuser);
- публичные selectors и внутренние source-wide decisions принудительно получают actor через `resolve_active_actor(..., force_refresh=True)`, включая `_scoped_issue_queryset` и `_visible_source_ids_for_user`;
- Git `--name-only` parser переведён на separator в начале записи, поэтому paths остаются в сегменте своего commit; добавлен regression-тест с реальным временным Git repository для mixed и own commits;
- добавлены тесты discovery ACL policy и stale marked actor после revoke группы.

После этой коррекции тесты не запускались по инструкции. Статические проверки выполняются отдельно перед handoff.

## Финальная приемка основным агентом

- прямые и экранные чтения перечитывают активного пользователя и состояние
  источника; `DISABLED` закрыт также для суперпользователя;
- публичные селекторы и adapter-helper не образуют обход общей политики;
- read fallback не создает `MemorySearchDocument` и не изменяет индекс;
- целевая итоговая матрица: 95 тестов и 32 вложенных сценария;
- memory-профиль: 153 теста и 61 вложенный сценарий;
- независимый критик: `PASS`, незакрытых S1/S2 нет.
