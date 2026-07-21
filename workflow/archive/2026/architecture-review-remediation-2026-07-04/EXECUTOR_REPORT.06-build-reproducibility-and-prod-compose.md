# Executor report: 06-build-reproducibility-and-prod-compose

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/archive/2026/architecture-review-remediation-2026-07-04/task-packets/06-build-reproducibility-and-prod-compose.json`

## Что сделано

### 1. Сборка ставит зависимости из lock-файлов, а не из `requirements.txt`

- `Dockerfile` (образ `web`): вместо `COPY requirements.txt .` + `pip install -r requirements.txt`
  теперь `COPY requirements.txt requirements.lock ./` + `pip install --no-cache-dir -r requirements.lock`.
  `requirements.txt` остаётся в образе только как человекочитаемый вход pip-compile
  (не используется для установки).
- `Makefile`: `install` ставит из `requirements.lock` вместо `requirements.txt`.
  Добавлены две новые цели:
  - `lock` — `$(PYTHON) -m piptools compile --output-file=requirements.lock requirements.txt`;
  - `lock-agent-runtime` — то же самое для `services/agent_runtime/requirements.lock`.
  Обе используют `$(PYTHON) -m piptools compile` (модульный вызов через venv-python)
  вместо голого `pip-compile`, чтобы не зависеть от того, попал ли скрипт `pip-compile`
  в `PATH`. Это эквивалент команды из пакета (`pip-compile --output-file=... ...`).
  Цель `check` (в т.ч. `check_staticfiles --fail`) не тронута.
- `pip-tools` (7.5.2) уже установлен в `.venv` этого окружения, но **не является
  задекларированной зависимостью проекта** (не в `requirements.txt`/`requirements.lock`) —
  это dev-инструмент. В Makefile и README явно указано, что для `make lock`/
  `make lock-agent-runtime` нужно `pip install pip-tools`.

### 2. `services/agent_runtime` — собственный lock (решение: нужен, не переиспользуем корневой)

Добавлен новый файл `services/agent_runtime/requirements.lock`, сгенерированный
`pip-compile` из `services/agent_runtime/requirements.txt` (7 пакетов: fastapi,
uvicorn[standard], httpx, langchain, langgraph, langchain-openai, mcp).
`services/agent_runtime/Dockerfile` теперь копирует и ставит зависимости из
него (`/tmp/agent-runtime-requirements.lock`), а не из `requirements.txt`.

**Почему отдельный lock, а не корневой `requirements.lock`:** корневой
`requirements.lock` резолвится из корневого `requirements.txt`, где помимо
LLM-стека есть Django, gevent, Pillow, ldap3, psycopg[binary], lancedb,
python-calamine, whitenoise, gunicorn, django-htmx — ни один из них
agent-runtime не использует и не устанавливает через свой отдельный минимальный
Dockerfile. Установка полного корневого lock в образ agent-runtime раздула бы
его лишними пакетами (включая тяжёлые C-расширения: psycopg[binary], Pillow,
gevent, pyarrow/lancedb) и противоречила бы существующему архитектурному
решению держать для этого сервиса отдельный slim-образ с собственным
`requirements.txt`. Поэтому у него должен быть и собственный lock.

**Наблюдаемый побочный эффект (не нарушение non-goals):** т.к. до этой задачи
lock для agent-runtime не существовал вовсе, независимая резолюция дала
немного другие версии транзитивных пакетов, совпадающих по имени с корневым
lock (например `langchain-core` 0.3.86 в agent-runtime lock против 0.3.84 в
корневом, `langsmith` 0.9.8 против 0.7.37, `openai` 2.44.0 против 2.33.0—
резолюция шла в разные моменты и по разным подмножествам констрейнтов).
Верхнеуровневые пины (`fastapi==0.116.2`, `langchain==0.3.28` и т.д.) в обоих
`requirements.txt` не менялись — non-goal «не менять версии зависимостей»
не нарушен: до задачи транзитивные версии agent-runtime вообще не были
зафиксированы (ставилось «что есть на PyPI сейчас»), поэтому фиксация впервые
не является «изменением» уже зафиксированной версии. Расхождение транзитивных
версий между `web` и `agent-runtime` для одноимённых пакетов — ожидаемо и
приемлемо для независимо собираемых и деплоящихся сервисов; если в будущем
понадобится строгий паритет версий между ними, это отдельная задача (не
входит в non-goals текущего пакета: не менять состав/менеджер зависимостей).

Проверка воспроизводимости (без изменения версий): для корневого
`requirements.lock` повторный прогон `pip-compile --output-file=requirements.lock
requirements.txt` дал **побайтово идентичный файл** — существующий
`requirements.lock` уже был актуален относительно `requirements.txt` и
перегенерация не потребовалась (файл не менялся).

### 3. `docker-compose.prod.yml` — не привязан к хосту, без мёртвых томов

- `env_file` у `web` и `agent-runtime` заменён с жёсткого
  `deployments/test-host/.env` на
  `${LOCAL_BUSINESS_ENV_FILE:?set LOCAL_BUSINESS_ENV_FILE to the path of the host env file, e.g. deployments/<host>/.env}`.
  Без переменной `docker compose` падает с понятной ошибкой; с переменной —
  использует указанный host-specific `.env`.
- Удалён мёртвый top-level блок `volumes: db: media: static: caddy_data: logs:`.
  Проверено: ни один сервис не монтирует именованные тома `db`/`media`/`static`/`logs`
  вообще; `caddy_data` в сервисе `caddy` смонтирован как bind-mount `./caddy_data:/data`
  (с `./`), а не как ссылка на top-level named volume `caddy_data:` — то есть
  и он был мёртвым объявлением. Оставлен только комментарий, поясняющий, почему
  секции `volumes:` больше нет.
- **Важное ограничение вне write_scope:** `scripts/linux/deploy.sh` (не входит
  в write_scope этого пакета) сегодня жёстко использует
  `deployments/test-host/.env` и **не экспортирует** `LOCAL_BUSINESS_ENV_FILE`
  перед вызовом `docker compose`. После этого изменения `deploy.sh` в текущем
  виде не сработает без правки. Это задокументировано как явный follow-up в
  `docs/deployment/DEPLOYMENT.md` (раздел «Env-файл хоста»), но сам скрипт
  я не трогал — он не входит в write_scope пакета 06.

### 4. Документация

- `README.md`:
  - `pip install -r requirements.txt` → `pip install -r requirements.lock` в
    обоих quickstart-блоках (Linux/VPS и Windows);
  - новый раздел «Воспроизводимая установка зависимостей» с объяснением
    отношения `requirements.txt` ↔ `requirements.lock` и командами
    `make lock` / `make lock-agent-runtime`.
- `docs/deployment/DEPLOYMENT.md`:
  - абзац в разделе «1. Docker» о том, что оба образа ставятся из lock-файлов;
  - новый раздел «Env-файл хоста (`LOCAL_BUSINESS_ENV_FILE`)» — что это,
    зачем, как задавать, и явное предупреждение про несовместимость текущего
    `scripts/linux/deploy.sh` без правки/экспорта переменной;
  - команды в «Полезные команды» и «Типовые проблемы» дополнены
    `export LOCAL_BUSINESS_ENV_FILE=...` и `sudo -E` (без `-E` `sudo` не
    передал бы переменную окружения дальше).

### 5. Сопутствующее (вне буквального write_scope, но требуется по AGENTS.md п.7)

- `services/agent_runtime/.desc.json` — добавлены записи для новых
  `requirements.txt`/`requirements.lock` этого сервиса (по аналогии с
  корневым `.desc.json`, где `requirements.lock` уже был описан).
- `PROJECT_STRUCTURE.yaml` перегенерирован (`make gen-struct` /
  `node scripts/dev/generate-structure.js`). **Побочный эффект:** генератор
  также добавил блок `learning/` (учебный git-submodule владельца, уже
  существовавший в файловой системе и описанный в `learning/.desc.json` до
  этой задачи, но не отражённый в `PROJECT_STRUCTURE.yaml` из-за более раннего
  коммита `b7b6ade`, не запустившего `gen-struct`). Это не относится к пакету 06,
  но неизбежно попало в diff, так как генератор строит файл из полного
  текущего состояния `.desc.json`, а не только из изменений этой задачи.

## Acceptance checks — фактический вывод

**1. `grep -n "requirements.lock" Dockerfile Makefile`**

```
Makefile:11:# Ставим зависимости из requirements.lock, а не из requirements.txt: lock
Makefile:15:	$(PYTHON_INSTALL) -r requirements.lock
Makefile:17:# Перегенерация requirements.lock из requirements.txt. Требует pip-tools
Makefile:19:# requirements.txt/requirements.lock как рантайм-зависимость.
Makefile:21:	$(PYTHON) -m piptools compile --output-file=requirements.lock requirements.txt
Makefile:26:	$(PYTHON) -m piptools compile --output-file=services/agent_runtime/requirements.lock services/agent_runtime/requirements.txt
Dockerfile:18:# Ставим зависимости из requirements.lock (сгенерирован pip-compile), а не из
Dockerfile:19:# requirements.txt: requirements.lock фиксирует версии всех транзитивных
Dockerfile:22:COPY requirements.txt requirements.lock ./
Dockerfile:23:RUN pip install --no-cache-dir -r requirements.lock
```

**2. `grep -n "test-host" docker-compose.prod.yml`**

Нет вхождений (команда ничего не вывела).

**3. `docker compose -f docker-compose.prod.yml config`**

`docker` был доступен в этом окружении (Docker 29.1.3, Docker Compose 2.37.1).
Проверено обоими сценариями:

Без `LOCAL_BUSINESS_ENV_FILE`:

```
error while interpolating services.agent-runtime.env_file.[]: required variable LOCAL_BUSINESS_ENV_FILE is missing a value: set LOCAL_BUSINESS_ENV_FILE to the path of the host env file, e.g. deployments/<host>/.env
exit code: 1
```

С `LOCAL_BUSINESS_ENV_FILE=deployments/test-host/.env` (реальный локальный
приватный env-файл этого чекаута, `deployments/` в `.gitignore`):

```
exit code: 0
```

Полный резолвленный YAML напечатан без секции `volumes:` (была
`db`/`media`/`static`/`caddy_data`/`logs` — все удалены) и без предупреждений
на stderr (stderr пуст в обоих прогонах).

Дополнительно (сверх acceptance_checks пакета, но по `tests` в JSON-пакете):
выполнены `docker build .` (образ `web`, полный success, финальный слой
`writing image ... naming to docker.io/library/lbs-web-test done`) и
`docker build -f services/agent_runtime/Dockerfile .` (образ `agent-runtime`,
полный success) — оба лога показывают установку именно из `requirements.lock`
(`Collecting ... (from -r requirements.lock (line N))` /
`(from -r /tmp/agent-runtime-requirements.lock (line N))`). Тестовые образы и
временная сеть `local-business-suite_internal` удалены после проверки
(`docker rmi`, `docker network rm`).

## Регрессионные проверки

```
.venv/bin/python manage.py check
# System check identified no issues (0 silenced).

.venv/bin/python manage.py validate_architecture_contracts
# Architecture contracts are valid.
```

Django-код и контракты не менялись этим пакетом — точечная проверка после
правки Dockerfile/Makefile/compose/documentation, регрессий нет.

## Методологическая заметка (DevSecOps)

**Зачем lock-файл при уже зафиксированных верхнеуровневых версиях.**
`requirements.txt` фиксирует только прямые зависимости (`Django==5.2.12`,
`langchain==0.3.28` и т.д.), но каждая из них тянет собственное дерево
транзитивных зависимостей с диапазонами версий (`langchain` не пишет
`langsmith==0.9.8`, а пишет что-то вроде `langsmith>=0.1,<1.0`). Без
lock-файла `pip install -r requirements.txt` резолвит эти диапазоны заново
при каждой сборке, в момент сборки — то есть два билда образа в разные дни
могут получить разные версии транзитивных пакетов, даже если
`requirements.txt` не менялся ни на символ. Это и есть проблема
воспроизводимости сборки: «работало на прошлой неделе» может перестать
работать сегодня из-за новой версии какой-то глубокой зависимости, без
единой явной причины в diff. `pip-compile` (pip-tools) один раз резолвит
полный граф и записывает точные пины всех транзитивных пакетов в
`requirements.lock`, с комментариями `# via <кто притянул>` для
трассируемости. `requirements.txt` остаётся источником намерения
(«какие верхнеуровневые пакеты и версии нам нужны»), `requirements.lock` —
источником факта («что именно ставится в образ»); первый — вход для
человека и для `pip-compile`, второй — вход для `pip install` в проде
и в CI/build. Обновление версий — осознанное действие (`make lock`), а
не побочный эффект обычной пересборки образа.

**Почему прод-compose не должен знать про конкретный хост.**
`docker-compose.prod.yml` — часть кодовой базы (версионируется в Git,
общий для всех окружений), а `deployments/<host>/.env` — секрет конкретного
сервера (см. AGENTS.md, «Изоляция сред развертывания»: `deployments/`
игнорируется в `.gitignore`, приватные хостовые файлы живут вне репозитория
кода). Если compose-файл жёстко пишет `deployments/test-host/.env`, он
перестаёт быть переиспользуемым шаблоном и превращается в конфиг одного
конкретного сервера: разворачивание второго хоста (например, `MedEx` —
такая директория уже существует в `deployments/`) потребовало бы либо
копипастить `docker-compose.prod.yml` под другое имя, либо путать хосты
между собой. Явная переменная окружения с обязательным значением
(`${VAR:?сообщение об ошибке}`) держит файл нейтральным к хосту и при этом
не даёт по ошибке «тихо» запустить контейнеры без окружения вовсе — сборка
или `compose up` без установленной переменной падает сразу с понятным
текстом, а не позже, на рантайм-ошибке от отсутствующих настроек.

## Файлы, изменённые пакетом 06

Изменены:
- `Dockerfile`
- `Makefile`
- `docker-compose.prod.yml`
- `services/agent_runtime/Dockerfile`
- `services/agent_runtime/.desc.json`
- `README.md`
- `docs/deployment/DEPLOYMENT.md`
- `PROJECT_STRUCTURE.yaml` (регенерация; включает не связанный с этой задачей,
  ранее не зафиксированный блок `learning/` — см. раздел 5 выше)

Новые:
- `services/agent_runtime/requirements.lock`

`requirements.lock` (корневой) — проверен на актуальность, не менялся
(повторная генерация дала побайтово идентичный файл).

**Не трогал, хотя логически связано:**
- `scripts/linux/deploy.sh` — вне write_scope; после этой задачи требует
  `export LOCAL_BUSINESS_ENV_FILE=...` перед вызовами `docker compose`
  (см. раздел 3 выше и `docs/deployment/DEPLOYMENT.md`).
- `.github/workflows/tests.yml` — CI всё ещё ставит зависимости из
  `requirements.txt` (не из lock); вне write_scope пакета, не менялось.
- В рабочей копии на момент начала задачи уже были незакоммиченные правки
  вне write_scope пакета 06: `apps/workorders/tests.py`,
  `apps/workorders/views.py`, `config/urls.py` — не мои, не трогал, не
  входят в диф этого пакета (аналогично наблюдению из
  `EXECUTOR_REPORT.02-agent-runtime-contract-delivery.md`).

Не коммитил (по инструкции пакета) — коммит делает оркестратор.
