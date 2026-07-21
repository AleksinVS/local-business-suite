# Executor report: memory-chat-reflection-secret-handles

Дата: 2026-05-20.

## Выполнено

- Добавлены модели chat-derived memory и secret handles:
  - `MemoryWriteRequest`;
  - `MemoryKnowledgeItem`;
  - `MemoryKnowledgeEvent`;
  - `MemoryKnowledgeCandidate`;
  - `MemoryReflectionRun`;
  - `SecretHandle`;
  - `SecretAccessAudit`.
- Добавлен `memory.remember` write tool, который ставит request в очередь.
- Добавлен `memory.update_personal` для edit/delete персональной памяти.
- Добавлен atomic/runtime storage writer для `data/memory/chat_knowledge/`.
- Добавлена команда `memory_reflect_chats`.
- Добавлен Vaultwarden-compatible MVP backend `external_vault_link` через `SecretHandleBackend`.
- Secret-like spans в chat memory заменяются на `<SECRET_HANDLE:...>`; non-secret текст продолжает ingestion.
- `<SECRET_HANDLE:...>` исключен из DLP false positive scanner.
- Обновлены AI tool registry, task type contracts, docs, deployment guide и project structure.

## Измененные области

- `apps/memory/`;
- `apps/ai/tooling.py`;
- `apps/ai/tool_definitions.py`;
- `contracts/ai/tools.json`;
- `contracts/ai/task_types.json`;
- `services/agent_runtime/task_types.py`;
- `docs/`;
- `workflow/active/memory-chat-reflection-secret-handles/`;
- `PROJECT_STRUCTURE.yaml`.

## Проверки

- `python manage.py test apps.memory.tests` - passed.
- `python manage.py test apps.ai.tests` - passed.
- `python manage.py check` - passed.
- `python manage.py validate_architecture_contracts` - passed.
- `python manage.py makemigrations --check --dry-run` - passed.
- `make test` - passed, 186 tests.

## Ограничения MVP

- `memory.remember` ставит request в очередь; обработка выполняется через `memory_reflect_chats` или service call.
- Vaultwarden integration реализован как external-link/handle metadata, без API-записи значений секретов.
- Organization candidate review model добавлена, но полноценный GUI review остается следующим UI-этапом.
- Права organization write/review в MVP завязаны на staff/superuser; контрактные granular capabilities остаются следующим hardening этапом.
