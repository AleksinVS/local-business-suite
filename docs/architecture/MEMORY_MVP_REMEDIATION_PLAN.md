# План исправления разрывов MVP-памяти

Статус: реализовано в workflow-блоке `workflow/active/memory-mvp-remediation/`.

Дата: 2026-05-21.

Связанные документы:

- `docs/adr/ADR-0010-memory-mvp-simplification.md`;
- `docs/architecture/MEMORY_MVP_SIMPLIFICATION_PLAN.md`;
- `workflow/active/memory-mvp-simplification/TASK_ACCEPTANCE.01-05.md`.

## Назначение

Этот документ фиксирует исправление трех замечаний, найденных после реализации упрощения MVP-памяти:

1. Сохраненное через `memory.remember` знание не находится обычным `memory.search`.
2. `MemoryBelief` все еще физически вводится в схему MVP.
3. `memory.remember` стал синхронным сохранением, хотя целевое поведение - постановка задачи в очередь и возврат статуса.

Цель исправления - вернуть очередь как основной путь запоминания, сделать обработанную память доступной для поиска и убрать `MemoryBelief` из MVP-схемы, если миграция еще не является опубликованным контрактом.

Итоговое поведение текущей ветки:

- первичный вызов `memory.remember` возвращает `status=queued` и не создает `MemoryKnowledgeItem`;
- совместимый обработчик очереди переводит запрос в `accepted`, создает `MemoryKnowledgeItem` и индексирует его в стандартный полнотекстовый backend;
- обычный `memory.search` после обработки находит сохраненный `memory_chunk`;
- `MemoryBelief` удален из модели, миграции MVP, admin-регистрации, сервисов и MVP-тестов;
- `MemoryClaim` оставлен как будущая заготовка, но обычный remember path его не создает.

## Принятые решения

### 1. `memory.remember` снова только ставит задачу в очередь

Обычный AI-инструмент `memory.remember` должен:

- проверить права пользователя;
- создать `MemoryWriteRequest` со статусом `queued`;
- создать `MemoryIndexJob` со статусом `pending`;
- вернуть `request_id`, `job_id`, `status=queued`, `target_scope`, `queued_at`;
- не выполнять извлечение, запись файлов и индексацию прямо в вызове инструмента.

Обработка выполняется отдельным контуром:

```text
memory.remember
  -> MemoryWriteRequest queued
  -> MemoryIndexJob pending
  -> memory_reflect_chats или новый совместимый обработчик очереди
  -> process_memory_write_request
  -> MemoryKnowledgeItem
  -> MemorySnapshot / MemoryChunk
  -> полнотекстовый индекс
  -> графовые факты текущего MVP, если применимо
```

Прямой синхронный helper допустим только в тестах или внутреннем обслуживании, если он явно не используется AI-инструментом и не называется обычным путем.

### 2. Обработанное знание должно находиться через `memory.search`

После обработки очереди сохраненное знание должно попадать в поисковые механизмы.

Минимальное требование MVP:

- `MemoryKnowledgeItem` индексируется как `MemorySnapshot` и `MemoryChunk`;
- текст попадает в текущий полнотекстовый индекс через `SQLiteFTSMemoryBackend`;
- `memory.search` по словам сохраненного знания возвращает `memory_chunk`;
- права доступа, чувствительность и надежность источника продолжают проверяться;
- секреты не попадают в индекс значениями.

Тест должен проверять полный путь:

```text
memory.remember
  -> queued
  -> обработчик очереди
  -> accepted
  -> memory.search
  -> найден сохраненный текст
```

Если используется временный `DATA_DIR`, проверка должна использовать тот же индекс, который использует `memory.search` по умолчанию.

### 3. `MemoryBelief` убрать из MVP-схемы или вывести отдельной миграцией

Целевое решение ADR-0010: `MemoryBelief` переносится на следующие этапы.

Если миграция `0004` еще не опубликована в общей ветке и не является обязательной для сред:

- удалить `MemoryBelief` из модели;
- убрать `MemoryBelief` из миграции `0004`;
- убрать admin-регистрацию;
- убрать функции `create_belief_from_claim` и `compile_belief_digest`;
- убрать тесты, которые создают `MemoryBelief` ради проверки MVP.

Если миграция уже применялась в средах, но еще не принято удаление данных:

- оставить модель только как legacy/future объект;
- добавить отдельную задачу будущей безопасной миграции удаления;
- гарантировать, что обычный путь не импортирует и не вызывает `MemoryBelief`;
- документация должна прямо сказать, что таблица считается legacy/future и не используется MVP.

Для текущей рабочей ветки предпочтительный вариант - не вводить `MemoryBelief` в MVP-миграцию.

## Что не менять

- Физическое хранение сообщений чата.
- Детальную стратегию графового поиска.
- Общую модель файловых проекций `memory.current.json` и `memory.current.md`.
- Секреты и provider-neutral `SecretHandleBackend`, кроме проверки, что значения секретов не попадают в поиск.
- Внешние коннекторы и их отдельную очередь.

## Требуемые изменения

### Код

- `apps/ai/tooling.py` должен вызывать очередь, а не синхронное сохранение.
- `apps/memory/services.py` должен оставить публичный путь `queue_memory_remember_for_actor`.
- `remember_memory_for_actor` нужно удалить или сделать явным внутренним helper без использования AI-инструментом.
- `apps/memory/chat_memory.py:index_knowledge_item` должен индексировать `MemoryKnowledgeItem` в полнотекстовый индекс по умолчанию.
- Для графа можно оставить текущий backend без новой стратегии.
- `MemoryBelief` убрать из модели/миграции/admin/services/retrieval/tests, если нет требования сохранять уже примененные данные.

### Контракты

- `memory.remember` outputs должны снова описывать постановку задачи в очередь:
  - `request_id`;
  - `status`;
  - `target_scope`;
  - `queued_at`;
  - `job_id`;
  - `message`.
- `memory_id`, `event_id`, `processed_at` должны быть результатами обработки очереди, а не обычного вызова инструмента.

### Документация

Обновить:

- `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`;
- `docs/architecture/MEMORY_MVP_SIMPLIFICATION_PLAN.md`;
- `docs/guides/MEMORY_USER_GUIDE.md`;
- `docs/deployment/MEMORY_DEPLOYMENT.md`;
- workflow-отчеты текущего remediation-блока.

Документация должна говорить:

- пользовательский "запомни" ставит задачу в очередь;
- обработчик очереди сохраняет `MemoryKnowledgeItem`;
- после обработки знание доступно через `memory.search`;
- `MemoryBelief` не входит в MVP.

## Проверки приемки

- Вызов AI-инструмента `memory.remember` возвращает `queued`, а не `accepted`.
- После вызова создан `MemoryWriteRequest` со статусом `queued`.
- После вызова создан `MemoryIndexJob` со статусом `pending`.
- После запуска обработчика очереди запрос становится `accepted`.
- После обработки `memory.search` находит сохраненное знание.
- `MemoryBelief` не создается и не используется в обычном MVP-пути.
- Проверка миграций не предлагает создать `MemoryBelief`, если принято убрать модель из MVP.
- Старые проверки надежных источников, прав доступа и секретов проходят.

## Команды проверки

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests
./.venv/bin/python manage.py memory_eval --dry-run
npm run test:e2e
git diff --check -- . ':(exclude)BACKLOG.md'
```
