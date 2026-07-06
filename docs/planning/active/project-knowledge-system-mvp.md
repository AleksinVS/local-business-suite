# План реализации: база проектных знаний для ИИ-агентов (kb) — MVP

**Статус:** готов к исполнению после принятия ADR · **Дата:** 2026-07-06
**Проектный документ:** `docs/architecture/project-knowledge-system-v0.1.md` (версия 0.5; далее — «проект»)
**Целевая аудитория:** агент-исполнитель, в том числе со слабой LLM. Все решения уже приняты — исполнителю запрещено их менять; при противоречии или пробеле — остановиться и спросить владельца.

---

## 0. Правила для исполнителя

1. Выполняй задачи T0–T6 строго по порядку. Не начинай следующую, пока не пройдены проверки текущей.
2. Ничего не проектируй заново: DDL, алгоритмы, форматы и коды выхода заданы в этом плане дословно. Если план и проект расходятся — прав этот план (он новее); сообщи о расхождении в отчёте.
3. Write scope (за пределами — не трогать): `scripts/dev/kb.py`, `scripts/dev/tests/`, `docs/knowledge/`, `docs/adr/` (один новый ADR), раздел в `AGENTS.md` (задача T6). Временные файлы — только в `.local/`.
4. Запрещено: менять `apps/`, `contracts/`, зависимости проекта; добавлять библиотеки (только stdlib + PyYAML, PyYAML уже есть в проекте); писать в `kb.sqlite3` мимо kb.py; git-хуки.
5. Все файлы, которые создаёшь в `docs/knowledge/` и `scripts/`, записывай с переводами строк **LF** и кодировкой UTF-8 без BOM.
6. Каждая задача заканчивается запуском указанных проверок и фиксацией их фактического вывода в отчёте исполнителя.

---

## 1. Зафиксированные решения (не менять)

| Решение | Значение |
|---|---|
| CLI | один файл `scripts/dev/kb.py`, запуск `python scripts/dev/kb.py <команда>` |
| Зависимости | Python stdlib (`sqlite3`, `hashlib`, `subprocess`, `argparse`, `json`, `re`, `pathlib`, `datetime`) + `yaml` (PyYAML) |
| Канон | `docs/knowledge/` (markdown + YAML frontmatter), только LF |
| Проекция | `.local/knowledge/kb.sqlite3`, полностью пересобираемая |
| Токенизатор FTS5 | `unicode61 remove_diacritics 2`, `prefix='2 3'` (НЕ trigram) |
| FTS-таблица | standalone (без `content=`), дубликат текста допустим |
| Идентификатор страницы | путь относительно `docs/knowledge/` без `.md`, разделитель всегда `/` |
| Акторы | `agent`, `maintenance`, `human`; git-трейлер `KB-Actor: agent|maintenance` |
| Хэши | sha256 от нормализованного содержимого (CRLF/CR → LF) |
| Блокировка | `BEGIN IMMEDIATE`; занято → «sync уже выполняется — пропуск», код выхода 0 |
| Коды выхода | 0 — успех/пропуск; 1 — ошибки валидатора; 2 — внутренняя ошибка |

---

## 2. Артефакты

```
scripts/dev/kb.py                       # CLI (T1–T5)
scripts/dev/tests/test_kb.py            # unit + e2e тесты (T1–T6)
scripts/dev/tests/fixtures/kb_bundle/   # тестовый бандл (T2)
docs/knowledge/                         # канон (T0, наполнение — фаза 2 отдельной задачей)
docs/adr/ADR-00XX-project-knowledge-base.md   # ADR (T6; номер — следующий свободный)
```

---

## 3. Спецификации файлов фазы 0 (создать дословно, T0)

### 3.1 `docs/knowledge/.gitattributes`

```
* text eol=lf
```

### 3.2 `docs/knowledge/schema/concept-types.yaml`

```yaml
# Контролируемый словарь типов концептов.
# status: approved | proposed. Ставить approved может только владелец (инвариант №7 проекта).
# Агент может ДОБАВЛЯТЬ записи со status: proposed (с полем rationale).
types:
  - name: domain
    status: approved
    description: Предметная область / подсистема верхнего уровня
  - name: component
    status: approved
    description: Приложение, модуль, сервис
  - name: integration
    status: approved
    description: Внешняя система и контур обмена с ней
  - name: pattern
    status: approved
    description: Принятый паттерн или конвенция (со ссылкой на решение)
  - name: constraint
    status: approved
    description: Ограничение среды, deployment, регуляторики
  - name: insight
    status: approved
    description: Неочевидный факт, причинность, «грабли»
  - name: source-summary
    status: approved
    description: Сводка объёмного первоисточника
```

### 3.3 `docs/knowledge/schema/edge-types.yaml`

```yaml
# Контролируемый словарь типов рёбер. Правила status — как в concept-types.yaml.
types:
  - name: part_of
    status: approved
    symmetric: false
    reads_as: "A входит в состав B"
  - name: depends_on
    status: approved
    symmetric: false
    reads_as: "A использует B"
  - name: interacts_with
    status: approved
    symmetric: true
    reads_as: "A обменивается с B"
  - name: implements
    status: approved
    symmetric: false
    reads_as: "A реализует решение/контракт B"
  - name: constrained_by
    status: approved
    symmetric: false
    reads_as: "на A действует ограничение B"
  - name: supersedes
    status: approved
    symmetric: false
    reads_as: "A замещает устаревший B"
  - name: contradicts
    status: approved
    symmetric: true
    reads_as: "A противоречит B"
  - name: relates_to
    status: approved
    symmetric: true
    reads_as: "A слабо связан с B"
```

### 3.4 Скелеты `docs/knowledge/schema/templates/<type>.md`

Каждый файл — заголовок-плейсхолдер `# <Название>` и перечисленные H2 (пустые). Состав H2 по типам:

| Файл | Разделы H2 (в этом порядке) |
|---|---|
| `domain.md` | Назначение · Состав · Ключевые решения · Ограничения |
| `component.md` | Назначение и границы · Устройство · Зависимости и контракты · Ограничения и грабли · Проверки |
| `integration.md` | Назначение · Контур обмена · Контракты и форматы · Ограничения и отказы · Проверки |
| `pattern.md` | Правило · Почему так · Где применяется · Антипаттерн |
| `constraint.md` | Ограничение · Источник и причина · На что влияет |
| `insight.md` | Факт · Почему так · Как обнаружено · Что делать |
| `source-summary.md` | О чём источник · Ключевые следствия · Порождённые концепты |

### 3.5 `docs/knowledge/index.md`

```markdown
# Карта знаний проекта

Точка входа для агентов. Читать в начале сессии; страницы искать через `kb query`, не сканированием.
Лимит этого файла — 150 строк; при росте выносить домены в под-индексы.

## Домены

_(заполняется в фазе 2: строка на домен — ссылка на страницу + одна фраза)_

## Сквозные ограничения

_(ссылки на страницы type: constraint)_

## Как пользоваться

- Поиск: `python scripts/dev/kb.py query "<вопрос>"`
- Страница: `python scripts/dev/kb.py page <id>`
- Протокол записи — AGENTS.md, раздел «База проектных знаний».
```

### 3.6 `docs/knowledge/eval/golden.yaml`

```yaml
# Golden set поиска: запрос → ожидаемые страницы (id без .md), k=3.
# Пополняется агентом при каждом промахе поиска («страница есть, но не нашлась»).
# Заполняется содержательно в фазе 2; пустой список допустим.
cases: []
```

---

## 4. Схема SQLite (полный DDL, авторитетная версия)

При `--full` файл БД удаляется и создаётся заново. `PRAGMA journal_mode=WAL;` при открытии.

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
-- ключи: schema_version='1', fts_config='unicode61', last_processed_commit,
--        last_maintenance_commit, last_full_rebuild (ISO 8601)

CREATE TABLE pages (
  id             TEXT PRIMARY KEY,  -- 'concepts/core/integrations-sdk'
  type           TEXT NOT NULL,
  title          TEXT NOT NULL,
  description    TEXT NOT NULL,
  lifecycle      TEXT DEFAULT 'current',
  timestamp      TEXT NOT NULL,     -- ISO 8601 из frontmatter
  front_hash     TEXT NOT NULL,     -- sha256 нормализованного frontmatter
  body_hash      TEXT NOT NULL,     -- sha256 нормализованного тела
  relations_hash TEXT NOT NULL      -- sha256 канонизированного блока relations (см. §5.4)
);

CREATE TABLE chunks (
  chunk_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id   TEXT NOT NULL,
  heading   TEXT NOT NULL,          -- "Заголовок H1 > H2 [> H3]"
  position  INTEGER NOT NULL,
  text      TEXT NOT NULL,
  text_hash TEXT NOT NULL           -- sha256 текста чанка (для rename-эвристики)
);
CREATE INDEX chunks_by_page ON chunks(page_id);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, heading, page_id UNINDEXED, chunk_id UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2',
  prefix = '2 3'
);

CREATE TABLE edges (
  src TEXT NOT NULL, type TEXT NOT NULL, dst TEXT NOT NULL,
  provenance TEXT,
  PRIMARY KEY (src, type, dst)
);
CREATE INDEX edges_by_dst ON edges(dst);

CREATE TABLE reconcile_queue (
  page_id     TEXT NOT NULL,
  reason      TEXT NOT NULL,        -- см. §6.4
  status      TEXT NOT NULL DEFAULT 'open',   -- open | dead
  detail      TEXT,                 -- контекст: старый путь, путь узла, id дубля и т.п.
  enqueued_at TEXT NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (page_id, reason)
);

-- Фаза 3 (T5 не реализует; создаётся заранее, пустая):
CREATE TABLE tree_nodes (
  path        TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  page_id     TEXT                  -- накрывающая страница (deepest-match) или NULL
);
```

---

## 5. Базовые функции (T1)

### 5.1 Нормализация и хэш

```
normalize(text) = text.replace('\r\n', '\n').replace('\r', '\n')
h(text)         = sha256(normalize(text).encode('utf-8')).hexdigest()
```

Любое чтение файлов бандла: `path.read_text(encoding='utf-8')` → сразу `normalize()`. Все хэши, чанки и FTS — только от нормализованного текста.

### 5.2 Парсинг страницы

Вход — нормализованный текст. Алгоритм:

1. Текст обязан начинаться с `---\n`. Найти следующую строку, равную `---` (или `---` в конце файла). Нет — результат `invalid("no frontmatter")`.
2. `front_text` — между разделителями; `body_text` — всё после закрывающего `---\n`.
3. `yaml.safe_load(front_text)` → dict. Исключение или не-dict — `invalid("yaml error: ...")`.
4. Обязательные поля `type`, `title`, `description`, `timestamp` — непустые строки (`timestamp` дополнительно парсится `datetime.fromisoformat`, суффикс `Z` заменить на `+00:00`). Нарушение — `invalid("missing/bad field X")`.
5. `relations` (если есть) — список dict с обязательными строками `type`, `target` и опциональной `provenance`. Элементы не по форме — отбрасываются с ошибкой валидатора E3 (страница при этом валидна).
6. `sources`, `covers`, `tags` (если есть) — списки строк; иное значение поля → как в п. 5 (элемент игнорируется, ошибка E3).

Результат: `ParsedPage(front: dict, body: str, front_text: str)` либо `invalid(причина)`.

### 5.3 Чанкинг

Вход — `body_text`, `title`, `description`. Правила:

1. Чанк 0: `text = title + "\n" + description`, `heading = title`, `position = 0`.
2. Сканировать строки тела. Строки внутри fenced-блоков (переключатель — строка, начинающаяся с ```` ``` ````) **не** считаются заголовками.
3. Заголовки: `^# ` (H1), `^## ` (H2), `^### ` (H3). H1 запоминается как имя страницы для `heading`-пути (если H1 нет — использовать `title`).
4. Текст до первого H2 (исключая строку H1) — чанк «преамбула» с `heading = <H1>`, если он непустой после `strip()`.
5. Каждый H2 открывает новый чанк до следующего H2. `heading = "<H1> > <H2>"`.
6. Если текст H2-чанка длиннее 2000 символов и содержит H3 — разрезать по H3: первый под-чанк (до первого H3) сохраняет heading H2, остальные — `"<H1> > <H2> > <H3>"`.
7. `position` — сквозная нумерация с 0. `text_hash = h(text)`.

### 5.4 Канонизация relations для `relations_hash`

`relations_hash = h(json.dumps(sorted([[r.type, r.target, r.provenance or ""] for r in relations]), ensure_ascii=False))`. Пустой список — хэш от `"[]"`.

### 5.5 Загрузка словарей

Из `schema/*.yaml` (нормализованных): множества `approved_concept_types`, `approved_edge_types`, `symmetric_edge_types`. Записи со `status != 'approved'` в множества не входят. Ошибка чтения/парсинга словаря — фатальная (код выхода 2): без словарей валидатор не работает.

---

## 6. Алгоритм `kb sync --actor {agent|maintenance} [--session-start] [--full]` (T2, T3)

`--actor` обязателен; отсутствие — ошибка аргументов (argparse, код 2).

### 6.1 Подготовка

1. Открыть/создать БД (`.local/knowledge/`, `mkdir -p`). Если `--full` — предварительно удалить файл БД. Создать схему §4 при отсутствии (`CREATE TABLE IF NOT EXISTS` недопустим для смены схемы: несовпадение `meta.schema_version` → сообщение «выполните kb sync --full», код 2).
2. Захватить блокировку: `conn.execute("BEGIN IMMEDIATE")` при `busy_timeout=0`; `sqlite3.OperationalError` → напечатать `sync уже выполняется другим процессом — пропуск` и выйти с кодом 0.
3. Загрузить словари (§5.5).

### 6.2 Данные от git (ровно 3 вызова за sync)

Все вызовы — `git -c core.quotepath=false`, кодировка вывода UTF-8, пути нормализовать к `/`.

- `HEAD = git rev-parse HEAD`.
- `dirty = git status --porcelain -- docs/knowledge` → множество незакоммиченных путей бандла.
- Батч истории: `git log --since=<D> --format=%x01%H%x02%ct%x02%(trailers:key=KB-Actor,valueonly=true) --name-only -- .` где `D` = (минимальный `timestamp` страниц в БД минус 1 день) либо 90 дней при пустой БД. Разобрать в список коммитов `{hash, ct, actor|None, files[]}` и построить `last_touch: path → max(ct)` по всем файлам репозитория.

### 6.3 Материализация

1. Сканировать `docs/knowledge/**/*.md`, исключая `schema/` и `index.md` (index.md — не страница; используется только lint'ом, §7).
2. Для каждого файла: id, нормализация, разбиение, хэши. Изменённым считается файл с `front_hash` или `body_hash`, отличным от строки в `pages` (или новый).
3. **Изменённые валидные**: UPSERT в `pages`; `DELETE FROM chunks WHERE page_id=?` и `DELETE FROM chunks_fts WHERE page_id=?`; вставить чанки заново (в обе таблицы, `chunk_id` из `chunks` продублировать в fts-колонку); `DELETE FROM edges WHERE src=?`; вставить рёбра, тип которых ∈ `approved_edge_types` (прочие — ошибка E2, не вставляются).
4. **Изменённые невалидные** (`invalid` из §5.2): строки `pages`/`chunks`/`edges` НЕ трогать (fail-soft — остаётся последняя валидная материализация); enqueue `(id, 'invalid-frontmatter', detail=причина)`. Новый файл, невалидный сразу, — в `pages` не попадает, только в очередь.
5. **Удалённые** (в `pages` есть, на диске нет): запомнить `(id, body_hash, title, description, set(text_hash))`, затем удалить из `pages`, `chunks`, `chunks_fts`, `edges (src=id)`.
6. **rename-candidate** (T5): для каждой пары (удалённая, новая в этом же прогоне): совпадение `body_hash`, ИЛИ (`title` И `description` равны), ИЛИ пересечение множеств `text_hash` ≥ 60 % от меньшего множества → enqueue `(new_id, 'rename-candidate', detail=old_id)`.

### 6.4 Акторная атрибуция и детекторы

Атрибуция изменённой страницы `p` (путь `f`):

- если `f ∈ dirty` (не закоммичено): актор = `human`, если передан `--session-start`; иначе актор = значение `--actor`;
- иначе (изменение пришло коммитами): собрать акторов коммитов из батча §6.2, затронувших `f`, новее `meta.last_processed_commit` (при пустом `last_processed_commit` — новее `pages.timestamp` страницы); коммит без трейлера = `human`; итоговый актор = `human`, если среди них есть human, иначе `maintenance`, если есть maintenance, иначе `agent`.

Детекторы (enqueue = `INSERT INTO reconcile_queue ... ON CONFLICT(page_id, reason) DO UPDATE SET enqueued_at=excluded.enqueued_at, detail=excluded.detail` — attempts и status не сбрасывать):

| Причина | Класс | Точное условие |
|---|---|---|
| `human-edited` | A | актор изменения = `human` |
| `source-drift` | A | для каждой валидной страницы: существует путь `s` из `sources`+`covers` (без завершающего `/`), для которого в `last_touch` есть ключ, равный `s` или начинающийся с `s + '/'`, со временем > `timestamp` страницы. Проверяется для ВСЕХ страниц каждый sync (карта уже построена, это дёшево) |
| `desc-mismatch` | A | (T5) у страницы есть `covers`, и (`last_touch` файла `<cover>/.desc.json` > `timestamp` страницы, ИЛИ `description` страницы изменился в этом прогоне). detail = путь узла |
| `prose-changed` | B | страница изменена, `body_hash` изменился, `relations_hash` НЕ изменился, актор ≠ `maintenance` |
| `dup-candidate` | B | (T5) среди валидных изменённых страниц актора ≠ `maintenance`: существует другая страница с равным (без учёта регистра) `title` ИЛИ `description`. detail = id второй страницы |
| `invalid-frontmatter` | B | §6.3 п. 4 |
| `rename-candidate` | B | §6.3 п. 6 |

### 6.5 Завершение

1. `meta.last_processed_commit = HEAD`; при `--actor maintenance` дополнительно `meta.last_maintenance_commit = HEAD`; при `--full` — `meta.last_full_rebuild = now()`.
2. `COMMIT`.
3. Прогнать lint (§7) и напечатать отчёт: `N страниц (M изменено, K удалено); ошибок: X; предупреждений: Y; в очереди: Z`.
4. Код выхода: 1, если ошибок валидатора > 0, иначе 0.

---

## 7. Правила lint (T2 — E/W1–W5; T3/T5 — остальные)

Ошибки (валидатор): **E1** — `type` страницы ∉ approved; **E2** — тип ребра ∉ approved; **E3** — элемент frontmatter не по форме (§5.2 п. 5–6); **E4** — обязательное поле отсутствует/пустое (для страниц, попавших в fail-soft, дублируется причиной в очереди).

Предупреждения: **W1** — `target` ребра не существует в `pages`; **W2** — страница недостижима из `index.md` (BFS по markdown-ссылкам `](...)` из index.md и под-индексов + по рёбрам); **W3** — ребро на страницу с `lifecycle: superseded`; **W4** — дубль `title`; **W5** — страница длиннее 200 строк; **W6** — `index.md` длиннее 150 строк; **W7** — доля рёбер `relates_to` > 30 % от всех; **W8** — ребро `contradicts`/`supersedes` без `provenance`; **W9** — страница без единого исходящего ребра; **W10** — зоны `covers:` двух страниц совпадают или пересекаются на одном уровне (вложенность разной глубины — НЕ предупреждение, действует deepest-match).

---

## 8. Читающие команды (T4)

### 8.1 `kb query "<текст>" [--k 10] [--hops 1] [--type T] [--json]`

1. Построить FTS-запрос: токены = `re.findall(r'\w+', текст, re.UNICODE)`; каждый токен длиной ≥ 2 → `токен*`, длиной 1 — отбросить; соединить ` AND `. Пусто → сообщение «пустой запрос», код 0.
2. `SELECT page_id, chunk_id, heading, snippet(chunks_fts, 0, '', '', '…', 12) AS snip, bm25(chunks_fts) AS rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 20;` Ноль строк → повторить с соединителем ` OR `.
3. Агрегация: оценка страницы = минимальный `rank` её чанков; отфильтровать по `--type`; взять топ-`k` страниц; исключить `lifecycle: superseded`.
4. При `--hops ≥ 1`: BFS по `edges` (оба направления) от отобранных страниц по типам `part_of`, `depends_on`, `implements`, `interacts_with`, глубина = `--hops`; соседи, не вошедшие в топ, — отдельным блоком с типом и направлением ребра.
5. Вывод (текст): `id — title [type]` + до 3 строк `  · <heading>: <snip>`; блок `Соседи:` — `id (←type— from | —type→ from)`. `--json`: `{"pages":[{"id","title","type","score","sections":[{"heading","snippet"}]}],"neighbors":[{"id","via","from","direction"}]}`.

### 8.2 `kb neighbors <id> [--hops N] [--type T]` — BFS как в §8.1 п. 4 (при `--type` — только рёбра этого типа); вывод: ребро на строку `src —type→ dst`.

### 8.3 `kb page <id> [--section "<фрагмент заголовка>"]` — без `--section`: печать файла канона целиком; с `--section`: чанки страницы, где `heading` содержит фрагмент без учёта регистра; не найдено — список доступных `heading`, код 0.

### 8.4 `kb log [<id>]` — `git log --format='%h %ad %s [%(trailers:key=KB-Actor,valueonly=true)]' --date=short -- docs/knowledge[/<id>.md]`.

### 8.5 `kb queue [--dead] [--done <id> [--reason R]] [--defer <id> --reason R]`

- Без флагов: открытые позиции (`page_id · reason · detail · attempts`, сортировка: `human-edited` первыми, далее по `enqueued_at`) + счётчики триггеров: открытых позиций; страниц, изменённых после `meta.last_maintenance_commit` (по батчу git это считает sync — хранить в meta счётчик `changed_since_maintenance`, обновляемый в §6.5).
- `--done` — DELETE (без `--reason` — все причины страницы). `--defer` — `attempts += 1`; при `attempts >= 3` → `status='dead'`. `--dead` — список dead.

### 8.6 `kb eval [--k 3]` (T5)

Загрузить `eval/golden.yaml`. Для каждого case: прогнать §8.1 п. 1–3 (без соседей), взять топ-k id. Попадание = пересечение с `expect` непусто. `expect`-id, отсутствующие в `pages`, — пометить `[нет такой страницы]` и исключить case из знаменателя. Вывод: `hit-rate: H/N = X.XX` + список промахов (`q`, `expect`, полученный топ). Код выхода всегда 0.

---

## 9. Задачи

### T0 — скелет канона (фаза 0)

Создать файлы §3 дословно (7 шаблонов — по таблице §3.4). Обновить `docs/.desc.json`/`docs/knowledge/.desc.json` (создать) и запустить `node scripts/dev/generate-structure.js`.
**Проверки:** `git check-attr text eol -- docs/knowledge/index.md` показывает `eol: lf`; `python -c "import yaml; yaml.safe_load(open('docs/knowledge/schema/edge-types.yaml', encoding='utf-8'))"` без ошибок.

### T1 — каркас и базовые функции

`scripts/dev/kb.py`: argparse-каркас всех команд (нереализованные — «не реализовано», код 2); функции §5 (normalize, h, parse_page, chunk, relations_hash, load_vocab).
**Проверки:** `python -m pytest scripts/dev/tests -q -k "normalize or parse or chunk"` — тесты U1–U7 (§10) зелёные.

### T2 — sync-ядро и lint-базис

§6.1–6.3, §6.5 без детекторов; lint E1–E4, W1–W5; тестовый бандл-фикстура (5–6 страниц, включая одну намеренно битую и одну с ребром на несуществующую цель).
**Проверки:** U8–U14; вручную: два подряд `kb sync --actor agent` на фикстуре — второй печатает `0 изменено`.

### T3 — акторы, детекторы ядра, очередь

§6.2 (батч git), §6.4 (`human-edited`, `source-drift`, `prose-changed`, `invalid-frontmatter`), §8.5, W6–W9.
**Проверки:** U15–U21; сценарный тест S1 (§10).

### T4 — читающие команды

§8.1–8.4.
**Проверки:** U22–U26.

### T5 — расширение (фаза 1.5)

Детекторы `dup-candidate`, `rename-candidate`, `desc-mismatch`; `kb eval`; W10.
**Проверки:** U27–U31.

### T6 — интеграция и приёмка

e2e-тест E1 (§10); ADR `docs/adr/ADR-00XX-project-knowledge-base.md` (контекст, решение: SQLite-проекция + OKF-отступление по `log.md`; статус Proposed — принимает владелец); раздел «База проектных знаний» в AGENTS.md — скопировать приложение А проекта (v0.5) дословно; обновить `.desc.json` затронутых директорий + `node scripts/dev/generate-structure.js`; финальный отчёт с фактическим выводом всех проверок.
**Проверки:** полный `python -m pytest scripts/dev/tests -q`; чек-лист приёмки §11.

---

## 10. Тест-план (минимальный обязательный набор)

Unit (fixtures — `scripts/dev/tests/fixtures/kb_bundle/`):

- **U1** normalize: `"a\r\nb\rc"` → `"a\nb\nc"`; **U2** hash CRLF == hash LF (критерий приёмки eol);
- **U3** parse: валидная страница → 4 обязательных поля; **U4** отсутствие `type` → invalid; **U5** битый YAML → invalid; **U6** relations без `target` → элемент отброшен, E3;
- **U7** chunk: страница с H1+2×H2+H3 и fenced-блоком с `## внутри` → правильные границы и heading-пути; чанк 0 = title+description;
- **U8** sync создаёт БД и строки pages/chunks/fts/edges; **U9** повторный sync — ноль изменений (идемпотентность); **U10** битая страница: fail-soft (старая версия в pages остаётся, очередь `invalid-frontmatter`); **U11** E1/E2 дают код выхода 1; **U12** удаление файла чистит pages/chunks/fts/edges; **U13** W1 на битое ребро; **U14** конкурентный sync: второй процесс (subprocess) → «пропуск», код 0;
- **U15** незакоммиченная правка + `--session-start` → `human-edited`; **U16** та же правка без `--session-start` при `--actor agent` → НЕ `human-edited`; **U17** прose-changed: правка тела без relations → в очереди; правка тела+relations → нет; **U18** актор `maintenance` не взводит prose-changed; **U19** source-drift: коммит в путь из `covers` после timestamp → в очереди (фикстура с временным git-репо); **U20** очередь: две причины одной страницы сосуществуют; **U21** `--defer` ×3 → status dead;
- **U22** query находит страницу по слову из тела; **U23** по слову из description (чанк 0); **U24** короткий токен «AI» находится (валидация выбора unicode61); **U25** --hops 1 добавляет соседа по `part_of`; **U26** page --section возвращает раздел;
- **U27** rename: mv + правка одной строки → `rename-candidate` (эвристика перекрытия чанков); **U28** dup по равному title; **U29** desc-mismatch при коммите `.desc.json` позже timestamp; **U30** eval: попадание и промах считаются верно; **U31** eval с несуществующим expect-id исключает case.

Сценарный **S1**: init git-репо во временной папке → бандл → коммит с трейлером → sync (пусто в очереди) → правка файла человеком (без коммита) → `sync --session-start --actor agent` → `human-edited` в очереди → коммит без трейлера → sync → причина сохраняется → `queue --done` → пусто.

e2e **E1**: полный цикл на фикстуре — `sync --full` → `query` возвращает ожидаемую страницу в топ-3 → `neighbors` → `page --section` → битая страница → fail-soft → `queue`. Оформить как pytest-тест, вызывающий CLI через `subprocess`.

## 11. Чек-лист приёмки (переносится в отчёт T6 с фактическими цифрами)

1. `kb sync --full` детерминирован (повторный прогон — «0 изменено»).
2. U2 зелёный: хэш не зависит от eol.
3. Дельта-sync < 1 с; полная пересборка фикстуры < 10 с; query < 200 мс (замер `time.perf_counter` в e2e).
4. U14: конкурентный sync пропускается.
5. U15/U16: акторная модель работает (правки агента не считаются человеческими).
6. U24: короткие термины ищутся.
7. lint на чистой фикстуре — ноль ошибок и ноль предупреждений, кроме намеренных.
8. `kb eval` работает на непустом golden set (можно из фикстуры).

## 12. Вне объёма этого плана

Фаза 2 (наполнение корпуса, лимит 20–30 страниц, golden set 10–20 пар) и фаза 3 (`tree_nodes`, обогащение карты) — отдельные задачи после приёмки MVP и принятия ADR владельцем. Продуктовая система памяти (`apps.memory`) не затрагивается ни одним шагом этого плана.
