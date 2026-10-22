# P0: текущий AI runtime, реестры и доверие

Статический исходный отчёт P0; общий статус и результаты запусков — в
[проверках](VERIFICATION.md), навигация — [P0](../13_P0_BASELINE.md).


## Оглавление

- [Цепочка исполнения и владельцы](#цепочка-исполнения-и-владельцы)
- [Текущие журналы и машины состояний](#текущие-журналы-и-машины-состояний)
- [Реестры и конфигурационные границы](#реестры-и-конфигурационные-границы)
- [Доверие и ограничения](#доверие-и-ограничения)
- [AG-UI: локальная согласованность](#ag-ui-локальная-согласованность)
- [Существующие отрицательные проверки: точные pytest node IDs](#существующие-отрицательные-проверки-точные-pytest-node-ids)
- [Непросмотренные/неподтверждённые зоны](#непросмотренныенеподтверждённые-зоны)

Срез кода: `2c250ae30e496434e479043ad9db84c758bce0ba`, 2026-10-22. До чтения `git status --short` показывал только пользовательский untracked `drafts/Выгрузка.txt`. Источники: AGENTS.md, Factory 01/02/05 и указанный ниже код. Это статическая инвентаризация; тесты, обращения к production, чтение секретных конфигураций и изменения исполняемого поведения не выполнялись.

## Цепочка исполнения и владельцы

1. `apps.ai` владеет Django-моделями чата/хода/согласования/аудита. `ChatSession.user` задаёт личного владельца (`apps/ai/models.py:53`); отдельной групповой комнаты в этих моделях нет. `AIChatPrepareTurnView` требует Django login, активную собственную сессию, сохраняет ход под `run_id` с блокировкой строки (`apps/ai/views.py:659`, `:713`).
2. `AIChatRunView` проверяет thread/session, допускает один running ход, возвращает сохранённый результат terminal хода и завершает просроченный running как ошибку без повторного исполнения (`apps/ai/views.py:778`, `:808`, `:810`, `:829`). Сервер формирует actor payload (`:869`; `apps/ai/ui_runtime/actor.py:67`). Native и CopilotKit используют общий runtime-контур; протокол UI не является межагентным Task API.
3. FastAPI `/ag-ui` проверяет HMAC/TTL actor payload и signed session (`services/agent_runtime/app.py:139`, `:196`, `:215`, `:228`); `stream_agent` строит модель и tools для одного запроса (`services/agent_runtime/graph.py:173`, `:205`, `:231`).
4. LangGraph `@entrypoint()` (`services/agent_runtime/graph.py:316`) вызывает модель и инструменты циклом; вызов `agent.stream(history_messages, stream_mode="messages")` (`:341`) не передаёт checkpointer/thread config. В просмотренной реализации долговечного checkpoint store нет; история реконструируется из переданного history (`:327`). `@task` LangGraph (`:244`, `:251`) не означает Factory AgentTask.
5. Tools передают actor/session/correlation в `DjangoGatewayClient` (`services/agent_runtime/tools.py:7`, `services/agent_runtime/gateway_client.py:4`). Django gateway проверяет service token (`apps/ai/views.py:211`, `:1498`) и сверяет user_id с активной Django-учёткой, username и владельцем существующей сессии (`:278`). Затем `execute_tool` заново получает пользователя из БД (`apps/ai/tooling.py:347`; `apps/ai/services.py:184`), применяет runtime policy, для native проверяет running fence (`apps/ai/tooling.py:284`, `:351`), вызывает доменные сервисы (`:128`). Примеры предметных проверок: `apps/ai/services.py:491` WorkOrders, `:520` Waiting List, `:809` правила доступа.

## Текущие журналы и машины состояний

| Сущность | Назначение и пределы | Доказательство |
|---|---|---|
| ChatRun | prepared/running/completed/failed; unique session+run_id и один running на сессию; запись одного хода чата, не общий журнал делегирования | `apps/ai/models.py:115`, `:142` |
| PendingAction | pending/processing/confirmed/cancelled/expired/failed/reconciliation_required, сохранённый payload/actor/session и lease | `apps/ai/models.py:161` |
| Confirmation transition | текущая policy повторно проверяется перед claim; исполняется сохранённый payload; actor/session ownership; атомарный claim; неопределённый исход требует reconciliation | `apps/ai/tooling.py:616`, `:751`, `:795`, `:820`, `:907`, `:993` |
| AgentActionLog | actor, tool_code, вид/статус действия, payload, session/message; аудит существенного вызова | `apps/ai/models.py:209`; `apps/ai/services.py:640` |
| MemoryExternalConnectorJob | отдельная очередь памяти: unique idempotency_key, attempt_count, max_attempts, lock/retry, payload/result | `apps/memory/models.py:600` |

Ни ChatRun, ни PendingAction, ни MemoryExternalConnectorJob не следует объявлять уже существующим AgentTask: у общего будущего контракта нужны descriptor/provider lifecycle, права инициатора и агента, доверенное делегирование, проверяемые artifact refs и восстановление только реально долгих задач. Checkpoint провайдера не заменяет ledger (`docs/architecture/lbs-factory/01_CONCEPT.md`, разделы 3/6; `02_AGENT_INTERACTION.md`; `05_ROADMAP_AND_ACCEPTANCE.md`, P2).

## Реестры и конфигурационные границы

| Узел | Текущий владелец / поведение |
|---|---|
| Исполнимые AI tools | Python `TOOLS`, `get_tool_registry()` — верхняя граница (`apps/ai/tool_definitions.py:13`, `:609`). Delivered catalog может только сузить её; mode/confirmation сверяются (`apps/ai/config_documents.py:89`; `services/agent_runtime/config.py:54`). |
| AI policy/contracts | Пять закрытых document IDs registry/tools/task_types/models/chat_settings (`apps/ai/config_documents.py:21`). Settings Center repository выдаёт единый снимок (`:31`); `get_document_specs` описывает defaults/storage (`:255`, `:321`). Runtime принимает агрегат HTTP с hash/strong ETag и ограниченным last-known-good (`services/agent_runtime/contract_cache.py:1`, `:25`, `:34`). |
| Effective tools | static ∩ delivered ∩ task policy (`services/agent_runtime/config.py:169`); Django повторно применяет policy до side effect (`apps/ai/tooling.py:338`). Сейчас это AI policy, не универсальный catalog/loader всех Factory capabilities. |
| Module skills | `AgentSkillProvider` / `AgentSkillDescriptor`, in-process реестр `_SKILLS` (`apps/core/ai_skills.py:15`, `:95`). Apps регистрируют skills при ready, например `apps/workorders/apps.py:13`. |
| File/runtime skills | discovery объединяет модули и SKILL.md, модуль приоритетен (`apps/ai/skills_service.py:47`); content загружается отдельно (`:74`); required_tools сверяются с Python registry (`:117`). Авторинг пишет атомарно в `RUNTIME_CONTRACTS_DIR/ai/skills` под lock после повторной проверки прав (`apps/ai/skill_authoring.py:38`, `:157`). |
| Source adapters | Отдельный Protocol и in-process registry (`apps/core/source_adapters.py:146`, `:172`), не общий CapabilityResolver; приватность — profile/envelope (`:26`, `:88`). |
| MCP | `/mcp` смонтирован (`services/agent_runtime/app.py:168`), но бизнес-вызовы намеренно декорированы `_disabled_project_tool`, который НЕ регистрирует tool. Причина: shared credential без доверенного per-request principal (`services/agent_runtime/mcp_server.py:12`). Есть безопасные metadata resources skills/tools/modules (`:50`, `:74`, `:101`). Не выдавать наличие MCP transport за разрешённое внешнее исполнение. |
| Deployment interfaces | В корневом compose отдельно web, agent-runtime, copilot-runtime (`docker-compose.yml:16`, `:37`, `:51`); явного Factory component loader/profile optionality этот compose не доказывает. AI runtime читает data volume read-only (`:46`), gateway URL через environment (`:44`). Django INSTALLED_APPS: `config/settings.py:81`. |

Дублирование конкретных представлений tools/skills/policy реально есть; удалить его до проверки текущей security ceiling нельзя. Универсальные installed/enabled/allowed, контракт provider lifecycle и независимый resolver должны вводиться отдельно, с ADR и отрицательной проверкой отключённых функций.

## Доверие и ограничения

- Shared gateway credential удостоверяет сервисный контур; проверка валидности user_id не устанавливает отдельный внешний principal, installation binding или пределы полномочий делегированного агента. Поэтому новый A2A/Telegram/MCP нельзя подключать к этому пути простым переносом actor JSON. Текущие принятые ограничения MCP явно фиксируют этот зазор (`services/agent_runtime/mcp_server.py:12`).
- Поля actor.roles/is_superuser подписываются (`services/agent_runtime/app.py:115`), но доменные операции должны получать реальные права из БД, как делает `resolve_actor`, и перепроверять на side effect. Payload задания не authority.
- Confirmation через `confirmed_token` в `execute_tool` закрыт до dispatch; подтверждение только через сохранённое PendingAction (`apps/ai/tooling.py:324`). Отмена pending не означает откат уже совершённой предметной операции.
- Логи для UI сокращены до безопасного tool trace без args/results (`services/agent_runtime/graph.py:376`). Sanitization аудита: `apps/ai/services.py:665`; маскирование текста runtime: `:461`. Полная карта AI egress/privacy требует отдельной PRIV-00 сверки.

## AG-UI: локальная согласованность

`package.json` содержит прямую точную зависимость `@ag-ui/client: 0.0.55`; соответствующая root package-lock запись — `package-lock.json:68`. Прямые CopilotKit версии: `1.59.5`. Default `agui_profile` в `config/settings.py:693`, `services/agent_runtime/protocols/common/capabilities.py:4`, `apps/ai/ui_runtime/config.py:178` и `.env.example:54` — `ag-ui@0.0.55`.

Это сверка локальных pin/defaults, не проверка новейшего upstream и не значение реального production environment. Новые версии не выбирались; зависимости и wire contract не менялись. Перед реализацией серверных изменений провести AG-UI check по AGENTS.md.

## Существующие отрицательные проверки: точные pytest node IDs

Ниже идентификаторы из исходников, не результаты запуска:

```text
apps/ai/tests/test_native_execution.py::NativeExecutionTests::test_prepare_rejects_foreign_and_archived_sessions
apps/ai/tests/test_native_execution.py::NativeExecutionTests::test_run_rejects_forged_thread
apps/ai/tests/test_native_execution.py::NativeExecutionTests::test_completed_run_replay_does_not_call_runtime_twice
apps/ai/tests/test_native_execution.py::NativeExecutionTests::test_stale_running_run_fails_without_reexecution
apps/ai/tests/test_native_execution.py::NativeExecutionTests::test_native_gateway_fence_rejects_archived_and_failed_runs
apps/ai/tests/test_native_execution.py::NativeExecutionTests::test_proxy_does_not_forward_raw_tool_data_or_unknown_events
apps/ai/tests/test_views.py::AIViewsTests::test_tool_gateway_rejects_actor_mismatch_for_existing_session
apps/ai/tests/test_views.py::AIViewsTests::test_tool_gateway_rejects_inactive_user
apps/ai/tests/test_views.py::AIViewsTests::test_pending_action_rejects_actor_mismatch
apps/ai/tests/test_views.py::AIViewsTests::test_execute_tool_rejects_confirmed_token_before_dispatch
apps/ai/tests/test_views.py::AIViewsTests::test_removed_access_pending_actions_fail_closed_without_dispatch_or_mutation
apps/ai/tests/test_views.py::PendingActionConcurrencyTests::test_concurrent_confirmation_dispatches_once_and_writes_one_terminal_audit
apps/ai/tests/test_views.py::PendingActionConcurrencyTests::test_terminal_failure_after_dispatch_requires_reconciliation_and_is_audited
apps/ai/tests/test_contract_gateway.py::AIPolicyExecutionTests::test_django_execution_rejects_tool_outside_delivered_task_policy
services/agent_runtime/tests/test_contract_delivery.py::test_effective_policy_rejects_tool_outside_delivered_task_policy
services/agent_runtime/tests/test_contract_delivery.py::test_effective_policy_rejects_tool_omitted_from_delivered_catalog
services/agent_runtime/tests/test_normalization.py::TestAGUIRuntimeEndpoint::test_ag_ui_run_rejects_missing_actor_signature
services/agent_runtime/tests/test_normalization.py::TestAGUIRuntimeEndpoint::test_ag_ui_signature_binds_page_context_and_rejects_tampering
services/agent_runtime/tests/test_normalization.py::TestAGUIRuntimeEndpoint::test_ag_ui_run_rejects_expired_actor_signature
```

Доступные команды по Makefile, запускать ступенчато основному агенту/CI в согласованной тестовой среде:

```bash
make verify-fast TEST_SCOPE="apps/ai/tests/test_native_execution.py apps/ai/tests/test_contract_gateway.py services/agent_runtime/tests/test_contract_delivery.py"
make verify-profile PROFILE=ai
make verify-profile PROFILE=ui
# Крупная реализация, не обязательный прогон для данного статического отчёта:
make verify-full
```

`scripts/e2e/tests/native_ai_ui.spec.ts:17` содержит браузерную группу native AG-UI; `scripts/e2e/tests/copilotkit_sidebar.spec.ts:123` — отрицательный сценарий подписи. Браузерный прогон требует тестового deployment; здесь не выполнялся. Проверка static refs не является e2e.

## Непросмотренные/неподтверждённые зоны

- Реальный production/test host: активные services, effective environment, роли пользователей/внешние identity mappings, backups/restore и метрики latency/cost не обследованы. Default `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE=False` (`config/settings.py:620`) нельзя переносить на реальный хост.
- LDAP/OIDC/AD provisioning, весь accounts access control и revocation baseline — отдельный ACCESS-00 аудит.
- File/source_data/raw/privacy, legacy FTS/vector/reindex, Wiki Git и provider egress — отдельный PRIV-00 аудит; по текущему отчёту нельзя объявлять privacy gate пройденным.
- Не выполнена матрица Django migrations/imports/FK бизнес-модулей, отключения/re-enable, отсутствия optional provider, второго deployment profile и восстановления.
- Не проверены реальные LLM endpoint/credentials, фактические HTTP routes у внешнего proxy, shared gateway key rotation во внешней среде, полная CopilotKit Node proxy implementation.
- Существующих тестов достаточно для стартовой выборки, но они не доказывают будущие AgentTask delegation/installation/artifact/cancel/restart гарантии. Эти проверки нужны до P2 и внешних каналов.
