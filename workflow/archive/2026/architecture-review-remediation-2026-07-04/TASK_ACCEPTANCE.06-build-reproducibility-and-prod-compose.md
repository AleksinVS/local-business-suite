# Приёмка: 06-build-reproducibility-and-prod-compose

Дата: 2026-07-07.
Роли: исполнитель — субагент (Sonnet); независимая проверка — не требуется
(`independent_verification: false`, риск medium); приёмка и companion-правки —
агент-оркестратор.

## Вердикт

**Принят с доработкой оркестратора** (companion-правка `deploy.sh` вне scope
субагента — см. ниже).

## Что проверено

Исполнение (из executor report + перепроверка оркестратором):

- **Воспроизводимая установка из lock:**
  - `Dockerfile:22-23` — `COPY requirements.txt requirements.lock` +
    `pip install -r requirements.lock`;
  - `services/agent_runtime/Dockerfile` — ставит из собственного
    `services/agent_runtime/requirements.lock`;
  - `Makefile`: `install` ставит из `requirements.lock`; добавлены цели
    `lock` и `lock-agent-runtime` (`python -m piptools compile`);
  - корневой `requirements.lock` перегенерирован для проверки — вышел
    байт-в-байт идентичным, изменений нет;
  - новый `services/agent_runtime/requirements.lock` (224 строки, валидный
    заголовок pip-compile).
- **Отдельный lock для agent-runtime — осознанное решение:** переиспользование
  корневого lock затащило бы в slim-образ Django/gevent/Pillow/psycopg и т.д.,
  что противоречит отдельному минимальному Dockerfile сервиса. Верхнеуровневые
  пины в обоих `requirements.txt` не тронуты (non-goal соблюдён); расхождение
  транзитивных версий между сервисами — ожидаемое и задокументировано.
- **Host-agnostic prod-compose:**
  - `env_file` у `web` и `agent-runtime` через
    `${LOCAL_BUSINESS_ENV_FILE:?...}` — без переменной понятная ошибка;
  - мёртвые именованные тома `db/media/static/caddy_data/logs` удалены
    (реально монтируются только bind-mount `./data` и `./caddy_data`).
- **Документация:** README (раздел «Воспроизводимая установка зависимостей»,
  quickstart переведён на lock), DEPLOYMENT.md (lock + `LOCAL_BUSINESS_ENV_FILE`),
  `services/agent_runtime/.desc.json` + PROJECT_STRUCTURE.yaml обновлены.

## Acceptance-проверки (прогнаны оркестратором)

- `grep -n requirements.lock Dockerfile Makefile` → установка идёт из lock
  (`Dockerfile:23`, `Makefile:15`) + цели `lock`/`lock-agent-runtime`.
- `grep -n test-host docker-compose.prod.yml` → вхождений нет.
- `docker compose -f docker-compose.prod.yml config`:
  - без `LOCAL_BUSINESS_ENV_FILE` → exit 1, `required variable
    LOCAL_BUSINESS_ENV_FILE is missing a value: ...`;
  - с `LOCAL_BUSINESS_ENV_FILE=deployments/test-host/.env` → exit 0, stderr пуст,
    секции `volumes:` нет (мёртвые тома убраны).
- Исполнитель дополнительно прогнал реальные `docker build .` и
  `docker build -f services/agent_runtime/Dockerfile .` — оба успешны, установка
  из соответствующих lock подтверждена логами.

## Companion-правка оркестратора (вне scope субагента)

Изменение `env_file` на `${LOCAL_BUSINESS_ENV_FILE:?...}` ломало
`scripts/linux/deploy.sh` (гонит `docker compose ... up` в удалённом heredoc без
экспорта переменной → падение с `:?`-ошибкой). `deploy.sh` не входил в write
scope пакета, субагент корректно оставил его и пометил как follow-up.

Оркестратор внёс необходимую companion-правку: в heredoc перед вызовами
`docker compose` добавлен
`export LOCAL_BUSINESS_ENV_FILE=deployments/test-host/.env`. Host-специфичная
привязка теперь живёт в host-специфичном деплой-скрипте, а `docker-compose.prod.yml`
остаётся общим — это и есть цель находки. Абзац «Важно» в DEPLOYMENT.md приведён
в соответствие (скрипт больше не «сломан», а сам задаёт привязку).

## Замечания и follow-up (в рекомендации, доработка не требуется)

1. Заголовок-комментарий `services/agent_runtime/requirements.lock` записан
   относительной командой (`pip-compile --output-file=requirements.lock
   requirements.txt`), а `make lock-agent-runtime` использует полный путь;
   косметика, перепишется при следующем `make lock-agent-runtime`.
2. `.github/workflows/tests.yml` всё ещё ставит из `requirements.txt` (вне scope).
   CI работает, но для единообразия воспроизводимости — кандидат в отдельную
   задачу.
3. `make lock`/`make lock-agent-runtime` требуют `pip-tools`, не входящего в
   рантайм-зависимости (это dev-инструмент) — отражено в комментариях Makefile,
   README и отчёте.

## Ограничения приёмки

`manage.py check` на момент приёмки не гоняется как «зелёный итог блока» из-за
параллельной работы пакета 03 в рабочем дереве (config/urls.py, workorders/*);
сводная проверка `make check` — после приёмки пакета 03. Изменения пакета 06 —
только сборка/compose/докстроки, Python-код не затронут.
