# Приведение системы памяти к архитектуре hybrid-knowledge v0.5

## Статус

Active planning. Готов к исполнению.

- Архитектурное решение: `docs/adr/ADR-0031-memory-alignment-hybrid-knowledge-v05.md`.
- Целевой концепт: `docs/architecture/hybrid-knowledge-architecture-v0.5.md` (версия 0.6 внутри документа).
- Текущая рабочая граница: `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`.
- Workflow-блок: `workflow/active/memory-hybrid-knowledge-v05-alignment/`.

## Цель

Выровнять ядро памяти с целевой архитектурой гибридной системы знаний и убрать необоснованную сложность:

- файл знания становится каноном: frontmatter авторитетен, база — пересобираемая проекция;
- прямая запись + pull-reconciler вместо push-очередей (шесть сущностей -> «файл + commit + reconciler»);
- ревизии и ревью через git-примитив `propose -> pending -> review -> stable`;
- рёбра графа из frontmatter `relations:` вместо LLM-extraction контура;
- автоупорядочивание файлов — в отдельное замороженное приложение;
- один профиль ранжирования поиска (RRF);
- заглушки и debt-артефакты для этапов data store (5а/5б), чтобы они гарантированно не потерялись.

Ожидаемое сокращение: с 31 модели до ~10–12, с 26 команд до ~8–10.

## Не цели

- Не реализовывать data store (этапы 5а/5б) в этом блоке — только заглушки в коде и debt-артефакты.
- Не реализовывать graph runtime search и профили ранжирования ADR-0016 (отложенный долг).
- Не строить слой доступа как отдельный веб-сервис (§9.1 концепта) — его роль продолжает играть Django-портал.
- Не менять бизнес-права портала, AG-UI контур, secret handles и trust-гейты.
- Не размораживать external connector и file auto-organization.

## Этапы и соответствие task packets

| Этап ADR-0031 | Task packet | Содержание |
|---|---|---|
| 1. Канон и reconciler | `01-file-canon-and-reconciler` | Кроссплатформенная блокировка записи, авторитет frontmatter, чистота канона, `needs-reconcile` вместо ошибки чтения, `memory_reconcile`, двойная работа + откат |
| 2. Запись и очереди | `02-direct-write-and-queue-collapse` | Синхронная запись в `memory.remember`, единая таблица-очередь с DLQ, вывод старых таблиц, `index.md` вместо `_summary.md` |
| 2. Ревью через git | `03-git-review-and-candidates` | Pending-страницы, кандидатство личное -> корпоративное на git-носителе, `log.md` из git, перенацеливание review UI |
| 3. Файловый контур | `04-filehub-extraction-and-freeze` | Вынос File Source Auto Organization в `apps.filehub`, заморозка |
| 4. Граф | `05-graph-contour-removal-and-edge-vocabulary` | Удаление extraction-контура, словарь типов рёбер, валидатор, детерминированный материализатор |
| Решение §6 | `06-single-ranking-profile` | Один профиль RRF, сокращение публичных режимов поиска до выбора корпуса |
| 5а/5б (debt) | `07-data-store-debt-stubs` | Заглушки в коде, DEBT-маркеры, тесты заглушек, сверка debt-записей backlog |
| Приемка | `08-docs-tests-acceptance` | Документация, e2e acceptance, Definition of Done |

Порядок: 01 -> 02 -> 03, затем 04/05/06 (могут идти параллельно), затем 07 -> 08.

## Ключевые проектные решения (из ADR-0031)

1. **Канон** — `data/knowledge_repo/**/*.md`. Frontmatter несет только присущие метаданные и workflow-флаги; `index_status`, версии индексов и собственные хэши файла живут в проекциях (инвариант №9 концепта).
2. **Идентичность** — путь файла (OKF); `knowledge_id` остается producer-defined стабильным ключом.
3. **Дисциплина одного писателя** — обязательная кроссплатформенная межпроцессная блокировка. Целевая среда — Linux и Windows в зависимости от условий внедрения, поэтому блокировка обязана работать на обеих. Текущий `knowledge_repo_lock` на `fcntl` на Windows — no-op; замена (единый интерфейс `msvcrt.locking`/`fcntl` или платформонезависимый эксклюзивный lock-файл) выполняется до отключения очереди записи.
4. **Удаление** — мягкое (`status: deleted`); настоящее стирание — runbook `git filter-repo`; фиксируется в пользовательской документации.
5. **Классификация** — валидатор reconciler не пропускает молчаливое понижение `sensitivity` ручной правкой.
6. **Миграция с откатом** — этап 1 работает в режиме двойной сверки (`memory_verify_knowledge_files`); авторитет переключается флагом только после чистой сверки.

## Этапы 5а/5б (data store) — управляемый долг

Не реализуются в этом блоке. Чтобы этапы гарантированно не потерялись, блок оставляет три вида артефактов:

1. **Заглушки в коде** (packet 07):
   - модуль `apps/memory/data_store.py` с типизированным интерфейсом `capture(dataset, observation)` / `query_dataset(dataset, query_name, params)`, поднимающим `NotImplementedError`, с docstring-ссылкой на ADR-0031 §7 и концепт §3.1;
   - маркеры `# DEBT(ADR-0031-5a): ...` в точке маршрутизации `memory.remember` (будущая fail-safe классификация «наблюдение vs знание») и в `memory_reconcile` (будущая материализация реестра датасетов из страниц `type: Dataset`);
   - unit-тест, фиксирующий контракт заглушки (интерфейс существует, поднимает `NotImplementedError`).
2. **Debt-записи в backlog** (`Later`, создаются вместе с этим планом): этап 5а (реестр датасетов + `capture`/`query`, первый потребитель — аналитический контур ADR-0008) и этап 5б (рефлексия-инициатор датасетов и миграция наблюдений) с критериями старта.
3. **Шаблон дескриптора датасета** (фиксируется здесь и переносится в операторскую документацию на этапе 5а):

```markdown
---
type: Dataset
title: Курсы валют
description: Ежедневные наблюдения курса валютной пары
sensitivity: internal
scope_tokens: [org:default]
status: active
lifecycle: current
dataset:
  name: fx_rates
  owner: <роль или пользователь>
  schema:
    - {name: date, type: date, required: true}
    - {name: pair, type: string, required: true}
    - {name: value, type: decimal, required: true}
  dedup_key: [date, pair]
  retention: P5Y
  row_indexing: none   # none | fts — opt-in индексирование строк, осознанное исключение
---

Назначение датасета, источники наблюдений, смысл полей.
```

Критерий старта 5а: приемка этапов 1–4 этого блока. Критерий старта 5б: работоспособный 5а.

## Риски

- **Гонки записи на Windows** — закрывается блокировкой в packet 01 до любых изменений пути записи.
- **Потеря пользовательских данных при выводе таблиц** — вывод только после миграции содержимого в файлы/архивные дампы; двойная сверка и откат на этапе 1.
- **Приватность git-истории** — персональная память переживает мягкое удаление в истории; семантика фиксируется в пользовательской документации, стирание — через runbook.
- **Отставание проекций между правкой и reconcile** — мягкая деградация, предусмотренная §7.1 концепта; окно ограничивается запуском reconciler после записи.

## Проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reconcile --dry-run          # появляется в packet 01
python manage.py memory_verify_knowledge_files
python manage.py memory_eval --dry-run
python manage.py memory_file_backed_e2e
python manage.py memory_file_content_search_e2e
```

Acceptance-сценарии e2e блока:

- ручная правка файла знания -> reconcile -> знание находится поиском, без ошибок чтения;
- `memory.remember` -> файл + git commit + индекс за один запрос;
- понижение `sensitivity` ручной правкой -> pending, не применяется молча;
- кандидат личное -> корпоративное проходит pending -> принятие -> находится в `org/`;
- повторный запуск reconciler без изменений не выполняет работу (идемпотентность);
- заглушка data store поднимает `NotImplementedError`, DEBT-маркеры присутствуют.

## Definition of Done блока

- Все восемь task packets приняты; e2e acceptance-сценарии проходят.
- `MEMORY_MVP_CURRENT_STATE.md`, `AGENTS.md` (перечень команд), `MEMORY_USER_GUIDE.md` (семантика удаления), `MEMORY_DEPLOYMENT.md` (backup `data/knowledge_repo/`, запуск reconciler) обновлены.
- `.desc.json` и `PROJECT_STRUCTURE.yaml` актуальны; backlog очищен от завершенного блока, debt-записи 5а/5б остаются в `Later`.
- Workflow-блок содержит executor reports, task acceptance и ретроспективу.
