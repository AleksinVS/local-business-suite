# План: текст знания только в файле знания

Статус: реализовано, ожидает приемки.

Дата: 2026-05-22.

Связанные документы:

- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0013-file-only-knowledge-body.md`;
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`;
- `docs/planning/active/memory-file-only-knowledge-body.md`.

## Назначение

Этот план закрывает главный оставшийся разрыв файловой памяти: текст знания сейчас хранится и в файле, и в `MemoryKnowledgeItem.text`.

Цель: сделать файл знания единственным источником текста знания. База хранит только метаданные, индексы хранят только перестраиваемые производные данные.

## Итог реализации

На 2026-05-22 целевой срез реализован:

- `MemoryKnowledgeItem` больше не хранит поле `text`;
- `MemoryClaim` удален из MVP-схемы;
- `MemorySearchDocument` хранит только технические поля поиска и ссылки на `MemoryKnowledgeItem` или `MemorySourceObject`;
- выдача текста знания идет через reader service и файл знания;
- индекс хранит `document_id`, служебные токены, права для ранней фильтрации и метаданные, но не хранит извлекаемый полный текст;
- `returned_chunk_ids` и `expected_chunk_ids` заменены на `returned_document_ids` и `expected_document_ids`.

## Текущее состояние

Сейчас реализовано:

```text
memory.remember
  -> MemoryWriteRequest
  -> MemoryKnowledgeItem.text
  -> файл знания
  -> MemorySearchDocument
  -> полнотекстовый индекс
```

Проблемы:

- `MemoryKnowledgeItem.text` дублирует файл знания;
- `knowledge_files.read_knowledge_item_file()` может вернуть текст из базы, если файл отсутствует;
- `knowledge_files.write_knowledge_item_file()` строит файл из `item.text`;
- `chat_memory.index_knowledge_item()` индексирует `item.text`;
- summary строятся из `item.text`;
- `MemorySearchDocument` дублирует часть полей знания;
- audit/eval все еще используют имена `chunk`;
- `MemoryClaim.text` является будущим дублирующим текстовым полем.

Так как внедрения еще не было, миграция данных не нужна. Поля можно удалить или переименовать напрямую.

## Целевая структура

### Файл знания

Единственное место хранения текста знания:

```text
data/knowledge_repo/
  org/sources/<source_code>/<year>/<knowledge_id>.md
  users/<user_id>/sources/<source_code>/<year>/<knowledge_id>.md
```

Файл содержит:

- front matter с метаданными;
- тело файла с текстом знания.

### `MemoryKnowledgeItem`

Карточка знания в `data/db/knowledge_meta.sqlite3`.

Хранит:

- идентификатор знания;
- область действия;
- владельца;
- тип знания;
- хэш текста;
- чувствительность;
- права;
- статус;
- ссылки на источник;
- путь к файлу;
- хэш файла;
- Git commit;
- статус индексации;
- происхождение;
- служебные метаданные.

Не хранит:

- полный текст знания;
- извлекаемый текст для выдачи агенту.

### `MemorySearchDocument`

Техническая карточка поиска.

Для `knowledge` хранит:

- `document_id`;
- `corpus_type=knowledge`;
- `object_kind=knowledge_item`;
- ссылку на `MemoryKnowledgeItem`;
- `index_status`;
- `body_hash`;
- `indexed_at`;
- минимальные технические метаданные.

Не должен быть вторым источником:

- прав;
- чувствительности;
- ссылок на источник;
- смыслового текста знания.

Эти поля читаются из `MemoryKnowledgeItem`.

Для `source_data` `MemorySearchDocument` ссылается на `MemorySourceObject`, а смысловые поля читаются из `MemorySourceObject` и `MemorySource`.

### Поисковый индекс

Индекс хранится отдельно:

```text
data/indexes/fulltext/search.sqlite3
data/indexes/vector/
data/indexes/graph/
```

Индекс может хранить только производные данные:

- токены;
- векторы;
- ранжировочные признаки;
- `document_id`;
- технические признаки фильтрации.

Индекс не должен хранить извлекаемый полный текст знания. Текст для выдачи всегда читается из файла знания.

## Целевой workflow записи

```text
memory.remember
  -> MemoryWriteRequest queued
  -> knowledge_writer_worker
  -> очистка текста и секретов
  -> write_knowledge_file_from_text()
  -> atomic rename
  -> Git commit
  -> MemoryKnowledgeItem без поля text
  -> MemoryKnowledgeEvent
  -> MemoryIndexJob queued
```

Правила:

- очищенный текст живет только в памяти процесса;
- файл пишется до создания metadata-записи;
- metadata-запись содержит путь, хэши и commit;
- ошибка записи файла не должна создавать активное знание в базе;
- отсутствие файла после записи считается ошибкой.

## Целевой workflow индексации

```text
knowledge_index_worker
  -> выбирает MemoryKnowledgeItem с index_status=indexing_pending
  -> reader service читает файл знания
  -> проверяет хэш
  -> создает/обновляет MemorySearchDocument
  -> передает производные данные в индекс
  -> ставит index_status=ready
```

Правила:

- индексатор не читает `MemoryKnowledgeItem.text`, потому что такого поля нет;
- если файл не найден или хэш не сходится, `MemoryKnowledgeItem.index_status=failed`;
- выдача пользователю не идет из индекса.

## Целевой workflow поиска

```text
memory.search
  -> поисковый индекс возвращает document_id
  -> загрузка MemorySearchDocument
  -> загрузка MemoryKnowledgeItem или MemorySourceObject
  -> проверка прав, чувствительности и надежности источника
  -> чтение файла знания reader service
  -> возврат text + citations
```

Для `knowledge` текст всегда читается из файла.

Для `source_data` результат по умолчанию возвращает только безопасные метаданные и ссылку на источник. Полный исходный текст не хранится в памяти как постоянный слой.

## Summary

Summary-файлы строятся только из файлов знаний:

```text
data/knowledge_repo/org/_summary.md
data/knowledge_repo/users/<user_id>/_summary.md
```

Порядок:

```text
MemoryKnowledgeItem queryset
  -> для каждого item читать файл знания
  -> собрать summary
  -> atomic write
  -> Git commit
```

Если файл знания отсутствует, summary builder должен зафиксировать ошибку целостности и пропустить item или завершиться ошибкой в строгом режиме.

## Редактирование и удаление

Редактирование:

```text
memory.edit
  -> reader проверяет существующий файл
  -> writer пишет новую версию файла
  -> обновляет hash/commit/index_status
  -> ставит переиндексацию
```

Удаление:

```text
memory.delete
  -> status=deleted
  -> файл знания помечается tombstone или переносится по принятому правилу
  -> MemorySearchDocument=index_status=deleted
  -> индекс деактивируется
```

Для MVP допустимо оставить файл в Git-истории и пометить metadata как `deleted`; физическое удаление из Git не требуется.

## `MemoryClaim`

`MemoryClaim` - это будущая карточка отдельного проверяемого утверждения.

Она нужна, когда система должна не просто хранить знание, а сравнивать противоречивые утверждения из разных источников.

Пример:

```text
Claim A: "Ответственный за закупки - Иванов"
Claim B: "Ответственный за закупки - Петров"
```

У каждого claim должны быть:

- источник;
- доказательства;
- статус проверки;
- срок действия;
- уверенность;
- связь с принятым знанием или кандидатом.

Для текущего MVP `MemoryClaim` не нужен в обычном пути:

- `memory.remember` его не создает;
- `memory.search` его не возвращает;
- claim не должен хранить копию текста знания;
- если модель остается, она должна быть выключенной заготовкой без полного текстового тела.

Рекомендуемое решение для этого блока: убрать `MemoryClaim.text` и все активные helpers/admin/tests, которые делают `MemoryClaim` частью MVP. Если это проще и не ломает контракты, удалить `MemoryClaim` из текущей схемы и вернуть отдельным будущим блоком claim-governance.

## Разрывы, которые закрывает блок

| Разрыв | Что сделать |
|---|---|
| Текст знания в `MemoryKnowledgeItem.text` | Удалить поле и все чтение/запись этого поля |
| Fallback чтения из базы | Удалить fallback, отсутствие файла считать ошибкой |
| Индекс хранит извлекаемый текст | Перевести индекс на производные данные без выдачи body |
| Summary строятся из базы | Читать файлы знаний |
| `MemorySearchDocument` дублирует смысловые поля | Оставить только технические поля и ссылки |
| Старые `chunk`-имена | Переименовать в `document` |
| `MemoryClaim.text` | Изолировать, удалить текстовое поле или удалить модель из MVP |

## Не входит

- новая стратегия графового поиска;
- выбор production-векторного backend;
- внешний API памяти;
- изменение хранения секретов;
- перенос уже несуществующих production-данных.

## Проверки готовности

- В модели `MemoryKnowledgeItem` нет поля `text`.
- В модели `MemoryClaim` нет поля полного текста или модель удалена из MVP.
- `memory.remember` создает файл знания и metadata без записи текста в базу.
- `memory.search` возвращает текст только после чтения файла.
- `memory_verify_knowledge_files --strict` падает при отсутствии файла или несовпадении хэша.
- `knowledge_index_worker` читает текст из файла, а не из базы.
- Summary строятся из файлов.
- Полнотекстовый индекс не содержит извлекаемого полного body знания.
- Audit использует `returned_document_ids`.
- Eval использует `expected_document_ids`.
- Unit-тесты и e2e-тесты проходят.

## Проверочные команды

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests
./.venv/bin/python manage.py memory_verify_knowledge_files --strict
./.venv/bin/python manage.py memory_file_backed_e2e
./.venv/bin/python manage.py memory_eval --dry-run
npm run test:e2e
git diff --check -- . ':(exclude)BACKLOG.md'
```
