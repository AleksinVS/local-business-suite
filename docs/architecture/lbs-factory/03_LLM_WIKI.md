# LLM-Wiki LBS Factory v3.4 — целевая модель с CROW/OKF

**Статус:** Accepted — согласованная архитектура по ADR-0051; **код CROW-интеграции ещё не реализован**.  
**Главные источники:** [ADR-0051](../../adr/ADR-0051-crow-pluggable-okf-knowledge-provider.md), [11_CROW_OKF_INTEGRATION.md](11_CROW_OKF_INTEGRATION.md), [12_CROW_IMPLEMENTATION_PLAN.md](12_CROW_IMPLEMENTATION_PLAN.md).  
**Открыто:** [политика ПДн в Wiki, CROW raw и Git](../../planning/active/knowledge-personal-data-git-policy-debt.md). Этот документ не устанавливает обязательное маскирование всех ПДн и не разрешает безусловную запись реальных ПДн в Git.

## 1. Роль LLM-Wiki и подключаемого CROW

LBS сохраняет существующие `apps.memory`, пользовательский Knowledge API, источники, ACL, аудит, Git-канон и статусы подтверждения. CROW (`crow-hq/llm-wiki-v2`) — **заменяемый KnowledgeOrganizationProvider** для назначенных корпусов: интеллектуальная маршрутизация, консолидация, объединение, организация и retrieval через нативный CROW. **OKF v0.2 — формат LBS, не CROW.**

~~~text
Источники / Интервью / Telegram / Web Chat / Битрикс24
                         |
                 LBS Knowledge API
                 /      |        \
              Access  Privacy    Confirmation
                 \      |        /
                  corpus_id → provider
                   /               \
       LBS MemoryProvider       LbsCrowAdapter
       (прочие корпуса)         (выделенные OKF bundles)
                                   |
                   native CROW ingest/search + ScopedReadStore
                                   |
             LBS-controlled writer / Git commit / recovery
                                   |
         OKF Markdown/Git + отдельно raw/.archive/.llmw2/sync
                         |
                 DB/FTS-проекции LBS
~~~

**Один corpus — один активный writer**, хотя LBS может использовать разные провайдеры для разных корпусов. CROW не владеет корпоративными правами, не пишет через собственный открытый для пользователей API и не является вторым независимым каноном. Отдельный CROW-сервис и переписывание алгоритмов upstream не входят в первый этап.

## 2. Сохранение текущих компонентов и роль FTS

Сохраняются `MemorySourceObject`, `MemorySearchDocument`, `SourceObjectEnvelope`, существующие Source Adapters, `memory.remember/search`, аудит, доменные права и legacy корпуса. Для CROW нужен локальный адаптер, отдельный проектор новых Note и совместимый OKF writer/reader. Не заменять `MemorySourceObject` на CROW `raw`.

**Для корпуса `provider=crow` основной интеллектуальный поиск знаний — CROW `Steps.select`**. Не строить второй конкурирующий пользовательский поиск по тем же Note. PostgreSQL FTS и существующие DB-проекции остаются для `source_data`, других не-CROW корпусов, регистрации, селекторов и аудита. После выключения CROW LBS обязан читать сами канонические Markdown-страницы, но не обязан обеспечивать прежнее качество classifier/CSV/history retrieval.

**Продуктивных внедрений Wiki, согласно ADR-0051, нет.** Для нового корпуса сразу внедрить корректный формат OKF и обновить тестовые данные без разработки большого legacy-мигратора. Наличие реальной инсталляции необходимо перепроверить перед сбросом или заменой чего-либо. Старые `lifecycle: pending` автоматически не раскрывать.

## 3. Операции Knowledge API

Логический контракт (не восемь новых сетевых сервисов):

~~~text
knowledge.save_working(text, source_ref, corpus_id, actor)
knowledge.search(question, corpus_ids, actor, audience)
knowledge.prepare_context(question, corpus_ids, actor, audience)
knowledge.get(knowledge_id, actor, audience)
knowledge.flag_confirmation(knowledge_id, reason, actor)
knowledge.list_confirmation(actor)
knowledge.confirm(knowledge_id, actor)
knowledge.reconcile(corpus_id, admin)
~~~

`save_working` маршрутизируется к активному провайдеру корпуса: в LBS-корпусе — к существующему контролируемому writer, в CROW-корпусе — к **адаптеру нативного `Wiki.ingest`**, без второго LBS-алгоритма организации заметок. Обычное `working`-знание пишется сразу, без human review.

**Критично различать две операции CROW:**

| Операция | Реальная семантика | Чего НЕ гарантирует |
|---|---|---|
| `knowledge.search` | Быстрый `Steps.select(ctx, scoped_root, question)` по разрешённому дереву; возвращает Note hits | Не запускает `_with_rows`, `_with_history` и `_conflicting` |
| `knowledge.prepare_context` | Native `Researcher.ask` с LBS `ScopedReadStore.load/read` и подменой **только** `Steps.answer=collect_context`, без финальной генерации CROW | Не создаёт автоматически межкорпусные противоречия и не гарантирует полноту при запрещённых raw/архивах |

`Researcher._with_history` выбирает старые версии лишь при настройке, предыдущей версии и соответствующем classifier-решении. `_conflicting` формирует **подсказку** о возможном противоречии, а не подтверждённый факт. `_with_rows` читает разрешённые CROW raw-таблицы в рамках бюджета. Итоговый ответ строит агент LBS; `Answer.citations` режима capture не считать provenance — цитаты собираются отдельно из разрешённых `knowledge_id/source_ref`.

**Native `Wiki.ask()` с неограниченным store НЕ использовать** в корпоративном пути: после `select` он может открыть `raw/.archive`. `ScopedReadStore` — предлагаемый узкий duck-typed wrapper, а не гарантированный публичный протокол CROW; закрепить версию upstream и добавить contract tests.

## 4. Единый канон OKF и отдельное служебное состояние

Пример первого запуска (bundles — **соседние**, не вложенные друг в друга):

~~~text
data/knowledge_repo/
  org/
    sources/                    # существующие LBS-корпуса
    crow/
      common/                   # CROW OKF bundle
        index.md / log.md / ...Note.md
        raw/                    # вне Git
        .archive/               # вне Git
        .llmw2/sync/            # вне Git
      accounting/               # второй самостоятельный bundle
      accounting-restricted/    # отдельная write-partition при необходимости
~~~

- **Git:** утверждённые для данного места хранения OKF Notes, индексы, журнал, версии и стабильные `knowledge_id`.
- **CROW raw/.archive/.llmw2/sync:** функционально необходимые вспомогательные источники, прежние редакции и курсоры; **не в Git**. Их защищать и восстанавливать **отдельно**.
- **PostgreSQL:** LBS Access, соответствие `space_id → bundle_id[]`, редкие Note-level ограничения, `MemoryKnowledgeItem/MemorySearchDocument` и аудит. Проекции можно пересоздать.
- **Домен/внешняя система:** исходные бизнес-объекты и оригиналы. CROW raw — подготовленная версия, а не обязательно побайтная копия оригинала.

`.gitignore` не останавливает рекурсивный обход файлов. Legacy `_walk_knowledge_files`, `memory_reconcile`, общий `org/index.md`/`org/log.md` и graph materializer **не должны читать/переиндексировать весь CROW-managed namespace**, включая `raw` и `.archive`. Для новых CROW Notes нужен отдельный LBS-проектор, не передающий их обратно legacy writer. `write_knowledge_item_file` сейчас пересобирает Frontmatter: нельзя им без нормализации перезаписывать CROW-страницы и терять `sources/id/generated` или неизвестные ключи.

## 5. OKF v0.2: обязательные поля и независимые статусы

Пример целевого Frontmatter Note (не текущая реализация writer):

~~~yaml
---
type: Note
id: "crow-note-a81fae39"
knowledge_id: "knw-maintenance-intake"
title: "Приём заявок"
description: "Фактические каналы регистрации заявок"
status: stable
lifecycle: current
confirmation_state: working
sensitivity: internal
sources:
  - id: s1
    resource: /raw/20261021-intake.md
    title: "Интервью технической службы"
---
~~~

**Не смешивать:**

- `status: draft|stable|deprecated` — OKF-статус; `stable` не значит подтверждено человеком. Внутренний `MemoryKnowledgeItem.status: active|superseded|deleted` получает явное отображение в LBS-проекторе.
- `confirmation_state: working|needs_confirmation|confirmed` — отдельная достоверность. `confirmed` требует подтверждения именно данной редакции; после смысловой машинной правки прежнее подтверждение не переносится автоматически.
- `lifecycle: current|pending` — отдельный LBS-контур; legacy `pending` не становится видимым из-за `status: stable`.

При записи не удалять unknown Frontmatter, `sources`, native ID, `knowledge_id` и валидные `verified`. Никаких списков пользователей/ролевых grants в YAML. Внутренние `index.md`/`log.md` должны соответствовать OKF v0.2; `log.md` имеет ISO-даты. Текущие схемы LBS не всегда поддерживают `type`/`status`/формат log — **исправить reader/writer/валидацию/фикстуры до первого реального корпуса**.

## 6. Запись и автоматическое объединение

1. LBS проверяет actor, аудиторию, источник, назначение/корпус и права целевого пространства. CROW не принимает эти решения.
2. Единый `prepare_content` LBS применяет **выбранную** политику к body/title/metadata/Origin перед native `raw` и любым вызовом модели; `external_llm` проверяется отдельно от `wiki_git/agent_context`. `SafeProjection` значит **допущенное**, не обязательно лишённое всех ПДн содержимое. [Открытая политика ПДн](../../planning/active/knowledge-personal-data-git-policy-debt.md) остаётся отдельной задачей.
3. LBS определяет **совместимую по write-ACL физическую partition ДО `Wiki.ingest`**. Native CROW может выполнять route/match/consolidate/merge/relate/plan/split внутри неё. Фильтрация `select` защищает чтение, но не предотвращает опасное cross-ACL объединение при ingest.
4. Внешний LBS writer lock и **читательский барьер** охватывают полную многофайловую операцию CROW: raw, Note, index, log, archive и sync. До Git-коммита LBS проверяет результат генерации (пути, ACL, запрещённые секреты/сведения, формат OKF), журналы и изменённые файлы. При прерывании операции не выдавать промежуточное состояние, восстановить или закрыть корпус.
5. LBS делает **один коммит того же канона**, raw/archive/sync исключены. Затем отдельный проектор регистрирует Note/обновляет индекс/кэш. Между коммитом и успешной проекцией **нельзя объявлять устаревший индекс актуальным**; canonical get может работать с явным `index_pending`.
6. `working` доступно без очереди review; `needs_confirmation` — отдельная необязательная отметка о достоверности, не реакция на privacy-block.

**Особый случай таблиц:** в CROW `Wiki.ingest_file(xlsx)` разбивает XLSX до `Steps.extract`. Поэтому при ограничениях на строки исходник нельзя отдавать такому методу и надеяться на последующее masking: LBS до CROW подготавливает разрешённый `sheet_text` по каждому листу и `Origin.id=file_id#sheet`, затем вызывает `Wiki.ingest(text=safe_sheet_text, origin=...)`. `Researcher._with_rows` и статистика иначе могут прочитать запрещённые строки.

## 7. Доступ до поиска, raw и ответа

Правило: **проверенный actor AND доступ к space AND зарегистрированная читаемая Note AND Note restrictions AND sensitivity/destination AND аудитория**. Note-level исключения **только сужают** доступ пространства. Текущий OR-`scope_tokens_match` сам по себе не обеспечивает это AND-наследование.

**Быстрый `select`:** до вызова `Steps.select` и любых classifier-операций LBS на основе кэшированного полного дерева доверенного процесса вычисляет batch ACL, затем создаёт request-local *копии Folder и Note* только с разрешёнными и безопасными `id/title/description/rel`, без body/sources/See also/запрещённых папок. В CROW `check_select` сверяет идентичности Note внутри **переданного scoped root**, поэтому разрешено выбирать Note-копии, если root и результат используют одни объекты. Классификатор не должен видеть запрещённые заголовки или пути.

**Полный `prepare_context`:** `ScopedReadStore.load()` отдаёт разрешённые Note с разрешёнными текстами из immutable bundle-кэша; `ScopedReadStore.read(rel)` проверяет LBS Access **каждого исходника и архивной версии** плюс privacy/egress назначения. Чтение raw/архива не становится разрешённым только из-за права видеть Note. Пропускать запрещённое с явным признаком **неполного контекста**, затем повторно проверять citations, ссылки `See also`, права и аудиторию ответа.

**Кэш:** штатный `WikiStore.load()` читает YAML и body в память. Загружать один базовый снимок на версию физического bundle, а не на каждый вопрос; сам снимок нельзя передавать модели. Создавать лёгкий scoped view на запрос, invalidate при изменении прав/версии. Для нескольких workers проверить версию через LBS; общий RAM-кэш между процессами **не предполагается**. `select_and_hydrate`, per-user persistent views и Source API — поздние оптимизации при измеренной пользе.

## 8. Подтверждения и статус сведений

Интервью → **сразу рабочая Note** с источником → доступ разрешённым агентам. `needs_confirmation` добавляет запись в неблокирующий реестр (противоречие, возможная устарелость, требование регламента), не задерживая сбор знаний. Реестр — перестраиваемая проекция OKF; сбой реестра не мешает writer.

`_conflicting` CROW формирует возможную подсказку при подготовке ответа, **не** автоматически достоверный спор и не обязательный human review. Privacy-block не переводить в `needs_confirmation`. Официальное подтверждение и изменение прав — отдельные полномочия. Смысловая правка подтверждённой Note требует новой оценки статуса.

## 9. Приватность и политика ПДн

Content Privacy Pipeline [10](10_CONTENT_PRIVACY_PIPELINE.md) — единая граница для Source Adapters, raw, индексов, Wiki и LLM; CROW **не** запускает вторую подсистему обезличивания. Текущие три профиля применяются **согласно выбранной политике назначения**; универсальное PII-сканирование и принудительное маскирование не утверждены. Для закрытого допустимого on-prem сценария CROW raw может включать реальные ПДн; для Git и внешней модели нужны **отдельные явные правила**.

До реальных чувствительных источников решить [долг по ПДн](../../planning/active/knowledge-personal-data-git-policy-debt.md): что допустимо в Git, raw, archive, FTS, бэкапах, какую LLM можно использовать и как удалять/пересоздавать производные знания. Пока — синтетический пилот или отдельно согласованные безопасные источники. Не раскрывать секреты в commit message, CROW index/log, trace или prompt. Проверять **и выход CROW после генерации**, не только подготовленный вход.

## 10. Восстановление и отключение модуля

CROW пишет несколько файлов без общей транзакции. Нужны один writer на namespace, барьер чтения во время записи, минимальный журнал/маркер незавершённой операции, предкоммитная валидация и тест прерывания между raw и Note, между Git и индексом. Для L0 не нужен распределённый координатор.

**Backup/restore:** комплект **Git + CROW raw + .archive + .llmw2/sync + конфигурация space/Access** и восстановимые БД-проекции; один Git clone не обеспечивает полную историю исходников. При аварии запрещено смешивать новый Note body со старым raw.

Выключение CROW запрещает новые вызовы и записи, **не удаляет OKF**. LBS читает канонические Note даже без CROW; полноценный classifier-select, строки таблиц и архивные подсказки без другого провайдера не обещаются. При смене provider новый writer включается только после проверки OKF и остановки прежнего.

## 11. Что не вводить заранее

Не внедрять полноценный второй интеллектуальный поиск по тем же CROW Notes, обязательный OpenFGA, публичный Source API внутри CROW, замену `MemorySourceObject` на raw, S3, event bus, собственный CROW fork, полную mixed-ACL обработку внутри одного bundle, per-user дерево и обязательный DLP/NER. Это возможные варианты эволюции с тестами, а не условия первого запуска.

**Лицензия CROW — AGPL-3.0-or-later:** до коммерческого включения, распространения или предоставления модифицированной сетевой службы провести лицензионную проверку и выбрать допустимый способ использования/лицензию.

## 12. Проверочная матрица (синтетические данные до политики ПДн)

| ID | Проверка | Результат |
|---|---|---|
| W-01 | OKF v0.2 страницы | `type/id/knowledge_id/status/sources`, сохранение неизвестных полей, корректные index/log |
| W-02 | Серия интервью | Рабочая Note без human-review, статус/источник, реестр не блокирует |
| W-03 | Подтверждённая Note изменена CROW | Старое confirmation не переносится |
| W-04 | 2 пространства + Note-level deny | Запрещённые title/description/folder не попадают в select/classifier |
| W-05 | Ingest несовместимых ACL | Нет cross-ACL merge/relate/plan, безопасная write-partition или отказ |
| W-06 | search против prepare_context | Быстрый select не выдаёт историю/CSV/conflict, полный контекст выдаёт только разрешённые |
| W-07 | Note доступна, raw запрещён | Note видна, raw не выдаётся; ответ помечен как неполный |
| W-08 | Egress закрыт | Нет облачного prompt с запрещённым текстом/заголовком |
| W-09 | Сбой между raw и Note | Read barrier/recovery не выдаёт полусостояние |
| W-10 | Сбой после commit до project | Нет устаревшего «current» индекса; reconcile возвращает состояние |
| W-11 | raw и archive вне Git и legacy обходов | Нет в `git ls-files`, FTS/org index и общем логе |
| W-12 | Повторный Origin, новая transform version | Идемпотентность и корректный update |
| W-13 | Отключённый CROW | Базовый read OKF без runtime; no new native writes |
| W-14 | Backup/restore | Git/raw/archive/sync/Access и ссылки восстановлены |
| W-15 | Обновление upstream | Contract tests ScopedReadStore/Researcher/Steps, проверка AGPL |
| W-16 | XLSX с row ACL | До CROW разделение/очистка, `_with_rows` не видит закрытые строки |

## 13. Основные документы

[11_CROW_OKF_INTEGRATION.md](11_CROW_OKF_INTEGRATION.md) — подробная архитектура и точные потоки. [12_CROW_IMPLEMENTATION_PLAN.md](12_CROW_IMPLEMENTATION_PLAN.md) — пакеты CROW-00..06, gate и отказные сценарии. [05_ROADMAP_AND_ACCEPTANCE.md](05_ROADMAP_AND_ACCEPTANCE.md) — Factory rollout. [07_ACCESS_ARCHITECTURE.md](07_ACCESS_ARCHITECTURE.md) — полномочия. [10_CONTENT_PRIVACY_PIPELINE.md](10_CONTENT_PRIVACY_PIPELINE.md) — единая разрешённая обработка.
