# ADR-0005: Chat-derived memory, reflection jobs and secret handles

## Status

Accepted

## Date

2026-05-20

## Context

ADR-0003 accepted the governance-first AI memory service architecture, and ADR-0004 accepted corporate document ingestion and graph schema bootstrapping. Those decisions cover managed sources, safe corpus, graph facts and the read-only `memory.search` tool.

The project also needs AI-chat-derived long-term memory:

- a user can explicitly ask the AI bot to remember a fact;
- remembered facts must be separated into personal user memory and organization-wide memory;
- key knowledge from chats should be consolidated during cheap off-peak background processing ("sleep-time reflection");
- urgent explicit remember requests should enqueue ingestion immediately instead of waiting for the scheduled reflection run;
- personal memory must be editable and deletable through the chat;
- organization-wide knowledge promoted from personal memory must be audited by the knowledge base / graph owner before publication;
- secrets mentioned in chats must not be indexed or passed to the LLM as values, but should be captured through a controlled secret-management interface.

The current implementation stores chat history in Django models `ChatSession` and `ChatMessage`. This history is operational chat state, not curated long-term memory.

External references used for this decision:

- LangGraph / Deep Agents memory docs describe long-term memory as filesystem-backed files, scoped memory, hot-path writes and background consolidation: https://docs.langchain.com/oss/python/deepagents/memory
- Vaultwarden / Bitwarden-compatible vaults fit human-owned password entry and retrieval workflows where the AI agent only stores or returns links/handles.
- OpenBao secrets engines support isolated paths, ACL-controlled secret storage and dynamic credential engines for later service-consumed secrets: https://openbao.org/docs/next/secrets/
- Bitwarden Secrets Manager supports machine accounts, projects and event logs for machine/AI access to discrete sets of secrets: https://bitwarden.com/help/machine-accounts/
- OWASP Secrets Management recommends least privilege, automation, rotation/temporality and lifecycle/audit logging: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
- OWASP Logging warns that logs can become a secret-exfiltration path: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

## Decision

Implement chat-derived memory as a separate controlled ingestion path inside `apps.memory`, backed by append-only knowledge event files and Django metadata.

### Scopes

Use two primary chat-memory scopes:

- `personal`: default for explicit "remember" requests; isolated per user.
- `organization`: used only when the user explicitly asks to remember for everyone / for the organization and the actor has the configured permission, or after reflection creates a candidate accepted by the knowledge owner.

Organization writes are controlled by project permissions. Promotion from personal memory to organization memory always creates a candidate requiring knowledge owner / graph owner audit before publication.

### Storage

Amendment 2026-05-26: ADR-0011 and ADR-0013 supersede the original projection-as-storage shape below. Canonical accepted knowledge now lives in `data/knowledge_repo/**/*.md`, with metadata in `MemoryKnowledgeItem`. `data/memory/chat_knowledge/` is retained only as a legacy append-only event log for chat-memory events and must not be treated as the source of truth for accepted knowledge text.

The original MVP storage shape was:

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

Current rules:

- `events/*.jsonl` are legacy append-only knowledge events with provenance;
- `memory.current.json` and `memory.current.md` are no longer canonical projections;
- canonical knowledge text is read from `data/knowledge_repo/`;
- Django DB remains the authority for access, status, audit and relations to chat messages;
- generated files under `data/` are runtime data and are not committed.

### Hot path and sleep-time reflection

Add `memory.remember` as a write tool that accepts message references, not arbitrary direct DB/index writes.

The tool must:

1. check actor permission and target scope;
2. create a queued `MemoryWriteRequest`;
3. return queue status to the bot;
4. optionally trigger an immediate lightweight ingestion job.

Off-peak reflection is a separate scheduled command, for example:

```bash
python manage.py memory_reflect_chats --window-hours 24
```

Reflection reads recent chat messages and queued requests, extracts key stable knowledge, deduplicates it against existing memory, updates personal projections and creates organization knowledge candidates when a personal memory item appears useful beyond one user.

### Exactness versus cleanliness

Do not choose between "as-is" storage and summarized memory. Store layered artifacts:

- source provenance: `ChatMessage` ids, session id, actor, timestamp and content hash;
- evidence snippet: safe text excerpt sufficient to understand the claim;
- normalized memory item: concise fact/preference/procedure with type, confidence and scope;
- current projection: compact merged view used for retrieval and context assembly.

The normalized item may be rewritten for clarity, but it must keep a provenance pointer to source chat messages and a content hash so the original meaning can be audited.

### Secrets

Secrets are not valid memory context, but they are valid inputs to a controlled secret-management flow.

When the pipeline detects a password, API key, token, private key, connection string or similar secret:

1. extract only the secret span;
2. store the secret value through a unified `SecretHandle` interface;
3. replace the span in memory text with `<SECRET_HANDLE:...>` and non-sensitive metadata;
4. continue processing the rest of the text;
5. write audit records for secret capture and handle access;
6. never place the secret value in prompts, tool traces, memory indexes, regular logs, `ChatMessage.metadata` or `AgentActionLog` payloads.

The user reads or writes the secret value through the secret-system URL/flow referenced by the handle. The AI agent sees only the handle and metadata.

Initial implementation should define one provider-neutral interface:

```text
SecretHandleBackend
  create_secret(actor, secret_value, metadata) -> SecretHandleRef
  get_secret_url(actor, handle_ref) -> URL
  rotate_secret(actor, handle_ref) -> status
  revoke_secret(actor, handle_ref) -> status
```

Provider choice:

- Vaultwarden is the preliminarily approved MVP storage for human-entered/human-read secrets when the agent only creates or finds links.
- OpenBao is deferred to later phases for service-consumed secrets, dynamic credentials, leases and server-side integration lookup.
- The code must depend on the unified interface, not directly on a concrete provider.

### Permissions

Extend the existing memory policy model:

- read personal memory: owner and superuser;
- write personal memory: owner and permitted delegated actors;
- delete/edit personal memory: owner and permitted delegated actors;
- write organization memory directly: configurable permission;
- propose organization candidate: reflection service and permitted users;
- approve organization candidate: knowledge owner / graph owner permission;
- read organization memory: users whose scopes match the published item;
- access secret handle value: never through LLM; only through secret backend UI/API and audited server-side flows.

### Moderation

Organization memory has two paths:

- direct write if the actor explicitly requested organization memory and has the configured permission;
- candidate flow if reflection promotes a personal memory item.

Candidate flow requires audit by the knowledge owner / graph owner before publication.

## Alternatives Considered

### Treat chat history as memory directly

Rejected. `ChatMessage` is an operational transcript. Directly indexing all chat text would mix noisy dialogue, transient thoughts, prompt-injection attempts, PII and secrets with curated knowledge.

### Only background reflection, no explicit remember tool

Rejected. Users expect explicit "remember this" requests to receive immediate acknowledgement. A queued hot-path tool gives the user status while preserving ingestion controls.

### Only hot-path memory writes

Rejected. Hot-path writes increase response latency and make the assistant reason about the current task and memory maintenance at the same time. Background reflection is still needed for deduplication, cleanup and organization candidate discovery.

### Block entire documents/messages when a secret is found

Rejected. This loses non-secret knowledge around the secret. The accepted behavior is span-level secret extraction plus continuation of the pipeline.

### Use OpenBao as the MVP default

Rejected. In the MVP scenario the agent does not read or write secret values; it only creates or finds links/handles, while the user enters and reads values through a vault UI. OpenBao would add unnecessary operational weight for that first stage.

OpenBao remains the preferred future backend when Django workers, integrations or services must resolve secret values server-side. The implementation remains provider-neutral through `SecretHandleBackend`.

## Consequences

### Positive

- Chat history, personal memory, organization memory and secret storage have clear boundaries.
- Personal memory is useful immediately while organization knowledge remains governed.
- The system can process remembered facts without indexing secrets or leaking them into LLM prompts.
- File-backed projections match the project data/code separation rule and are easy to audit.
- The architecture starts with a Vaultwarden-compatible human-vault MVP and remains compatible with future OpenBao or Bitwarden Secrets Manager adapters.

### Negative

- More models, commands and UI states are required.
- Reflection quality needs evaluation and human review loops.
- Secret span extraction must be conservative and well tested.
- Direct organization writes require careful permission design to avoid shared-memory prompt injection.

## Required Follow-up

- Update `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md` with this decision and the current gap analysis.
- Add a detailed implementation plan for chat memory, reflection and secret handles.
- Add workflow task packets for models, tools, reflection, secret handles, policy UI and tests.
- Extend `contracts/ai/tools.json` and `apps/ai/tool_definitions.py` with `memory.remember` only during implementation.
- Treat Vaultwarden as the preliminarily approved MVP secret storage for human-entered/human-read secrets.
- Keep OpenBao in the later service-consumed secrets phase.
- Add tests that prove secret values never appear in memory indexes, prompts, tool traces or ordinary logs.
