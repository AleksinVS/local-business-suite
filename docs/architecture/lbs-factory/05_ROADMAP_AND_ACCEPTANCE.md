# Переход к LBS Factory v3.4: агентные пакеты и приёмка

Статус: **Accepted — согласованный план поэтапной реализации и критерии приёмки; работы по этому документу ещё не выполнены.** Запрещено молча менять production или удалять данные.

Отложено отдельным архитектурным долгом: [долг по ПДн в знаниях и Git](../../planning/active/knowledge-personal-data-git-policy-debt.md). Итоговая политика персональных данных в Git/знаниях не утверждена и **не** блокирует пилот на синтетических данных.

## 1. Последовательность с минимальной регрессией

### P0 — Сверка и решения (read-only)

**Цель:** понять фактический `main` на момент начала, состояние развёртываний и границы знаний/агентов.

**Состояние 2026-10-22:** [исходный отчёт P0](13_P0_BASELINE.md) и
[ADR-0052](../../adr/ADR-0052-factory-kernel-and-reference-portal.md) подготовлены.
Локальные исходные проверки выполнены; эксплуатационная часть остаётся открытой.
Владелец подтвердил одну продуктивную установку Windows + IIS с Waiting List;
сохраняемый состав — лист ожидания, пользователи, права, подразделения и
оборудование с зависимостями/историей. Доступа к хосту из среды агента нет;
подготовлена проверка для запуска оператором. Это не разрешение переноса или P1.

- перепроверить git SHA и git status;
- инвентаризировать `apps.memory`, `apps.ai`, `services.agent_runtime`, registry, policy, Django settings, read/write paths, ChatRun/PendingAction, source adapters, FTS/vector;
- **ACCESS-00:** снять baseline ролей, protected flags, org scopes, ACL, `accounts` ↔ `workorders` imports и назначений внешних identities; добавить негативные регрессионные тесты без изменения прав;
- проверить существующие тесты и конфигурацию `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE` реального тестового/production хоста отдельно (не выводить только из defaults);
- выполнить `PRIV-00`: снять карту raw/safe путей файлов, Source Adapters, `adapter_check`, FTS/vector/reindex/Wiki и AI egress, включая legacy проекции;
- записать ADR о LBS Factory и коррекцию ADR-0024 (Django owner только текущего внедрения, не всей Factory);
- подготовить список конфликтующих решений (ADR-0030, ADR-0013, ADR-0021, ADR-0048), не переписывать исторические документы без версии.

**Результат:** dependency map + approved ADR + baseline metrics + data backup/rollback plan.

### P1 — Wiki API и безопасный Discovery (первый вертикальный срез)

- локальный facade Knowledge API поверх `apps.memory`, без нового Wiki service; `save_working` выбирает provider по корпусу (LBS или CROW), без второго writer; до первой реальной Git-записи пройти PRIV-01/04;
- **немедленное** сохранение разрешённой рабочей информации в OKF v0.2 Wiki (через активный writer корпуса), без обычного human review; отдельно проверяются OKF `status`, `confirmation_state` и закрытый legacy `lifecycle: pending`;
- неблокирующий реестр needs_confirmation как проекция из канона, без второго источника истины;
- совместимость memory.remember/search и прежнего pending проверять golden tests;
- сохранность Git/индекса, минимум ACL и запрет секретов; для CROW дополнительно `raw/.archive/sync`, writer/read barrier; реальные source_data перед AI — только после PRIV-02/03 и необходимых проверок PRIV-05.

**Приёмка:** агент проводит серию интервью, записи доступны сразу; отмеченные сомнения видны в реестре, но не тормозят сбор; тестовый специальный `pending` не раскрывается; backup/restore работает. Продуктивных Wiki-данных для миграции нет.



### P1-CROW — CROW как optional Wiki provider при обязательном OKF v0.2

**Опциональный рабочий профиль, не блокирующий простую LBS-Wiki.** Подробные обязательные пакеты **CROW-00…06** и проверки определены [12_CROW_IMPLEMENTATION_PLAN.md](12_CROW_IMPLEMENTATION_PLAN.md); Accepted-контракт — [ADR-0051](../../adr/ADR-0051-crow-pluggable-okf-knowledge-provider.md), [11_CROW_OKF_INTEGRATION.md](11_CROW_OKF_INTEGRATION.md). Не вести ещё одну параллельную декомпозицию реализации CROW в этом файле.

**Порядок и границы первой очереди:**
1. Проверить отсутствие продуктивных Wiki-корпусов, pinned upstream, OKF v0.2, AGPL и synthetic baseline; до реальных ПДн отдельно решить [политику Git/raw](../../planning/active/knowledge-personal-data-git-policy-debt.md).
2. `PRIV-00..04` → единая source×destination SafeProjection **до** native CROW raw и внешнего classifier; тотальное PII-маскирование не утверждено.
3. Локальный `LbsCrowAdapter`, минимум два логических пространства и отдельные физические bundles; **один active writer на corpus**, write-partitions для несовместимых ACL, CROW writes только под LBS lock/read barrier/commit+recovery.
4. С первого дня OKF v0.2: `type/status/sources/index/log`, стабильный `knowledge_id`, сохранение unknown Frontmatter, отдельные lifecycle и confirmation. Исключить CROW namespace из legacy `memory_reconcile` и общих обходов; добавить проектор Note без конкурирующего writer.
5. **`knowledge.search` = CROW `Steps.select`** по разрешённому scoped дереву. **`knowledge.prepare_context` = `Researcher.ask` + `ScopedReadStore` + `Steps.answer=collect_context`**, с проверенным чтением `raw/.archive` и внутренним CROW CSV/history/conflict. Внешние A2A и Source API не нужны.
6. Кэш дерева по версии bundle, final ACL/egress после отбора; read-only OKF после выключения provider, backup/restore связанного Git+raw+archive+sync. Не обещать эквивалентный интеллектуальный поиск при выключенном CROW.

**Обязательный e2e:** два пользователя видят разный набор заметок **в одном** пространстве; чужие заголовки не попадают в prompt `select`; `raw` и архивы проверяются дополнительно; native ingest не объединяет несовместимые ACL; сценарий XLSX защищён **до** CROW ingest_file; прерывание между raw/Note и между commit/projection восстановимо; legacy `pending` закрыт. Без результата contract tests для pinned `Researcher/Steps/ScopedReadStore` не принимать.

**Не делать:** второй основной FTS-поиск по CROW Notes, новый Source API внутрь CROW, OpenFGA или отдельную службу CROW как предпосылку. При CROW disabled базовое чтение OKF работает без него, а остальные корпуса сохраняют LBS MemoryProvider.

### P2 — Agent Interaction Kernel локально

- локальный Task/Result контракт и один in-process provider;
- DB-backed ledger только для **реально долгих/восстанавливаемых** задач, не для каждого синхронного обращения;
- права по инициатору и агенту; проверяемые artifact refs; **сначала ACCESS-04/06 trust/delegation boundary, права task payload не считать authority**;
- адаптер к существующему LangGraph, не переписывая agent loop.

**Приёмка:** task submit/retry/cancel/fail, reboot recovery, no privilege escalation и чужих артефактов.

### P3 — Второй provider и граница A2A

- подключить Pi **или** Claude SDK через отдельный adapter, минимальные capabilities;
- сравнить стоимость выполнения и ресурсы, убедиться в изоляции запуска;
- зафиксировать границу A2A; реальный A2A сервер только при появлении независимого peer;
- не переносить внутренний LLM graph state между движками.

**Приёмка:** одна и та же задача выполняется двумя провайдерами, возвращая нормализованные результаты; отказ и недоверенное сообщение обрабатываются корректно.

### P4 — Коммуникации и Bitrix24

- Telegram channel (минимальный бот, signed/allowlisted identity linking, user consent, protected sensitive flows; интеграция с ACCESS-04);
- Web Chat/group rooms по отдельному профилю, строгая audience ACL (ACCESS-05 и проверки перед retrieval/публикацией);
- Bitrix24 TaskProvider с read + опциональным write по approval, идемпотентностью и rate limits;
- не синхронизировать сообщения и задачи бесконтрольно между всеми провайдерами.

**Приёмка:** 2 пользователя + 2 комнаты + закрытый Wiki source + один agent, отрицательный сценарий утечки, запись Bitrix один раз после retry.

### P5 — Упрощение инфраструктуры и оптимизация

- измерить Git write latency, Wiki search p95, end-to-end agent latency, стоимость и число конфликтов;
- убрать доказанное дублирование tool/skills registry, использовать один capability source;
- при необходимости выносить Wiki writer/индексатор в worker, но не начинать с микросервисной миграции; при CROW обязательно проверить связанный backup native raw/archive и восстановление многофайловой операции;
- расширение парсеров, векторов и других хранилищ только по оценке качества на реальном корпусе;
- выработать verification pack для следующего внедрения.

**Приёмка:** функциональность исходного LBS сохранена, независимый второй профиль конфигурации проходит e2e, сделан демонтаж одного optional provider без потери данных.

### P6 — Подключаемые предметные модули Kanban, Waiting List, Warehouse

**Это обязательный этап целевой архитектуры, но не блокирует пилоты Wiki/AgentTask.**

- Сначала инвентаризировать связи модулей с `core`, `accounts`, `workorders`, `inventory`, меню, Django migrations и AI tools; оформить корректирующий ADR.
- Ввести локальные manifest/descriptors и единый `enabled` gate; не удалять Django apps и модели до миграции зависимостей.
- Отвязать Waiting List от `apps.workorders.policies`, обеспечить независимое использование.
- Разделить WorkOrders business API и Kanban board/UI; сохранить старые заявки, статусы и действия.
- Выделить Warehouse через публичные интерфейсы, оставив весь posting/ledger внутри одной транзакции.
- Проверить профили без бизнес-модулей, `waiting-list-only`, `workorders-no-kanban`, `warehouse-only` и Bitrix Tasks; отдельно проверить восстановление после re-enable.

**Приёмка:** ни одно отключение не удаляет данные и не оставляет доступных HTTP/API/AI/MCP операций; отсутствие модулей не ломает минимальную Factory; модуль можно включить без изменения business-кода Kernel. Самостоятельная физическая установка модуля — отдельный gate, не смешивать с первичной функциональной развязкой.

Полная спецификация: `06_PLUGGABLE_BUSINESS_MODULES.md`.

## 2. Задания агентам (read/write scope)

| ID | Агентная задача | Read scope | Write scope | Граница готовности |
|---|---|---|---|---|
| A00 | Architectural inventory | весь repo, ADR, configs | только docs/reports | зависимости, факты и непросмотренные зоны перечислены |
| A01 | KnowledgeProvider facade | `apps/memory`, `apps/core/source_adapters`, docs | новые интерфейсы + минимальные wiring changes | contract tests, legacy search unaffected |
| A02 | Direct Wiki + confirmation register | `apps/memory`, channel adapters | safe-write facade + status projection/tests | запись без review; реестр неблокирующий; ACL/source e2e |
| A03 | AgentTask schema + ledger | AI/models + agent runtime | новая узкая task library + migration | retry/idempotency/restart/audit tests |
| A04 | Existing LangGraph adapter | `services/agent_runtime` | adapter и tests; без переписки graph | standard Task API compliant |
| A05 | Pi/Claude provider pilot | official SDK, sandbox | adapter + deployment test config | no secret leakage; capabilities matrix |
| A06 | A2A compatibility pilot | официальная A2A spec/SDK | A2A adapter | conformance + signed/trusted principal |
| A07 | Group audience security review | chat + wiki ACL | tests/security policy; код отдельно по scope | negative group leak tests |
| A08 | Bitrix24 provider | Bitrix REST docs + integration SDK | provider отдельного компонента | single writer, id mapping, retry test |
| A10 | Business module dependency map | `apps.workorders`, `apps.waiting_list`, `apps.warehouse`, `apps.accounts`, core | docs only | FK/import/migration/access graph and gates |
| A11 | Waiting List decoupling | Waiting List + policies | limited app code/tests | standalone operation without WorkOrders |
| A12 | Kanban / WorkOrders split | workorders + board templates | staged app code/migration after ADR | WorkOrders works without Kanban; no data loss |
| A13 | Warehouse as optional domain | warehouse + org/auth ports | limited warehouse code/tests | immutable entries, atomic posting, off/on works |
| A14 | Profile installation tests | settings, routing, registry, deploy/test | tests/profiles docs | empty and mixed profiles work; no disabled tools |
| A09 | Independent verification | PR diff, acceptance docs | только отчёт, тестовые фикстуры по запросу | воспроизведение критичных отклонений |

Параллельно допустимы A01/A03 при отсутствии общего write scope; A05 после A03; A06 после A05; A07 проектировать до Web Chat; A09 независимо после каждого рискованного среза. Субагентам передавать только необходимые контрактные файлы, diff, acceptance criteria и репозиторные refs; не полную историю всех обсуждений без нужды.

## 3. Матрица приёмки по инвариантам

| Инвариант | Unit | Integration | E2E |
|---|---|---|---|
| Установленные/активные/разрешённые capabilities не совпадают | x | x | x |
| Субагент не повышает права | x | x | x |
| No cross-installation/cross-room leakage | x | x | x |
| Working-знания без review доступны в current Wiki со статусом; needs_confirmation в реестре | x | x | x |
| Git canon и searchable projection восстанавливаются | x | x | x |
| Task replay не создаёт второй side effect | x | x | x |
| Подмена provider endpoint/Agent Card отвергается | x | x | x |
| Отмена не выдаётся за business rollback | x | x | x |
| Egress, секреты, PII, safe title/path и `adapter_check` | x | x | x |
| Versioned contract / old client compatibility | x | x | x |
| Неподключённый provider не запускается и не ломает kernel | x | x | x |
| Backend restarts maintain committed tasks |  | x | x |

Проверки базового репо: `make verify-fast TEST_SCOPE=...` → `make verify-profile PROFILE=memory|ai|contracts` → финальный `make verify-full` для крупного блока. После изменения структуры обновлять `.desc.json` и `make gen-struct`. Не делать «green build» единственным подтверждением качества: инварианты должны проверяться реальными негативными сценариями.

## 4. Набор обязательных ADR до реализации

- `ADR-F01`: LBS Factory как отдельная концепция от текущего Django portal; соглашение о референсном внедрении.
- `ADR-F02`: local AgentTask, A2A boundary, MCP/AG-UI, auth propagation и delegation limits.
- `ADR-F03`: общая Wiki/Knowledge API и неблокирующее подтверждение; **CROW/OKF уже принято ADR-0051**. Политика ПДн Git/raw остаётся отдельным архитектурным долгом, не вводить фиктивное «решение» новым ADR-F03.
- `ADR-F04`: provider lifecycle + optionality, identity and secrets.
- `ADR-F05`: Bitrix24 TaskProvider source of truth, конфликты записей и idempotency.
- `ADR-F06`: превращение Kanban/Waiting List/Warehouse в подключаемые компоненты, разделение WorkOrders и board UI, режимы disabled/uninstalled и migration strategy.
- `ADR-F07`: LBS Access как подключаемый AuthorizationProvider, capabilities от модулей, trusted delegated agent authority, чаты/Wiki/Bitrix24; переработка зависимостей без изменения semantics ADR-0043.

Использовать новый ADR ID только после проверки реальной нумерации/правил репозитория; `ADR-F0x` — логические placeholders.

## 5. Условия остановки / no-go

Не подключать Telegram/внешние LLM в реальных организациях без оформленных правил обработки чувствительных данных. Не давать агентам direct production shell/API credentials. Не объявлять реализованный A2A endpoint до сквозной проверки auth, task lifetime и streaming semantics. Не переносить `apps.memory` в отдельную службу, пока договоренности о каноне/доступе и восстановлении не проверены. Не обновлять AG-UI версии без отдельного плана и тестов в соответствии с `AGENTS.md`.

## 6. Пример валидации бизнес-ценности

Для первого пилота метрика — доля результатов интервью, которые **без ожидания reviewer** стали рабочими доступными страницами OKF со ссылкой на источник и понятным статусом; отдельно измеряется корректность ответов/контекста и число исправлений. Доля `confirmed` **не** должна быть KPI скорости наполнения. Для второго — сколько функций удалось получить настройкой готового решения и интеграцией без custom-кода, и насколько легко это обновлять.

## 7. Сквозной поток LBS Access (v3.3)

**Требование не является поздним отдельным этапом:** если реализацию доступа отложить до конца, Wiki, AgentTask и коммуникации успеют создать новые, несовместимые источники идентичности и прав.

- **До P1 и P2:** завершить ACCESS-00 (golden grants, основные FK/import, status/revocation tests) и договориться о `TrustedActorContext`/`AuthorizationProvider`/domain policy port.
- **Вместе с BM-01/BM-02/BM-04:** выполнить ACCESS-01..03 — общую модель роли/grants вынести из WorkOrders, capability declarations закрепить за доменами. Отключение бизнес-модулей без потери роли/настроек — обязательный gate.
- **Перед корпоративными Telegram/Bitrix/Remote A2A:** ACCESS-04 — verified identity mapping, installation binding, trusted service context; ACCESS-06 — проверка делегированных прав на фактическом side effect.
- **Перед Wiki и Web Chat multi-user pilot:** ACCESS-05 — source/item ACL, audience-aware retrieval/publish и тесты отзыва.
- **ACCESS-07:** optional OIDC/OpenFGA feasibility только по отдельной потребности, не блокирует локальный профиль.

**Задания:** AX-00..07 и подробная матрица в `08_ACCESS_MIGRATION_AND_TESTS.md`. Не поручать один и тот же изменяемый файл разным агентам параллельно; ориентироваться на PR-gates и `AGENTS.md`.

## 8. Порядок по принципу Progressive Complexity (v3.4)

S0: baseline, восстановление и границы модулей.  
S1: интервью → непосредственная working Wiki → поиск → необязательный реестр подтверждений.  
S2: один агент, нужные каналы и прямые интеграции.  
S3: независимое функциональное включение/выключение бизнес-модулей.  
S4: OpenFGA, A2A, векторы, брокер, второй agent provider и отдельные сервисы — каждый по отдельной доказанной необходимости.

Подробная спецификация: [09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md](09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md).

## 9. Этап PRIV перед LLM-Wiki, AI и внешними источниками

Нельзя считать исправление privacy-зазоров необязательным расширением безопасности: это предварительное условие стабильного безопасного накопления знаний из реальных документов. Выполнить `PRIV-00` (инвентаризация), `01` (общая библиотека), `02` (file ingestion), `03` (Source Adapters/adapter_check), `04` (Git Wiki и agent egress), `05` (контролируемый reindex существующих проекций) и `06` (регрессия/качество поиска). Не запускать удаление старых индексов на production без отдельного dry-run, резервной копии и подтверждения.

**Gate:** file и adapter paths не выдают raw при `pii_guarded`; `pii_strict` блокирует; `adapter_check` применяет назначенную privacy-политику; первый Wiki Git commit не сохраняет секрет или запрещённый PII. Одно отклонённое содержимое не блокирует общий Wiki/discovery flow. Полная матрица: [10_CONTENT_PRIVACY_PIPELINE.md](10_CONTENT_PRIVACY_PIPELINE.md).

## 10. Сводные критерии приёмки CROW/OKF для всей Factory

| Что проверяем | При включённом CROW | При выключенном CROW |
|---|---|---|
| `save_working` | Native CROW ingest в выделенном bundle через один LBS Writer Guard; без отдельного прямого writer | LBS MemoryProvider в назначенном не-CROW корпусе |
| Поиск Note | Единственный `Steps.select` по разрешённым Note; LBS FTS не конкурирует за те же Note | LBS-корпуса ищутся штатным способом; CROW Note доступны для базового OKF чтения |
| Контекст агента | `Researcher.ask` + `ScopedReadStore` + capture answer step | Нет ложного обещания полного CROW CSV/history/conflict |
| Доступ | Space AND Note restrictions; read/write ACL; raw/archive отдельным source ACL | LBS Access и доменные права без CROW |
| Надёжность | Lock + read barrier + operation journal + Git и native raw/archive/sync backup | Обычный существующий режим хранения и восстановления |
| Статусы | OKF `status`, human `confirmation_state`, legacy `lifecycle` не смешиваются | Те же внешние значения Knowledge API, без автоподтверждения |

Для CROW canonical per-corpus права Access не дублируются в Frontmatter как отдельные grants. Публикация закрытой информации через слияние в более общий bundle — **no-go**, даже если итоговый поиск отфильтрован. Отдельный долг по ПДн не блокирует synthetic pilot, но без политики **не включать произвольные реальные ПДн в Git и внешнюю модель**.

Реализационные acceptance criteria остаются в [12_CROW_IMPLEMENTATION_PLAN.md](12_CROW_IMPLEMENTATION_PLAN.md); это короткая Factory-матрица, **не второй независимый набор работ**.
