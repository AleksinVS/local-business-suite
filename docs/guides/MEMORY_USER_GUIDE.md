# Руководство пользователя: система памяти

## Назначение

Система памяти добавляет к AI-чату управляемый поиск по безопасному корпусу знаний проекта:

- источники памяти описываются контрактами;
- исходный текст проходит privacy pipeline;
- индексы строятся по файлам знаний и безопасным поисковым документам;
- доступ идет через read-only tool `memory.search`;
- каждый успешный или запрещенный поиск фиксируется в `MemoryAccessAudit`.

Это не замена базе данных и не способ читать исходные документы напрямую. Для пользователей AI-чат возвращает только компактный контекст со ссылками на источники.

Фактическая граница текущего MVP описана в `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`.

## Что доступно обычному пользователю

Обычный пользователь работает через AI-чат. Типовые запросы:

- "Найди в памяти информацию по заявкам на обслуживание насоса."
- "Есть ли контекст по калибровке кислородного оборудования?"
- "Поищи связанные факты по устройству device_alpha."

Ожидаемое поведение:

- если подходящие знания найдены, ответ инструмента содержит `items` и `citations`;
- если данных нет или scope пользователя не подходит, `items` будет пустым;
- если запрошен запрещенный уровень чувствительности, запрос будет отклонен и записан в audit;
- пути к исходным файлам, необработанные данные и секреты пользователю не возвращаются.

## Что проверять в ответе AI

Для каждого полезного результата должны быть citations:

- `source_code`;
- `source_object_id`;
- `knowledge_id` или `document_id`;
- `text_hash`;
- `sensitivity`.
- `trust_status`;
- `authority_class`;
- `trusted_for_context`.

Если AI дает утверждение "из памяти", но citations отсутствуют, такой ответ нельзя считать подтвержденным данными memory service.

## Надежные источники и сохраненные знания

Безопасный корпус означает, что текст прошел проверку приватности и безопасности и может индексироваться. Это не означает, что источник можно напрямую отдавать агенту.

Для обычного `memory.search` теперь действует trusted-only правило:

- `trusted` источники могут попадать в agent context после scope/sensitivity/citation checks;
- `review_required` источники можно хранить и разбирать, но нельзя напрямую отдавать агенту до проверки;
- `blocked` источники не используются;
- старые значения `candidate_only` и `quarantined` совместимо отображаются в `review_required`;
- untrusted источники могут использоваться как evidence для review/candidate flow;
- `MemoryKnowledgeItem` является главным объектом сохраненного знания MVP;
- `MemoryClaim` и `MemoryBelief` не входят в MVP-схему и не возвращаются обычным `memory.search`.

Если источник safe, но не trusted, оператор должен провести проверку источника или конкретного знания перед публикацией в общую память.

## Администрирование

Администратор использует рабочий UI ревью памяти:

```text
/memory/review/
```

В нем доступны:

- сводка открытых issues и состояния индекса;
- очередь `MemoryIngestionIssue`;
- карточка issue с безопасными metadata и действиями acknowledge/assign/resolve/ignore/reindex;
- список и карточка `MemorySearchDocument` с FTS/vector diagnostics;
- раздел `Кандидаты` (`/memory/review/pending/`) — страницы со статусом `lifecycle: pending`: кандидаты personal -> organization и понижения классификации, ожидающие явного решения владельца знаний (принять/отклонить);
- раздел `Файлы` с baseline-размещениями, предложениями общей структуры и заданиями переноса;
- журнал ревью (`/memory/review/audit/`) — комбинированная лента: решенные issues, задания единой очереди памяти и git-история знаний. Отдельной таблицы действий ревью в базе больше нет: решение по issue/индексу хранится прямо в самой записи, а решение по знанию (принятие/отклонение кандидата) — это git-коммит.

Для низкоуровневого осмотра остается Django Admin:

- `MemorySource` — источники памяти и их статус;
- `MemorySearchDocument` — прямые поисковые записи для знаний и исходных объектов;
- `MemoryKnowledgeItem` — метаданные знаний (включая pending-страницы), которые хранятся в файлах;
- `MemoryExternalConnectorJob` — единая очередь фоновых заданий памяти (reindex, reconcile, ingestion, внешние коннекторы);
- `MemoryAccessAudit` — журнал вызовов `memory.search`;
- `MemoryEvalCase` — сценарии eval/smoke проверок.

В admin намеренно не выводятся raw/safe/text path как обычные searchable поля. Для исходных объектов показываются только безопасные метаданные и ссылки.

## Ingestion корпоративных документов

Следующий блок памяти добавляет ingestion документов из локальной папки Windows Server или UNC path. Операционные правила описаны в `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

Коротко для пользователей и операторов:

- первый источник — отдельная read-only папка "документы для памяти", а не весь общий файловый ресурс;
- Windows services должны использовать UNC paths вида `\\SERVER\Share\Folder`, не mapped drives;
- raw-документы по умолчанию не копируются в `data/memory/`, хранится ссылка, hash и metadata;
- password-protected, encrypted, partial, suspicious и unsupported документы попадают в issue/review queue;
- graph schema proposals проверяются профильными экспертами и владельцем графа;
- graph runtime search в `memory.search` пока отключен; graph extraction и schema bootstrapping остаются отдельным подготовительным контуром.

## Автоупорядочивание файлов

Для файловых источников может быть включен отдельный режим автоупорядочивания:

- система создает исходную виртуальную структуру после анализа текущего источника;
- новые файлы кладутся во входной каталог, обычно `<source>/incoming/new`;
- пользовательские виртуальные структуры могут отличаться от общей структуры;
- популярные и устойчивые структуры используются как агрегированный сигнал для предложений;
- физический перенос выполняется только после согласования администратором;
- исходный файл удаляется только через карантин, retention и backup checkpoint.

Пользовательские виртуальные папки не дают доступ к файлу сами по себе. Если у пользователя нет права на исходный объект, наличие файла в виртуальной структуре не обходит проверку доступа.

Операторский UI:

```text
/memory/review/file-organization/
```

Пользовательский UI личной виртуальной структуры:

```text
/memory/files/
```

Администратор видит confidence, evidence/conflicts, предложения общей структуры и задания переноса. Обычный пользователь работает с входным каталогом и доступными ему виртуальными представлениями, но не согласует физический перенос.

## Операторские команды

Синхронизировать источники памяти из contracts:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_sync_source
```

Синхронизировать внутренние модули через универсальные source adapters:

```bash
python manage.py source_adapter_reconcile --source-code workorders --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code workorders --target all --backend all
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend all
```

`workorders` и `waiting_list` являются `source_data`: результат поиска должен показывать предупреждение, что это исходный объект, а не принятое знание. Для заявок AI может использовать wrapper `workorders.search`; он внутри вызывает `memory.search` в режиме `source_explicit` и сохраняет доменную проверку доступа.

Проверить состояние индексирования без Celery и без raw PII indexing:

```bash
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py memory_reindex --corpus all --backend all
```

Запустить synthetic smoke/security eval:

```bash
python manage.py memory_eval --dry-run
python manage.py memory_eval --output-json
```

Проверить автоупорядочивание файлов:

```bash
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_file_auto_organization_e2e
```

Eval report пишется только в `data/memory/eval/`.

## Ограничения текущей версии

- production scheduler/Celery не подключен;
- production full-text поиск использует PostgreSQL backend; SQLite FTS5 остается для dev/legacy и малых локальных запусков;
- LanceDB vector backend включен для локального векторного поиска; по умолчанию используется легкий deterministic test embedding profile;
- production multilingual embedding model нужно включать явно через `LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE` после подготовки модели и железа;
- FTS/vector индексы хранят перестраиваемые поисковые производные и метаданные, но не являются источником полного текста для выдачи;
- graph runtime search отключен и в trace отображается как `disabled/not_ready`;
- `memory.search` выполняет trusted-only gate, deterministic rank fusion и context packing без обязательного LLM;
- review UI для issues памяти и состояния поискового индекса доступен в `/memory/review/`; Django Admin остается техническим fallback;
- claim extraction, `MemoryClaim` и `MemoryBelief` перенесены на следующие этапы;
- ingestion MVP поддерживает local/UNC discovery, issue queue, text-like file ingestion, `.csv/.tsv/.xlsx/.xls`, bootstrap package и graph schema proposals;
- автоупорядочивание файлов поддерживает stable file identity, baseline virtual structure, incoming worker, агрегированные proposals и managed_fs copy/verify/quarantine;
- PDF/DOC/DOCX/images пока не извлекаются полноценно: такие документы попадают в issue queue до подключения production parser/OCR backend;
- ACL inheritance, raw vault, production cloud OCR/LLM и review каждого graph instance не входят в MVP;
- облачная маршрутизация для чувствительных случаев не включена.

Результаты `source_data` являются ссылками на исходные объекты, а не принятым знанием. В ответе они должны содержать предупреждение; обычные утверждения агента должны опираться на `knowledge` и citations.

## MVP расширение: память из AI-чата

AI-чат использует `memory.search` как read путь к memory service. Диалоги самого чата хранятся в `ChatSession` и `ChatMessage` и не считаются долговременной curated memory без отдельного pipeline.

`memory.search` принимает только корпус (`corpus`: `knowledge` по умолчанию или `source_data`) и `limit` (плюс `query`/`sensitivity`). Выбор именованного профиля ранжирования или сырых весов каналов ИИ-боту недоступен: единственный серверный профиль по умолчанию — гибрид FTS + вектор со слиянием RRF (ADR-0030 решение 6). `corpus=knowledge` ищет принятые знания с автоматическим fallback к `source_data`, если знаний не найдено; `corpus=source_data` ищет только явные исходные объекты. Дифференциация профилей ранжирования (ADR-0016: `precise`/`balanced`/`semantic_heavy`/`source_content`/`source_semantic`/`graph_future`) — отложенный архитектурный долг: концепция не удалена, но не подключена к runtime и возвращается только тогда, когда `memory_eval` на реальном корпусе покажет измеримую пользу дифференциации профилей. В коде `apps/memory/retrieval.py` для этого есть ровно одна точка расширения — функция `_select_ranking_profile()`.

Для запросов вида "запомни" добавлен MVP-контур:

- по умолчанию знание пишется в персональную память пользователя;
- запись в общую память организации требует явного намерения пользователя и соответствующего права;
- `memory.remember` пишет файл знания и делает git commit синхронно (ADR-0030): ответ сразу содержит `memory_id`, `knowledge_file_path`, `knowledge_file_commit` и `index_status` — очереди со `status=queued`/`job_id` больше нет;
- **кандидатство personal -> organization теперь идет через git-примитив `propose -> pending -> review -> stable`**, а не через отдельную таблицу кандидатов: ночная рефлексия (`python manage.py knowledge_reflection_worker`) для знания с высокой важностью создает страницу в `org/` с `lifecycle: pending` в frontmatter — это реальный файл и git-коммит, но обычный `memory.search` его не находит;
- владелец знаний принимает или отклоняет кандидата в `/memory/review/pending/`: принятие переводит `lifecycle` в `current` и коммитит слияние — страница сразу становится доступна `memory.search`; отклонение фиксируется отдельным git-коммитом и никогда не индексируется;
- то же самое понижение классификации (ручная правка frontmatter, снижающая `sensitivity`/`scope_tokens`), которое `memory_reconcile` держит "на паузе" до явного ревью, отображается в том же разделе `/memory/review/pending/`;
- пользователь сможет исправлять и удалять свою персональную память через чат;
- секреты сохраняются только через secret handle: агент видит `<SECRET_HANDLE:...>` и metadata, но не значение секрета;
- MVP secret backend использует Vaultwarden-compatible external link: пользователь сам вводит/читает secret value во внешнем vault UI.

**Мягкое удаление.** Удаление личного знания через чат помечает файл `status: deleted` и убирает его из проекций и выдачи — текст при этом остается в истории git знаний (`data/knowledge_repo/`), это осознанное поведение (ADR-0030), а не утечка. Настоящее необратимое стирание текста (например, по требованию отозвать источник) — это отдельный административный runbook на основе `git filter-repo`, а не обычная операция удаления через чат или review UI.

Архитектурное решение: `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`, `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` (решения 1 и 4).
Implementation plan: `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`.

Операторская команда рефлексии (регенерация `index.md`/`log.md` и предложение кандидатов):

```bash
python manage.py knowledge_reflection_worker --dry-run
python manage.py knowledge_reflection_worker
python manage.py memory_reconcile --dry-run
```

## Как проверить пользователю

1. Открыть AI-чат под обычным пользователем.
2. Задать запрос по теме, которая точно должна быть в сохраненных знаниях.
3. Убедиться, что ответ содержит citations.
4. Попросить найти данные вне своего scope и убедиться, что контекст не возвращается.
5. Администратору проверить `MemoryAccessAudit`: должны быть записи с `policy_decision=allowed` или `denied`, `query_hash`, returned ids и retrieval trace.

Если память еще не индексировалась, пустой результат `memory.search` является нормальным.
