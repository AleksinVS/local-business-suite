# Gap analysis: текущее состояние системы памяти и план завершения

Статус: предварительный gap analysis для завершения memory-системы.

Дата: 2026-05-20.

Связанные решения:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`;
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`.

## Назначение

Этот документ фиксирует разрывы между целевой архитектурой памяти и текущей реализацией на 2026-05-20. Он не заменяет ADR и не является task packet; его цель - дать карту оставшихся работ.

## Текущее состояние

### Уже реализовано или частично реализовано

- `apps.memory` существует.
- Добавлены базовые модели памяти: `MemorySource`, `MemorySnapshot`, `MemoryChunk`, `MemoryGraphFact`, `MemoryIndexJob`, `MemoryAccessAudit`, `MemoryEvalCase`.
- Добавлены ingestion/discovery модели для документов: `MemorySourceObject`, `MemoryIngestionRun`, `MemoryIngestionIssue`, `MemoryGraphSchemaProposal`, `MemoryGraphEntity`, `MemoryGraphExtractionRun`, `MemoryGraphReviewItem`.
- Есть контракты `memory_sources`, `memory_profiles`, `memory_routing`, `memory_ingestion_profiles`, `memory_graph_schema` и схемы валидации.
- Есть `memory.search` как read tool.
- Есть Django policy layer для retrieval через scope tokens.
- Есть базовый DLP scanner (`CredentialGuard`) и de-identification с HMAC pseudonyms.
- Есть MVP ingestion local/UNC для text-like файлов и issue queue для неподдерживаемых/сложных файлов.
- Есть management commands для sync/discovery/ingestion/graph extraction/reindex/eval.
- Есть документация по document ingestion, deployment и user guide.

### Текущее хранение AI-чата

Диалоги ИИ-чата сейчас хранятся в Django runtime DB:

- `apps.ai.models.ChatSession` - сессия чата;
- `apps.ai.models.ChatMessage` - сообщения пользователя, ассистента, system и tool;
- `apps.ai.models.ChatAttachment` - вложения.

Это операционная история диалога. Она не является curated long-term memory и не должна напрямую индексироваться как знание без отдельного pipeline.

## Основные разрывы

### 1. Нет chat-derived memory

План памяти не описывал полноценный контур "пользователь попросил запомнить факт".

Не хватает:

- модели queued request для explicit remember;
- отдельного файлового storage для personal/org chat knowledge;
- связи remembered knowledge с `ChatMessage` provenance;
- команд для отражения/консолидации чатов;
- UI/admin для просмотра и исправления персональной памяти;
- audit для edit/delete/remember операций.

### 2. Нет `memory.remember`

В tool registry есть только `memory.search`.

Нужно добавить write tool:

- принимает `session_id` и `message_ids`;
- принимает `target_scope=personal|organization`;
- не пишет напрямую в индексы;
- ставит ingestion job/request в очередь;
- возвращает статус пользователю.

### 3. Не реализована "рефлексия во сне"

В backlog была общая идея суммаризации и заполнения памяти, но нет архитектурного процесса.

Нужно:

- scheduled command `memory_reflect_chats`;
- окно обработки, watermark и idempotency;
- cheap off-peak profile;
- дедупликация и merge с existing memory;
- promotion важных персональных знаний в кандидаты общих знаний;
- review queue владельца базы/графа знаний.

### 4. Секреты сейчас блокируют весь snapshot

Текущее поведение:

- `CredentialGuard` находит secret-like span;
- `deidentify_text()` возвращает `blocked=True` и пустой `safe_text`;
- snapshot становится `BLOCKED`;
- индексация не продолжается.

Целевое поведение:

- блокировать только secret span;
- значение секрета сохранять через `SecretHandleBackend`;
- в safe text оставлять `<SECRET_HANDLE:...>` и metadata;
- продолжать обработку остального текста;
- не отдавать secret value в LLM, индекс, logs или tool traces.

### 5. Secret-management architecture описана только как этап

В `MEMORY_SERVICE_IMPLEMENTATION_PLAN.md` есть Stage 12 с OpenBao/SecretHandle, но нет:

- ADR по chat/secret handles;
- provider-neutral backend contract;
- модели `SecretHandle` / `SecretAccessAudit`;
- DLP scanner в chat input;
- правила ссылок, которые агент может отдавать пользователю;
- правила исключения secret values из `ChatMessage.metadata`, `AgentActionLog`, prompts и обычных логов.

### 6. Права чтения памяти есть частично, права записи не проработаны

Сейчас есть retrieval-level scope tokens:

- `org:default`;
- `user:<id>`;
- `role:<name>`;
- `role:superuser`.

Чтение chunks/facts проверяется через Django metadata. Это базовый контур чтения, но он не покрывает:

- право писать personal memory;
- право редактировать/удалять personal memory;
- право писать organization memory напрямую;
- право создавать organization candidate;
- право approve/reject organization candidate;
- право создавать/читать/ротировать/revoke secret handles;
- отдельные audit trails для write-памяти.

### 7. Organization memory moderation не формализована для chat knowledge

Document graph schema proposals уже имеют moderated модель. Chat knowledge promotion пока не описан.

Нужно:

- отдельная очередь `MemoryKnowledgeCandidate`;
- статусы candidate: `proposed`, `needs_review`, `accepted`, `rejected`, `merged`, `superseded`;
- review role: knowledge owner / graph owner;
- rejected examples как negative examples;
- publication into `data/memory/chat_knowledge/org/default/`.

### 8. File-backed personal/org memory не описана в старом storage tree

Текущий storage tree знает:

- `raw_vault`;
- `safe_corpus`;
- `indexes`;
- `manifests`;
- `eval`.

Нужно добавить:

```text
data/memory/chat_knowledge/
  org/default/
  users/<user_id>/
```

и описать, что это runtime data, не Git.

### 9. `safe corpus` нужно уточнить для chat memory

Для document ingestion safe corpus - очищенный текст после privacy pipeline. Для chat-derived memory safe corpus должен включать:

- safe evidence snippets;
- normalized memory facts;
- secret handles вместо values;
- provenance pointers;
- scope/sensitivity labels.

### 10. Evaluation не покрывает chat memory

Существующий eval smoke/security ориентирован на retrieval и secret bait.

Нужны новые suites:

- explicit remember creates queued request;
- personal memory isolation;
- personal edit/delete;
- direct org write permission;
- candidate promotion review;
- secret span extraction continues non-secret ingestion;
- secret value absent from prompts/logs/indexes;
- reflection idempotency.

## Secret storage: MVP и дальнейшие этапы

После уточнения требований MVP агент не должен читать или записывать значения секретов. Агент создает/находит только ссылку/handle, а пользователь сам вводит и читает secret value в отдельном vault UI.

Для такого MVP предварительно одобрен Vaultwarden как human-vault хранилище:

- подходит для человеческих паролей и shared vault workflows;
- не требует от Django/LLM обработки secret value;
- позволяет агенту хранить только `<SECRET_HANDLE:...>`, label, provider, owner/scope и ссылку;
- лучше соответствует первому этапу, где сервисы не потребляют секреты автоматически.

OpenBao переносится на дальнейшие этапы, когда появится service-consumed secret контур:

- динамические credentials и leases;
- server-side lookup без выдачи value агенту;
- policy/ACL на уровне paths/engines;
- изоляция secret engines;
- audit доступа к handles;
- возможность будущих machine/service integrations.

Целевое решение остается provider-neutral: единый `SecretHandleBackend`. Для MVP его основной provider - Vaultwarden-compatible external vault link. Для будущих service-consumed secrets добавляется OpenBao provider.

Ориентиры:

- OpenBao secrets engines: https://openbao.org/docs/next/secrets/
- OpenBao KV: https://openbao.org/docs/secrets/kv/kv-v1/
- Bitwarden machine accounts: https://bitwarden.com/help/machine-accounts/
- Bitwarden Secrets Manager: https://bitwarden.com/products/secrets-manager/
- OWASP Secrets Management: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

## Завершение системы памяти

Завершение memory-системы теперь состоит из трех связанных направлений:

1. Corporate/document memory:
   - production parser/OCR;
   - vector backend;
   - stronger graph extraction;
   - admin/review hardening.
2. Chat-derived memory:
   - `memory.remember`;
   - personal/org memory files;
   - sleep-time reflection;
   - candidate promotion and review;
   - edit/delete through chat.
3. Secret handles:
   - unified provider interface;
   - span-level extraction;
   - Vaultwarden-compatible external vault link for MVP;
   - OpenBao-compatible adapter for later service-consumed secrets;
   - secret audit and no-value-in-LLM guarantees.

Detailed implementation plan: `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`.
