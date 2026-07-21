# Executor Report: 01-contract-read-write-consistency

Дата: 2026-07-05.
ADR: `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md` (разделы «Решение» п.1-2, «Реализационные правила»).

## Что сделано

### 1. Contract store (`apps/core/contract_store.py`, новый модуль)

- `get_contract(name)` для контрактов `role_rules`, `workflow_rules`, `workorder_status_colors`.
  Путь берётся из `settings.LOCAL_BUSINESS_*_FILE` (env-override уважается — settings.py уже
  применил его к этим константам).
- Кэш per-process; ключ инвалидации — строго кортеж `(st_mtime_ns, st_size, st_ino)`
  (один `stat()` на обращение).
- Семантика ошибок по ADR: первое чтение после старта при битом/невалидном файле —
  исключение `ContractStoreError` наверх (fail-fast); последующие ошибки — возврат последнего
  валидного payload, лог ERROR, выставление сигнала деградации.
- `get_degradation_state()` — видимый сигнал деградации; `/health/details/`
  (блок `services.contracts`, см. `apps/core/health_views.py`) выполняет **активную**
  проверку: проходит `get_contract()` по всем зарегистрированным в store контрактам
  (`registered_contracts()`) — при неизменном файле это один `stat()` на контракт —
  и отражает фактическое состояние рабочих копий, а не только пассивный флаг текущего
  воркера (доработка M3 по итогам независимой проверки). Для Settings Center минимально
  достаточная точка интеграции — `get_degradation_state()` (по постановке).
- `normalized_hash(payload)` / `current_contract_hash(name)` — sha256 нормализованного
  (`pretty_json`, sort_keys) представления для оптимистической проверки записи.
- Валидация payload при (пере)чтении — существующими валидаторами из `apps.core.json_utils`.

### 2. Снимок на время HTTP-запроса

`get_contract(name, request=...)` кэширует payload на объекте запроса
(`request._contract_snapshots`): контракт читается один раз на запрос. Применено в
`RoleRulesUpdateView` (GET-контекст и POST). В точках без доступного request используется
простой `get_contract()` — постановка это явно допускает («в местах без request — просто
get_contract()»); согласованность в пределах запроса там обеспечивает процессный кэш по
ключу метаданных.

### 3. Переведённые точки чтения (только role_rules / workflow_rules / workorder_status_colors)

- `apps/workorders/policies.py` — `role_rules()`, `workflow_rules()` → store.
- `apps/memory/policies.py` — `_user_has_role_flag` → store (memory-контракты не тронуты).
- `apps/ai/skill_authoring.py` — `can_manage_ai_skills` → store.
- `apps/ai/services.py` — `update_role_permissions_for_actor` и `get_role_rules_for_actor` → store.
- `apps/accounts/management/commands/seed_roles.py` → store.
- `apps/core/views.py` — контекст формы ролей → store (со снимком на запрос).
- `apps/workorders/views.py` — `_workorder_status_color_style` → store (см. «Отклонения»).
- `config/settings.py` не менялся: константы продолжают загружаться для обратной
  совместимости остальных мест (AI/memory/analytics-контракты — вне пакета);
  переведённые точки их больше не читают.

### 4. `RoleRulesUpdateView.post` — единственный путь записи

Переведён на `apps.settings_center.contract_services.apply_contract_payload`
(setting_id `core.contract.role_rules`): валидация, атомарная запись, `SettingsChange` audit,
плюс `base_hash` от прочитанной версии. Убраны shallow `.copy()`-мутация и прямое
присваивание `settings.LOCAL_BUSINESS_ROLE_RULES`. Ошибка валидации показывается через
`messages.error` без изменения файла. Выбран вариант «перевести view на service layer»
(а не замена страницы ссылкой на Settings Center) — сохраняет привычный упрощённый UI
при меньшем объёме изменений в шаблонах/маршрутах.

### 5. `_refresh_inprocess_setting` удалён

Вместе с вызовом в `apply_contract_payload`. Согласованность между процессами теперь
обеспечивает store. Metadata-ключ `settings_payload_attr` в дескрипторах перестал
читаться кодом; сами дескрипторы (в т.ч. ai/memory) не трогал — вне scope, кандидат
на чистку следующими пакетами.

### 6. Оптимистическая проверка записи

`apply_contract_payload(..., base_hash=None)` — обратная совместимость сохранена.
При переданном `base_hash` сравнивается sha256 нормализованного текущего файла;
при несовпадении — `ValidationError` с предложением перечитать.

- **UI-форма ролей** (доработка M2 по итогам независимой проверки): хеш отрисованной
  версии кладётся в контекст в `get_context_data` и уходит в шаблон
  `templates/core/role_rules_form.html` hidden-полем `base_hash`; `post()` берёт его из
  `request.POST`. Это закрывает классический lost update «два администратора открыли
  форму, второй сохранил позже», а не только гонку одновременных POST. Отсутствие поля
  (прямой POST без формы) означает запись без проверки — обратная совместимость.
- **AI-инструмент** `update_role_permissions_for_actor` передаёт хеш версии, прочитанной
  перед формированием правки.

### 7. Docstring `update_role_permissions_for_actor`

Обновлён: утверждение «AI-инструмент и UI используют один и тот же путь записи» теперь
соответствует действительности (оба идут через `apply_contract_payload`).

### Документация и структура

- `docs/guides/SETTINGS_CENTER_OPERATIONS.md` — новый фрагмент в разделе Runtime Contracts:
  store и ключ инвалидации, единственный путь записи, `base_hash`, активная проверка и
  сигнал деградации в `/health/details/`, предупреждение о legacy-копиях `role_rules`
  без backward-compat ключей (M1).
- `apps/core/.desc.json` + `make gen-struct` (`PROJECT_STRUCTURE.yaml`) — регистрация
  нового модуля `contract_store.py` по протоколу AGENTS.md.

## Выбранный вариант неизменяемости payload

**Глубокая копия** (`copy.deepcopy` кэшированного payload при каждом `get_contract`).

Почему не read-only обёртка: `MappingProxyType` поверхностна (вложенные dict/list остаются
мутабельными), а полноценная рекурсивная обёртка — это собственный класс с ценой
сопровождения и сюрпризами для вызывающего кода (`isinstance`-проверки, json-сериализация).
Контракты пакета маленькие (единицы килобайт), частота чтений умеренная — цена копии
пренебрежима. Выбор закреплён тестом
`ContractStoreTests.test_returned_payload_mutation_does_not_corrupt_cache`: мутация
возвращённого payload (включая вложенные структуры) не влияет на следующее чтение.

Дополнительно store валидирует копию payload (а не кэшируемый объект), потому что
`validate_role_rules_payload` нормализует payload на месте (`setdefault` обратной
совместимости) — кэш и хеш всегда соответствуют фактическому содержимому файла.

## Тесты (8 пунктов пакета)

| Пункт пакета | Тест |
| --- | --- |
| Инвалидация кэша по ключу метаданных | `apps.core.tests.ContractStoreTests.test_cache_invalidates_on_metadata_key_change` |
| Два независимых «воркера» видят изменение после `apply_contract_payload` | `ContractStoreTests.test_independent_workers_see_change_after_apply` |
| Мутация возвращённого payload не влияет на следующее чтение | `ContractStoreTests.test_returned_payload_mutation_does_not_corrupt_cache` |
| Битый файл: первое чтение — fail-fast; после валидного — последний валидный + деградация | `ContractStoreTests.test_first_read_of_broken_file_fails_fast`, `ContractStoreTests.test_broken_file_after_valid_read_serves_last_valid_and_flags_degradation`, плюс `DiagnosticEndpointTests.test_health_details_reports_contract_store_degradation` (отражение в `/health/details/`) |
| Запись с устаревшим хешом отклоняется | `apps.settings_center.tests.SettingsCenterContractTests.test_apply_with_stale_base_hash_is_rejected`; сценарий lost update через UI-форму (GET → конкурентная запись → POST со старым hidden-хешом → отказ) — `DepartmentViewTests.test_role_rules_form_rejects_lost_update_with_stale_hidden_hash` |
| Невалидный role_rules через UI-форму отклоняется, файл не меняется | `apps.core.tests.DepartmentViewTests.test_saving_invalid_role_rules_via_ui_is_rejected_and_file_unchanged` |
| Запись через UI-форму создаёт SettingsChange | `DepartmentViewTests.test_saving_role_rules_via_ui_creates_settings_change` |
| Regression: существующие тесты settings_center и core зелёные | полный прогон (см. ниже) |

Адаптированы существующие тесты, которые полагались на удалённый механизм:

- `apps/workorders/tests.py` — два теста переопределяли payload-константу
  (`LOCAL_BUSINESS_ROLE_RULES` / `LOCAL_BUSINESS_WORKFLOW_RULES`); теперь через хелпер
  `_override_contract_file` подменяется `*_FILE`-путь и сбрасывается кэш store.
- `apps/settings_center/tests.py` — проверка «settings обновлён после apply» заменена
  на проверку через `get_contract` (согласованность обеспечивает store, а не
  присваивание в текущем воркере).

## Команды проверок и фактические результаты

1. `.venv/bin/python manage.py test apps.core.tests apps.ai.tests apps.settings_center.tests apps.workorders.tests apps.memory.tests`

   Результат (полный набор, до доработок M2/M3): `Ran 305 tests in 523.480s — OK`
   (независимая проверка получила тот же результат: 305/305 OK).

   После доработок M2/M3 (hidden `base_hash` в форме, активная health-проверка) прогнан
   затронутый scope `apps.core.tests apps.settings_center.tests apps.workorders.tests`:
   Результат (прогон выполнен оркестратором — сессия исполнителя оборвалась на лимите):
   `Ran 126 tests in 339.636s — OK`; `validate_architecture_contracts` — valid;
   `manage.py check` — 0 issues.

2. `.venv/bin/python manage.py validate_architecture_contracts`

   Результат: `Architecture contracts are valid.`

3. `grep -rn "settings.LOCAL_BUSINESS_ROLE_RULES" apps/ --include='*.py' | grep -v tests`

   Результат — только допустимые `*_FILE`-вхождения (пути, не payload):

   ```text
   apps/core/forms.py:41: settings.LOCAL_BUSINESS_ROLE_RULES_FILE.read_text(...)
   apps/core/management/commands/validate_architecture_contracts.py:58: load_json_file(settings.LOCAL_BUSINESS_ROLE_RULES_FILE)
   ```

   Дополнительный grep по `WORKFLOW_RULES` / `WORKORDER_STATUS_COLORS` (payload, вне тестов):
   осталось одно чтение `settings.LOCAL_BUSINESS_WORKFLOW_RULES` в
   `apps/core/forms.py:49` внутри `RoleRulesForm` — форма стала мёртвым кодом
   (см. «Остаточные риски»); `apps/settings_center/contract_services.py` и
   `validate_architecture_contracts` читают workflow-файл через `load_json_file(*_FILE)`
   (путь записи/диагностика — свежий файл, не settings-payload).

## Отклонения от постановки

1. **Файлы вне write_scope JSON-пакета, изменённые по прямому тексту постановки исполнителю:**
   - `apps/accounts/management/commands/seed_roles.py` — назван в постановке явно;
   - `apps/core/health_views.py` — требование «сигнал деградации, который читают health view»;
   - `apps/workorders/views.py` — единственное оставшееся чтение payload
     `LOCAL_BUSINESS_WORKORDER_STATUS_COLORS`; без него acceptance-требование
     «все чтения трёх контрактов вне тестов переведены» не выполняется (правка — 3 строки);
   - `apps/workorders/tests.py` — адаптация двух существующих тестов, сломанных удалением
     payload-override механики (иначе regression-пункт пакета красный);
   - `templates/core/role_rules_form.html` — hidden-поле `base_hash` (доработка M2 по
     замечанию независимой проверки; без правки шаблона защита от lost update формы
     нереализуема);
   - `apps/core/.desc.json`, `PROJECT_STRUCTURE.yaml` (через `make gen-struct`) —
     регистрация нового модуля по обязательному протоколу AGENTS.md.
2. **Кросс-валидация на пути чтения отключена.** Store валидирует каждый контракт автономно
   (`validate_role_rules_payload` без `workflow_payload`). Каскадная зависимость чтения
   role_rules от workflow_rules давала бы ложную деградацию/fail-fast при рассинхроне пары
   (и ломала существующий тест матрицы переходов). Кросс-валидация пар сохраняется на пути
   записи (`VALIDATORS` в contract_services), при старте процесса (`config/settings.py`) и в
   `validate_architecture_contracts`. Это уточнение трактовки «валидация существующими
   валидаторами», зафиксировано комментарием в модуле.
3. **Индикатор деградации в Settings Center** реализован минимально достаточно по постановке:
   `get_degradation_state()` + отражение в `/health/details/`. Отдельный визуальный индикатор
   на страницах Settings Center не добавлялся (постановка: «минимально достаточно функции
   get_degradation_state() + отражение в /health/ payload»).

## Остаточные риски

- **Legacy-копии `role_rules` без backward-compat ключей (M1).** Store кэширует сырое
  содержимое файла, поэтому нормализация валидатора (`setdefault` ключей
  `view_analytics`/`manage_departments`/`manage_roles` от значения `manage_inventory`)
  больше не достигает читателей: на старой рабочей копии без этих ключей роли тихо
  не получат соответствующие права. Поведение fail-closed (права не расширяются),
  текущие рабочие и дефолтные копии полные. Рекомендация: при обновлении старых
  установок пересохранить `role_rules` через Settings Center — путь записи прогоняет
  payload через валидатор и дописывает недостающие ключи. Зафиксировано в
  `docs/guides/SETTINGS_CENTER_OPERATIONS.md`.
- `apps/core/forms.py:RoleRulesForm` стал мёртвым кодом (view больше его не использует)
  и содержит последнее payload-чтение `settings.LOCAL_BUSINESS_WORKFLOW_RULES`.
  Файл вне write_scope — не трогал; кандидат на удаление в следующем пакете/чистке.
- `config/settings.py` продолжает загружать payload-константы при старте (обратная
  совместимость непереведённых читателей AI/memory/analytics); новые чтения payload из
  settings запрещены ADR-0031 и контролируются grep-ом в review.
- Ключ `settings_payload_attr` в metadata дескрипторов больше не используется кодом;
  чистка затронула бы дескрипторы ai/memory вне scope.
- Ограничение среды из ADR: `data/` должна лежать на локальной ФС; на NFS/SMB инвалидация
  по метаданным не гарантирована (зафиксировано в ADR, требует отражения в
  deployment-документации в рамках пакета 08/документационных задач).
- Request-scoped снимок применён в точке с доступным request (форма ролей). Авторизационные
  policy-функции без request читают через процессный кэш: в пределах одного запроса версии
  могут разойтись только если запись файла произошла между двумя чтениями одного запроса —
  окно мало́; постановка допускает этот компромисс («в местах без request — просто
  get_contract()»).
