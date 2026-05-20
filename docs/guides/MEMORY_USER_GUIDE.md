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

Если AI дает утверждение "из памяти", но citations отсутствуют, такой ответ нельзя считать подтвержденным данными memory service.

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
- `memory.search` выполняет простую выдачу: vector/full-text candidates, затем graph candidates;
- ingestion MVP поддерживает local/UNC discovery, issue queue, text-like file ingestion, bootstrap package и graph schema proposals;
- PDF/Office/images пока не извлекаются полноценно: такие документы попадают в issue queue до подключения production parser/OCR backend;
- ACL inheritance, raw vault, production cloud OCR/LLM и review каждого graph instance не входят в MVP;
- облачная маршрутизация для чувствительных случаев не включена.

## Как проверить пользователю

1. Открыть AI-чат под обычным пользователем.
2. Задать запрос по теме, которая точно должна быть в safe corpus.
3. Убедиться, что ответ содержит citations.
4. Попросить найти данные вне своего scope и убедиться, что контекст не возвращается.
5. Администратору проверить `MemoryAccessAudit`: должны быть записи с `policy_decision=allowed` или `denied`, `query_hash`, returned ids и retrieval trace.

Если память еще не индексировалась, пустой результат `memory.search` является нормальным.
