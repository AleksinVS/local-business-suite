# Отчёт исполнения 06: AI gateway и доставка agent-runtime

Статус: correction cycle после REJECT; финальные замечания Sol закрыты в
рабочей копии. Commit/push и production cutover не выполнялись.

## Реализовано

- Добавлен закрытый read-only gateway `GET /ai/gateway/contracts/` с service
  token, явными ID и фиксированным allowlist из пяти AI-документов. Неизвестные,
  повторные и пустые наборы возвращают непрозрачный 404; отсутствие и неверный
  token дают одинаковый 403. DB/repository ошибки дают безопасный 503 без
  payload и деталей исключения.
- Ответ gateway содержит `document_id`, `schema_version`, `revision`,
  `content_hash`, `payload`; strong ETag строится по отсортированным
  `document_id + schema_version + revision + content_hash`. Успешный 304 не
  содержит body и требует совпадающий strong ETag.
- Agent-runtime принимает только точный requested set, schema version 1,
  canonical SHA-256 payload hash и strong ETag. Полный LKG set заменяется одним
  атомарным переходом; network I/O находится вне state lock. Single-flight не
  задерживает параллельного caller при свежем LKG. Успешные 200/304 обновляют
  `last_validated_at`; stale age считается от последней валидации.
- Runtime diagnostics/startup/health содержат только source, age, revisions,
  hashes и безопасный error code. Старые path-based diagnostics удалены.
- Runtime graph замораживает один aggregate snapshot и передаёт его model,
  prompt, tools и task policy. Alias-нормализация и разрешение task policy
  читают delivered `task_types` из этого же snapshot; legacy in-code catalog не
  используется production runtime. Django AI consumers используют один
  request-local repository aggregate. `chat_settings` читается через
  repository и выпущен в DB backend release set. Static AI descriptors имеют
  `json_viewer`/`read_only`, а generic editor не может открыть их на запись.
- Effective tool capabilities являются пересечением статического Python-реестра,
  доставленного `tools` и mode-совместимых `task_types.allowed_tools`. Runtime
  проверяет policy до `tool.invoke`, Django проверяет её до создания pending
  action и повторно до подтверждения. Для helper tools выбирается
  точная/mode-совместимая task policy; отсутствие, конфликт или drift
  fail-closed. Confirmation берётся из этого же snapshot.
- Добавлены тесты запрета инструмента вне allowed task policy, подтверждения по
  snapshot и фильтрации `model.bind_tools`. Добавлен реальный persistent
  `RuntimeSettingDocument(chat_settings)` -> Django gateway ->
  `AgentContractCache` тест на in-process Django transport с последовательностью
  `200`, новой revision `200`, затем `304`. Health HTTP без LKG проверен с
  сериализацией `age: null`.
- DB-active документы больше не публикуют legacy `settings_path`; drift и
  `validate_architecture_contracts` используют только активный backend/snapshot,
  включая `waiting_list.contract.status_colors`.
- Git-static Settings Center detail отображает только JSON viewer. POST и
  прямой preview для `read_only` возвращают отказ и не создают `SettingsChange`.
- Удалены AI payload-константы из `config/settings.py`; Git-static документы не
  имеют legacy file path в AI spec. AG-UI/CopilotKit зависимости, profile и
  wire contract не менялись (`ag-ui@0.0.55`; найденная latest `0.0.59` не
  обновлялась).

## Изменённые файлы

- `apps/ai/config_documents.py`, `apps/ai/chat_settings.py`,
  `apps/ai/services.py`, `apps/ai/settings_descriptors.py`, `apps/ai/tooling.py`,
  `apps/ai/ui_runtime/config.py`, `apps/ai/views.py`, `apps/ai/urls.py`;
- `apps/ai/tests/test_contract_gateway.py`, `apps/ai/tests/test_views.py`,
  `apps/ai/tests/test_identity_context.py`,
  `services/agent_runtime/tests/test_contract_delivery.py`,
  `services/agent_runtime/tests/test_normalization.py`;
- `apps/settings_center/tests.py`, `apps/core/tests.py`;
- `apps/settings_center/document_registry.py` — только добавлен release ID
  `ai.contract.chat_settings`;
- `apps/settings_center/registry.py`, `apps/settings_center/contract_services.py`,
  `apps/core/contract_drift.py`, `templates/settings_center/setting_detail.html`;
- `apps/core/management/commands/validate_architecture_contracts.py` — точечная
  правка по запросу correction cycle: AI validators читают aggregate repository
  snapshot, а status aliases берутся из delivered task types;
- `config/settings.py` — только удалены пять AI payload-констант;
- `services/agent_runtime/config.py`, `contract_cache.py`, `prompting.py`,
  `mcp_server.py`, `graph.py`, `app.py`; MCP user-scoped project tools are not
  registered while the current shared transport lacks a trusted per-request
  principal; metadata resources remain available and AG-UI stays on the
  authenticated Django path;
- `services/agent_runtime/tools.py` — небольшой обязательный correction вне
  исходного узкого списка: параметр aggregate snapshot и фильтрация tools по
  delivered catalog;
- `services/agent_runtime/tests/test_contract_delivery.py`;
- `docs/guides/SETTINGS_CENTER_OPERATIONS.md` и
  `services/agent_runtime/README.md`;
- `workflow/active/settings-storage-simplification/.desc.json` и этот отчёт.

## Проверки

Запускался после `git status --short`, только с `--reuse-db`:

- `pytest services/agent_runtime/tests/test_contract_delivery.py apps/ai/tests/test_contract_gateway.py --reuse-db -q` — зелёный targeted набор, включая policy, health HTTP и DB -> Django -> cache;
- `pytest services/agent_runtime/tests/test_contract_delivery.py services/agent_runtime/tests/test_normalization.py --reuse-db -q` — зелёные delivered-tool intersection, MCP spoof-denial и no-LKG health проверки;
- `pytest apps/core/tests.py::ContractDriftTests --reuse-db -q` — зелёный drift-набор с DB-active gating;
- `pytest apps/settings_center/tests.py::SettingsCenterRegistryTests::test_git_static_contract_detail_is_json_viewer_only apps/settings_center/tests.py::SettingsCenterRegistryTests::test_git_static_contract_post_is_forbidden_without_settings_change apps/settings_center/tests.py::SettingsCenterContractTests::test_static_contract_preview_service_fails_closed_without_audit_row --reuse-db -q` — зелёные GET/POST/service preview проверки;
- `pytest apps/ai/tests/test_views.py apps/ai/tests/test_identity_context.py::IdentityContextPropagationTests::test_ai_chat_workorder_and_personal_memory_user_journey_tools --reuse-db -q` — зелёные policy-aware view и journey проверки;
- `pytest apps/ai/tests/test_views.py::AIViewsTests::test_pending_confirmation_requires_strict_boolean_and_keeps_pending apps/ai/tests/test_views.py::AIViewsTests::test_pending_confirmation_service_rejects_non_boolean_before_lookup --reuse-db -q` — зелёные HTTP/service проверки typed confirmation без изменения pending;
- `pytest apps/settings_center/tests.py::ProductSettingsAuthorityTests apps/settings_center/tests.py::SettingsCenterRegistryTests apps/settings_center/tests.py::SettingsCenterContractTests --reuse-db -q` — зелёные проверки DB-active path projection и read-only UI;
- `git diff --check` — успешно.

## Известные gaps и точные правки за пределами scope

- Локальные executor-проверки выполнялись на host SQLite с ``--reuse-db``;
  main-агент выполнил 84 runtime проверки зелёными, а также PostgreSQL
  gateway/views/drift/settings проверки зелёными. Отдельная БД не
  пересоздавалась.
- `test_normalization.py` получил явный delivered-contract fixture для prompt,
  alias и AG-UI unit-сценариев; полный файл проходит. Два старых memory file
  сценария в полном `test_identity_context.py` остаются за пределами пакета 06
  и требуют выравнивания с параллельным package 07 source-contract snapshot;
  production AI policy checks от них не зависят.
- За пределами исходного узкого списка точечно изменены
  `services/agent_runtime/tools.py` (явная передача snapshot), и
  `apps/core/management/commands/validate_architecture_contracts.py` (AI
  validators переведены на repository snapshot по отдельному запросу).
  Другие файлы, `data/`, `.env`, Docker, AG-UI и `TASK_ACCEPTANCE` не менялись.
- Обновлены `services/agent_runtime/README.md`, раздел AI gateway в
  `docs/guides/SETTINGS_CENTER_OPERATIONS.md` и этот report. ADR и
  `PROJECT_STRUCTURE.yaml` не требовали изменений: структура не менялась.
  AG-UI/CopilotKit/profile не обновлялись.
