# Руководство пользователя: система памяти

## Назначение

Система памяти добавляет к AI-чату управляемый поиск по безопасному корпусу знаний проекта:

- источники памяти описываются контрактами;
- исходный текст проходит privacy pipeline;
- индексы строятся только по safe corpus;
- доступ идет через read-only tool `memory.search`;
- каждый успешный или запрещенный поиск фиксируется в `MemoryAccessAudit`.

Это не замена базе данных и не способ читать raw snapshots. Для пользователей AI-чат возвращает только компактный контекст с citations.

## Что доступно обычному пользователю

Обычный пользователь работает через AI-чат. Типовые запросы:

- "Найди в памяти информацию по заявкам на обслуживание насоса."
- "Есть ли контекст по калибровке кислородного оборудования?"
- "Поищи связанные факты по устройству device_alpha."

Ожидаемое поведение:

- если подходящие safe chunks найдены, ответ инструмента содержит `items` и `citations`;
- если данных нет или scope пользователя не подходит, `items` будет пустым;
- если запрошен запрещенный уровень чувствительности, запрос будет отклонен и записан в audit;
- raw paths, raw snapshots и секреты пользователю не возвращаются.

## Что проверять в ответе AI

Для каждого полезного результата должны быть citations:

- `source_code`;
- `source_object_id`;
- `chunk_id` или `fact_id`;
- `snapshot_hash`;
- `text_hash`;
- `sensitivity`.
- `trust_status`;
- `authority_class`;
- `trusted_for_context`.

Если AI дает утверждение "из памяти", но citations отсутствуют, такой ответ нельзя считать подтвержденным данными memory service.

## Надежные источники и сохраненные знания

Safe corpus означает, что текст прошел privacy/security pipeline и может храниться или индексироваться. Это не означает, что источник можно напрямую отдавать агенту.

Для обычного `memory.search` теперь действует trusted-only правило:

- `trusted` источники могут попадать в agent context после scope/sensitivity/citation checks;
- `review_required` источники можно хранить и разбирать, но нельзя напрямую отдавать агенту до проверки;
- `blocked` источники не используются;
- старые значения `candidate_only` и `quarantined` совместимо отображаются в `review_required`;
- untrusted источники могут использоваться как evidence для review/candidate flow;
- `MemoryKnowledgeItem` является главным объектом сохраненного знания MVP;
- `MemoryClaim` не создается обычным "запомни"; `MemoryBelief` не входит в MVP-схему и не возвращается обычным `memory.search`.

Если источник safe, но не trusted, оператор должен провести проверку источника или конкретного знания перед публикацией в общую память.

## Администрирование

Администратор использует Django Admin:

- `MemorySource` — источники памяти и их статус;
- `MemorySnapshot` — снимки источников, blocked/ready state, artifact presence;
- `MemoryChunk` — safe chunks без отображения raw text path в поиске;
- `MemoryGraphFact` — извлеченные графовые факты;
- `MemoryIndexJob` — smoke reindex jobs и статус выполнения;
- `MemoryAccessAudit` — журнал вызовов `memory.search`;
- `MemoryEvalCase` — сценарии eval/smoke проверок.

В admin намеренно не выводятся raw/safe/text path как обычные searchable поля. Показывается состояние артефактов: present/missing.

## Ingestion корпоративных документов

Следующий блок памяти добавляет ingestion документов из локальной папки Windows Server или UNC path. Операционные правила описаны в `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

Коротко для пользователей и операторов:

- первый источник — отдельная read-only папка "документы для памяти", а не весь общий файловый ресурс;
- Windows services должны использовать UNC paths вида `\\SERVER\Share\Folder`, не mapped drives;
- raw-документы по умолчанию не копируются в `data/memory/`, хранится ссылка, hash и metadata;
- password-protected, encrypted, partial, suspicious и unsupported документы попадают в issue/review queue;
- graph schema proposals проверяются профильными экспертами и владельцем графа;
- routine graph entities/facts после принятия схемы создаются автоматически, review нужен только для исключений.

## Операторские команды

Синхронизировать источники памяти из contracts:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_sync_source
```

Проверить состояние индексирования без Celery и без raw PII indexing:

```bash
python manage.py memory_reindex --dry-run
python manage.py memory_reindex
```

Запустить synthetic smoke/security eval:

```bash
python manage.py memory_eval --dry-run
python manage.py memory_eval --output-json
```

Eval report пишется только в `data/memory/eval/`.

## Ограничения текущей версии

- production scheduler/Celery не подключен;
- embeddings пока представлены интерфейсом, но не генерируются;
- SQLite FTS используется как локальный MVP full-text backend;
- Kuzu backend пока lazy placeholder;
- `memory.search` выполняет trusted-only gate, deterministic rank fusion и context packing без обязательного LLM;
- review UI для источников и знаний пока представлен Django Admin;
- claim extraction и `MemoryClaim` перенесены на следующие этапы; `MemoryBelief` не входит в MVP-схему;
- ingestion MVP поддерживает local/UNC discovery, issue queue, text-like file ingestion, bootstrap package и graph schema proposals;
- PDF/Office/images пока не извлекаются полноценно: такие документы попадают в issue queue до подключения production parser/OCR backend;
- ACL inheritance, raw vault, production cloud OCR/LLM и review каждого graph instance не входят в MVP;
- облачная маршрутизация для чувствительных случаев не включена.

## MVP расширение: память из AI-чата

AI-чат использует `memory.search` как read путь к memory service. Диалоги самого чата хранятся в `ChatSession` и `ChatMessage` и не считаются долговременной curated memory без отдельного pipeline.

Для запросов вида "запомни" добавлен MVP-контур:

- по умолчанию знание пишется в персональную память пользователя;
- запись в общую память организации требует явного намерения пользователя и соответствующего права;
- `memory.remember` ставит запрос в очередь и возвращает `request_id`, `job_id`, `status=queued`, `target_scope` и `queued_at`;
- пока обработчик очереди не запускался, `MemoryKnowledgeItem` еще не создан и `memory_id` в первичном ответе отсутствует;
- команда `memory_reflect_chats` остается совместимой командой обработки очереди "запомни" и создания кандидатов, но не является полноценной ночной рефлексией;
- после обработки очереди запрос получает состояние `accepted`, создается `MemoryKnowledgeItem`, а сохраненный фрагмент находится через `memory.search`;
- кандидаты в общие знания публикуются только после review владельца базы/графа знаний;
- пользователь сможет исправлять и удалять свою персональную память через чат;
- секреты сохраняются только через secret handle: агент видит `<SECRET_HANDLE:...>` и metadata, но не значение секрета;
- MVP secret backend использует Vaultwarden-compatible external link: пользователь сам вводит/читает secret value во внешнем vault UI.

Архитектурное решение: `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`.
Implementation plan: `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`.

Операторская команда совместимости для обработки очереди:

```bash
python manage.py memory_reflect_chats --dry-run
python manage.py memory_reflect_chats
```

## Как проверить пользователю

1. Открыть AI-чат под обычным пользователем.
2. Задать запрос по теме, которая точно должна быть в safe corpus.
3. Убедиться, что ответ содержит citations.
4. Попросить найти данные вне своего scope и убедиться, что контекст не возвращается.
5. Администратору проверить `MemoryAccessAudit`: должны быть записи с `policy_decision=allowed` или `denied`, `query_hash`, returned ids и retrieval trace.

Если память еще не индексировалась, пустой результат `memory.search` является нормальным.
