# План: chat-derived memory, queue processing, future reflection и secret handles

Статус: архитектурный implementation plan; MVP data model, `memory.remember`, personal edit/delete services, queue processor command and Vaultwarden-compatible external link backend implemented 2026-05-20. Уточнено ADR-0010: `MemoryKnowledgeItem` является главным объектом памяти MVP, а полноценная ночная рефлексия перенесена на следующий этап.

Уточнение 2026-05-26: после ADR-0011/ADR-0013 канонический текст принятого знания хранится только в `data/knowledge_repo/`. Путь `data/memory/chat_knowledge/` оставлен только как legacy append-only event log событий, а не как source of truth или текущая projection-память.

Дата: 2026-05-20.

Связанный ADR: `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`.

## Назначение

Этот план описывает доработку системы памяти, которая превращает отдельные факты из AI-чата в управляемую долговременную память. План дополняет:

- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/architecture/MEMORY_COMPLETION_GAP_ANALYSIS.md`.

## Принятые пользовательские решения

- По умолчанию "запомни" пишет в персональную память пользователя.
- Общая организационная память используется, если пользователь явно сказал "для всех / для организации" и имеет право, либо если обработчик очереди создал кандидата в общие знания.
- Право прямой записи в организационную память настраивается правами пользователя.
- Кандидаты в общие знания требуют обязательной модерации владельцем базы/графа знаний.
- На первом этапе все секреты идут через единый provider-neutral `SecretHandleBackend`, где Vaultwarden является предварительно одобренным MVP-хранилищем для human-entered/human-read secret values.
- Пользователь должен уметь удалить или исправить свою персональную память через чат.
- `memory.remember` считается успешным, если поставил `MemoryWriteRequest` в очередь и вернул `status=queued`; `memory_id` появляется только после обработки очереди.
- Агент видит только `<SECRET_HANDLE:...>` и metadata; значение секрета пользователь пишет/читает самостоятельно через ссылку, переданную агентом.
- Совместимый обработчик очереди может предлагать важные персональные знания как кандидаты в организационную память, но публикация в общую память идет только через audit владельца базы/графа знаний.

## Термины

- Chat history: `ChatSession` и `ChatMessage`, операционная история диалога.
- Remember request: явный запрос пользователя сохранить знание.
- Personal memory: долговременная память одного пользователя.
- Organization memory: общая память организации, доступная по scope/policy.
- Knowledge event: append-only событие изменения memory state.
- Current projection: историческое название агрегированной версии memory-файла; в текущем MVP не является источником истины.
- Queue processor: обработчик queued remember requests и простых кандидатов в общую память.
- Future reflection: будущая отложенная консолидация чатов и remembered events в дешевое ненагруженное время.
- Candidate: предложение добавить знание в общую память.
- Secret handle: ссылка на секрет в контролируемом secret backend без раскрытия value агенту.

## Storage layout

Legacy event log:

```text
data/memory/chat_knowledge/
  org/default/
    memory.current.json
    memory.current.md
    events/YYYY-MM.jsonl
  users/<user_id>/
    memory.current.json
    memory.current.md
    events/YYYY-MM.jsonl
```

Формат event:

```json
{
  "event_id": "uuid",
  "event_type": "remembered|edited|deleted|reflected|promoted|rejected|secret_captured",
  "scope": "personal|organization",
  "owner_user_id": 123,
  "source": {
    "session_id": "uuid",
    "message_ids": [1, 2],
    "content_hash": "sha256:..."
  },
  "memory_item": {
    "memory_id": "stable-id",
    "kind": "fact|preference|procedure|decision|secret_reference",
    "text": "Safe normalized text",
    "confidence": 0.82,
    "sensitivity": "internal",
    "scope_tokens": ["user:123"]
  },
  "secret_handles": [
    {
      "handle": "secret:...",
      "label": "API token for test system",
      "provider": "openbao",
      "url_ref": "opaque-url-or-route-name"
    }
  ],
  "status": "accepted|queued|candidate|deleted|superseded",
  "created_at": "2026-05-20T10:00:00+03:00",
  "actor_id": 123
}
```

Правила:

- secret value запрещено хранить в JSONL/current files;
- raw chat text не копировать в files без необходимости; использовать references + hash + safe snippets;
- запись атомарная;
- current projections пересобираются из events;
- Django DB хранит authority metadata, status, locks и audit.

## Django model additions

Предварительные модели:

- `MemoryWriteRequest`
  - actor, session, message ids, target scope, status, reason, created_at, processed_at;
  - statuses: `queued`, `processing`, `accepted`, `candidate_created`, `failed`, `cancelled`;
  - links to output memory items / issues.
- `MemoryKnowledgeItem`
  - stable id, scope, owner user, text hash, current text, sensitivity, scope tokens, status;
  - statuses: `active`, `deleted`, `superseded`, `quarantined`;
  - provenance to source messages and events.
- `MemoryKnowledgeCandidate`
  - source personal item, proposed org item, evidence, reviewer, status;
  - statuses: `proposed`, `needs_review`, `accepted`, `rejected`, `merged`, `superseded`.
- `MemoryReflectionRun`
  - сейчас используется как совместимый журнал обработки очереди; полноценная reflection window будет уточнена отдельно.
- `SecretHandle`
  - opaque handle, provider, label, owner/scope metadata, created_by, sensitivity, status;
  - no secret value.
- `SecretAccessAudit`
  - actor, handle, action, decision, request_id, timestamp, metadata without value.

## Tooling

### `memory.remember`

Mode: write.

Inputs:

- `session_id`;
- `message_ids`;
- `target_scope`: `personal|organization`;
- `user_note`;
- `importance`: optional;
- `contains_secret_hint`: optional.

Outputs:

- `request_id`;
- `status`;
- `target_scope`;
- `queued_at`;
- `job_id`;
- `message`.

Rules:

- default target scope is `personal`;
- organization target requires explicit user wording and permission;
- обычный tool только создает `MemoryWriteRequest` со статусом `queued` и `MemoryIndexJob` со статусом `pending`;
- обработчик очереди сохраняет `MemoryKnowledgeItem`, обновляет файлы и индексы, после чего знание находится через `memory.search`;
- `memory_id`, `event_id` и `processed_at` относятся к результату обработки очереди, а не к первичному ответу инструмента;
- user confirmation depends on normal write-tool policy.

### `memory.update_personal`

Mode: write.

Inputs:

- `memory_id`;
- `operation`: `edit|delete`;
- `new_text` for edit.

Rules:

- only owner or permitted delegated actor;
- operation creates append-only event;
- current projection is rebuilt;
- old item is superseded/deleted, not silently overwritten.

### `memory.propose_org_memory`

Mode: write/internal.

Used by queue processor, future reflection or permitted users to create organization candidates.

### `memory.review_candidate`

Mode: write/admin.

Used by knowledge owner / graph owner to accept, edit, reject or merge organization candidates.

## Ingestion and queue processing pipeline

### Immediate request path

```text
User says "remember ..."
  -> AI runtime calls memory.remember with message refs
  -> permission and scope check
  -> MemoryWriteRequest created with queued status
  -> MemoryIndexJob created with pending status
  -> bot reports request_id, job_id and queued status
```

### Queue processing path

```text
Scheduled memory_reflect_chats
  -> select queued MemoryWriteRequest rows
  -> process explicit remember requests
  -> MemoryKnowledgeItem saved as main MVP memory object
  -> event appended to personal/org target
  -> current projection rebuilt
  -> MemorySnapshot/MemoryChunk updated for retrieval
  -> default full-text index updated
  -> request accepted and processed result includes memory_id/event_id
```

### Queue processor command

```text
Scheduled memory_reflect_chats
  -> select queued MemoryWriteRequest rows
  -> retrieve existing personal memory projection
  -> create organization candidates for cross-user/org-relevant knowledge
  -> update chunks/indexes for processed requests
  -> write MemoryReflectionRun compatibility metrics
```

This command is not full sleep-time reflection. Future reflection will separately analyze chat windows, merge repeated knowledge and find stable patterns.

Scheduling:

- MVP: management command from cron/systemd/Windows Task Scheduler.
- Production: Celery + Redis + django-celery-beat after memory jobs are stable.
- Run in low-load windows; default nightly is acceptable.
- Use watermarks and locks so repeated runs are idempotent.

## Extraction policy: exactness and cleanliness

Use a layered strategy:

1. Keep exact provenance in DB: source message ids, hashes, actor, session, timestamps.
2. Create safe evidence snippets after DLP/PII/secret processing.
3. Create normalized memory items with minimal wording changes.
4. Preserve meaning by storing claim type, confidence, source pointers and before/after hashes.
5. For ambiguous facts, create candidate/review item instead of publishing.

Allowed transformations:

- remove dialogue filler;
- merge duplicates;
- normalize names of domains/entities where policy allows;
- replace PII with stable pseudonyms;
- replace secrets with handles.

Forbidden transformations:

- changing factual polarity or condition;
- removing provenance;
- creating organization-wide knowledge from one personal statement without candidate review, unless actor explicitly has organization-write permission;
- storing secret values in memory text.

## Secret-handling pipeline

```text
Text span scanner
  -> classify secret span
  -> create SecretHandle through provider interface
  -> replace value with <SECRET_HANDLE:...>
  -> attach metadata
  -> continue non-secret memory ingestion
  -> audit capture/access
```

Provider-neutral baseline:

```text
SecretHandleBackend
  create_secret(actor, value, metadata)
  update_secret(actor, handle, value)
  get_user_url(actor, handle)
  resolve_for_service(service_identity, handle)
  rotate_secret(actor_or_service, handle)
  revoke_secret(actor_or_service, handle)
```

MVP provider modes:

- `disabled`: creates a blocked secret issue and redacts the span; no value persisted.
- `external_vault_link`: production MVP mode; creates a Vaultwarden-compatible handle/link while the user enters and reads the value in the vault UI.
- `local_stub`: test-only, writes encrypted/quarantined value under `.local/` or test DB only; forbidden in production.
- `openbao`: future provider for service-consumed secrets, dynamic credentials, leases and server-side integration lookup.

Rules:

- LLM never sees value.
- Agent returns only handle and user-facing link/route.
- Service integrations use server-side lookup.
- Ordinary logs store only handle id/hash, action and decision.
- If secret storage fails, the secret span is redacted and a review issue is created; non-secret text still continues.

## Permissions

Use contract-driven permissions rather than hard-coded role names.

Required capability names:

- `memory.personal.read`;
- `memory.personal.write`;
- `memory.personal.edit`;
- `memory.personal.delete`;
- `memory.organization.read`;
- `memory.organization.write`;
- `memory.organization.propose`;
- `memory.organization.review`;
- `memory.secret.capture`;
- `memory.secret.handle_link`;
- `memory.secret.service_resolve`;

Implementation note: map these capabilities into the existing role rules contract during code implementation. Do not let LLM-generated scope tokens decide access.

## Admin/UI

MVP admin:

- list write requests and statuses;
- list personal memory items for the owner/admin;
- list organization candidates;
- accept/edit/reject candidate;
- list secret handles without values;
- show secret access audit.

Chat UX:

- "запомни ..." returns queued/accepted/candidate status;
- "что ты обо мне помнишь?" uses personal memory retrieval;
- "забудь/исправь ..." calls personal update/delete tool;
- secret responses include only handle/link.

## Tests and acceptance

Required tests:

- personal remember defaults to personal scope;
- explicit organization remember requires permission;
- reflection creates candidate, not direct org write;
- knowledge owner can accept candidate;
- rejected candidate remains as negative example;
- personal edit/delete works through append-only events;
- secret span extraction continues non-secret ingestion;
- secret value absent from:
  - `MemoryChunk`;
  - safe corpus files;
  - vector/full-text/graph indexes;
  - prompts/tool traces;
  - `AgentActionLog`;
  - ordinary logs;
- scope filters prevent reading another user's personal memory;
- repeated reflection run is idempotent.

Verification commands after implementation:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reflect_chats --dry-run
python manage.py memory_eval --dry-run
```

## Implementation phases

### Phase 1. ADR, docs and task packets

Create accepted ADR, gap analysis, active plan and workflow packets.

### Phase 2. Data model and storage writer

Add models, migrations and atomic file writer for chat knowledge events/projections.

### Phase 3. Immediate remember tool

Add tool contract, gateway handler, queueing service and status responses.

### Phase 4. Reflection command

Add scheduled command, watermarks, idempotent processing and organization candidate creation.

### Phase 5. Secret handles

Replace document-level secret blocking with span-level extraction for chat-derived memory first, then extend document ingestion. MVP handle creation targets Vaultwarden-compatible external links; OpenBao integration is deferred until service-consumed secrets are implemented.

### Phase 6. Permissions and UI/admin

Add capability mapping, admin actions and chat edit/delete flow.

### Phase 7. Evaluation and release hardening

Add eval suites, logging checks, prompt/tool trace checks and deployment guide updates.
