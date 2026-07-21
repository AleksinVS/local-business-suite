# Windows Run

Локальный запуск проекта на Windows без Docker.

## Что требуется

- Windows 10/11
- Python 3.12+ с `py`
- PowerShell
- интернет для `pip install`
- `OPENAI_API_KEY`, если нужен рабочий AI runtime

## Быстрый старт

Из корня проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\run_windows.ps1 -Setup -Migrate -SeedRoles
```

Эта команда:

- создаст `.venv`, если его нет;
- установит Python-зависимости проекта;
- установит зависимости `agent_runtime`;
- создаст `.env` из `.env.example`, если файла еще нет;
- применит миграции;
- выполнит `seed_roles`.

После подготовки можно запустить только Django:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\run_windows.ps1 -WebOnly
```

Или поднять Django и AI runtime вместе:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\run_windows.ps1 -StartRuntime
```

## Что поднимается

- Django web: `http://127.0.0.1:8000`
- Agent runtime: `http://127.0.0.1:8090`

## Если нужен доступ с хоста или из другой машины

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\run_windows.ps1 -WebOnly -BindHost 0.0.0.0 -Port 8000
```

Для `VirtualBox` после этого нужно еще пробросить порт или использовать `Bridged Adapter`.

## Важные замечания

- Основной Django UI можно запускать без `OPENAI_API_KEY`.
- Без `agent_runtime` обычные Django-экраны работают, но AI-часть не будет полноценной.
- Если `OPENAI_API_KEY` не задан, runtime может стартовать, но AI-запросы будут завершаться ошибкой.
- Если PowerShell блокирует скрипт, используйте `-ExecutionPolicy Bypass`, как в примерах выше.
- На Windows Server с IIS не запускайте одновременно ручной runtime через `-StartRuntime` и автозапуск через Task Scheduler. Для постоянного режима оставьте только задачу планировщика.

## Автозапуск Agent Runtime на Windows Server

Для постоянного запуска Agent Runtime используйте одну задачу Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup_agent_runtime_autostart.ps1 -Force
```

Скрипт регистрирует задачу `Portal Agent Runtime` в `\Portal\` и запускает runtime через `.venv\Scripts\python.exe`. Перед регистрацией он ищет и предлагает удалить старые задачи, которые запускали тот же runtime через другой Python или старый `start_agent_runtime.bat`.

Диагностика дублей без изменения системы:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\check_agent_runtime_autostart.ps1
```

Диагностика должна показывать `OK: 1 root process (uvicorn master) + N worker subprocess(es) (uvicorn multiprocessing)`. Если видит `WARNING`, см. раздел «Анатомия процессов Agent Runtime» ниже.

## Анатомия процессов Agent Runtime

После регистрации задачи и её запуска в системе живут **ровно две** структуры, связанные с Agent Runtime:

| Что | Ожидаемый путь | Почему |
|---|---|---|
| Scheduled task `\Portal\Portal Agent Runtime` | `C:\inetpub\portal\.venv\Scripts\python.exe` | Прямой запуск через venv-лаунчер, как задано в `setup_agent_runtime_autostart.ps1:32-34, 138-159` |
| Master процесс (uvicorn) | `C:\inetpub\portal\.venv\Scripts\python.exe` | Стартует от scheduled task, parent = svchost/services.exe |
| Worker subprocess (uvicorn) | `C:\Program Files\Python311\python.exe` | См. ниже |

### Почему worker subprocess использует `C:\Program Files\Python311\python.exe`, а не `.venv\Scripts\python.exe`

Это **не дубль интерпретатора**, а особенность venv-лаунчера на Windows. В этом проекте venv создан поверх системного Python 3.11:

```ini
# .venv\pyvenv.cfg
home = C:\Program Files\Python311
executable = C:\Program Files\Python311\python.exe
version = 3.11.9
```

`C:\inetpub\portal\.venv\Scripts\python.exe` — это **proxy executable**: при старте он через `os.execv` перезапускает сам себя на путь из `pyvenv.cfg:executable`, то есть на `C:\Program Files\Python311\python.exe`. После такого re-exec `sys.executable` внутри процесса указывает на `C:\Program Files\Python311\python.exe`.

uvicorn 0.35.0 при старте через `python -m uvicorn ...` всегда работает в режиме multiprocessing: мастер-процесс и один worker subprocess. См. исходники uvicorn:

- `uvicorn/main.py:567-580` — `Multiprocess(config, target=server.run, sockets=[sock]).run()` при `config.workers > 1` либо `config.should_reload`.
- `uvicorn/supervisors/multiprocess.py:122-126` — `init_processes` создаёт воркеров и кладёт им уже открытый listening socket.
- `uvicorn/_subprocess.py:18, 51` — `multiprocessing.get_context("spawn")` запускает child через `sys.executable` родителя.

В итоге `sys.executable` в worker subprocess после re-exec venv-лаунчера = `C:\Program Files\Python311\python.exe`, поэтому в `Get-CimInstance Win32_Process` worker показывается с этим путём.

**Это нормальное состояние.** В диспетчере задач и `Get-Process` всегда будет видно **два** python-процесса с разными `Path`, но это **один** ASGI-сервис.

### Что считать реальным дублём

Чек-скрипт `check_agent_runtime_autostart.ps1` помечает состояние как проблемное, если:

- в `Task Scheduler` больше одной задачи Agent Runtime (например, устаревшая в корне планировщика + новая в `\Portal\`);
- запущено больше одного **root** процесса (parent которого не входит в список процессов Agent Runtime) — это значит, runtime стартовал независимо из двух источников;
- root-процесс использует Python не из ожидаемого множества (`.venv\Scripts\python.exe` или путь из `pyvenv.cfg:executable`);
- запущены worker subprocess'ы, но root-процесс отсутствует (master упал, worker висит).

Если в Task Scheduler действительно **две** задачи (например, старая в корне из `archive/TASK_SCHEDULER_COMPLETED.md` и новая в `\Portal\`), то это **настоящий** дубль. Удалить лишнюю можно через `setup_agent_runtime_autostart.ps1 -Force` — он перед регистрацией найдёт и предложить удалить чужие задачи по совпадению в `Actions` (см. `setup_agent_runtime_autostart.ps1:44-114`).

## Типичные проблемы и защитные лимиты Agent Runtime

Эти сценарии отлажены на проде. Для каждого указан симптом, причина и команды диагностики.

### «ИИ-сервис недоступен» в чате

Симптом: каждое сообщение возвращает `Не удалось получить ответ от ИИ-сервиса. Причина: ИИ-сервис недоступен. Технический идентификатор: <uuid>`. Ошибка формируется в `apps/ai/views.py:54-68` при `httpx.ConnectError` на `127.0.0.1:8090` — runtime не отвечает.

Диагностика:

```powershell
curl http://127.0.0.1:8090/health
# {"status": "ok"} — runtime жив; иначе — поднимаем
```

Подъём без перезагрузки сервера:

```powershell
Start-ScheduledTask -TaskName "Portal Agent Runtime" -TaskPath "\Portal\"
```

### `DisallowedHost` 400 на gateway-запросах runtime

Симптом: runtime поднят, `/health` отвечает 200, чат отвечает общими фразами без вызова инструментов. В логах runtime видно `GET http://127.0.0.1/ai/gateway/skills/catalog/ "HTTP/1.1 400 Bad Request"`. Django отклоняет `Host: 127.0.0.1`, потому что `ALLOWED_HOSTS` в проде — `['stc-web', 'web']` (или другие имена, заданные `DJANGO_ALLOWED_HOSTS`). `gateway_client.get_skills_catalog()` ловит `httpx.HTTPError` и возвращает пустой список (`services/agent_runtime/gateway_client.py:57-58`), LLM продолжает отвечать, но tool-вызовы не работают.

Фикс: `DJANGO_AI_GATEWAY_URL` в `.env` должен указывать на хост из `ALLOWED_HOSTS`:

```env
# в проде на машине с hostname = stc-web
DJANGO_AI_GATEWAY_URL=http://stc-web/ai/gateway
```

После правки `.env` обязателен перезапуск runtime (`Stop-ScheduledTask` + `Start-ScheduledTask`), потому что `services/agent_runtime/config.py:64-66` читает env через `load_dotenv` один раз при импорте.

### Runtime завис → каскадный отказ Django

Симптом: сообщения «уходят без ответа», `POST /ai/chat/<uuid>/delete/` падает с «Ошибка соединения» (см. `static/src/js/ai_chat.js:683, 707`). `curl /health` на runtime возвращает таймаут, но TCP-порт `8090` остаётся в `LISTEN` (`netstat -ano | grep ":8090"`). У wfastcgi-воркеров, державших стримы, появляются соединения в `FinWait2` к runtime.

Причина: длительный LLM-вызов (z.ai или другой провайдер завис) блокирует worker uvicorn. Worker зависает в `CloseWait` и не отвечает новым запросам. Все wfastcgi-воркеры, державшие чат-стримы, тоже блокируются — пул wfastcgi заканчивается, и даже запросы, которые runtime не трогают (например, удаление чата), не получают свободный воркер и отваливаются по таймауту. На стороне браузера JS ловит `fetch` rejection и показывает общее `alert('Ошибка соединения.')`.

Защитные лимиты в деплое:

- **LLM-таймаут 120s** в `services/agent_runtime/graph.py:85-92, 209-216` (`init_kwargs = {"temperature": 0, "timeout": 120}`). При зависании провайдера LLM-вызов упадёт через 120 секунд, `try/except` в `services/agent_runtime/app.py:99-105, 138-152` вернёт клиенту осмысленную ошибку (`error: agent_runtime_error` в SSE-потоке или HTTP 400 для sync), runtime не зависнет, wfastcgi-воркеры освободятся.
- **wfastcgi-лимиты** в `web.config` `<appSettings>`:

  ```xml
  <add key="instanceMaxRequests" value="2000" />
  <add key="idleTimeoutInSeconds" value="300" />
  ```

  Каждый воркер перерабатывается после 2000 запросов (защита от state-засорения и медленных утечек), простаивающие закрываются через 5 минут. Эти значения не предотвращают зависание, но не дают воркерам копить мусор.

Аварийное восстановление, если runtime уже завис:

```powershell
Stop-ScheduledTask -TaskName "Portal Agent Runtime" -TaskPath "\Portal\"
Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*uvicorn*' } |
    ForEach-Object { $_.Terminate() }
Start-ScheduledTask -TaskName "Portal Agent Runtime" -TaskPath "\Portal\"
# ждём ~5 секунд
curl http://127.0.0.1:8090/health
```

Висящие wfastcgi-воркеры IIS перезапустит по мере освобождения; чтобы ускорить:

```powershell
Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*wfastcgi*' } |
    ForEach-Object { $_.Terminate() }
```

Первое обращение к `/ai/...` через Windows-auth (например, `curl --ntlm -u : http://stc-web/ai/chat/`) заставит IIS поднять свежие воркеры, которые прочтут обновлённый `web.config`.

### Удаление чата падает с 500 из-за cross-database FK

Симптом: `POST /ai/chat/<uuid>/delete/` возвращает HTTP 500, в логах Django `OperationalError: no such table: memory_memorywriterequest` (или аналогичная таблица другого cross-DB FK). В debug-странице прямо в SQLCompiler указан `using='chat'` — то есть ORM шлёт SELECT в БД чата, хотя таблица живёт в `knowledge_meta`.

Причина: в multi-DB проекте `apps/ai/ChatSession` хранится в `chat` DB (роутер `apps/core/db_routers.py:50`), а модели `apps/memory/*` — в `knowledge_meta` DB. Когда `MemoryWriteRequest.session` (FK на `ChatSession`) объявлен с `on_delete=PROTECT | CASCADE | SET_NULL | SET_DEFAULT`, Django при `ChatSession.delete()` идёт в `Collector.collect()` (`django/db/models/deletion.py:305-310`) и делает SELECT по обратным FK, чтобы решить, что делать с наследниками. Этот SELECT идёт через `self.using` — алиас БД **родителя** (`chat`). В `chat` DB таблицы `memory_*` нет → `OperationalError`. Роутер при cascade-collect не вызывается — это известная особенность Django.

**Единственное значение `on_delete`, которое пропускает SELECT, — `DO_NOTHING`** (`deletion.py:307-310`: `if on_delete == DO_NOTHING: continue`). Ни `SET_NULL`, ни `CASCADE`, ни `PROTECT` не помогут — все они идут через `self.related_objects()` и шлют SELECT в БД родителя.

В этом деплое FK настроены так:

| Модель | Поле | `on_delete` | Поведение после удаления чата |
|---|---|---|---|
| `MemoryWriteRequest` | `session` | `DO_NOTHING` | Строка остаётся с `session_id=<старый uuid>` — dangling reference, но UUID пригоден для аудита |
| `MemoryKnowledgeItem` | `source_session` | `DO_NOTHING` | То же — знания переживают удаление чата by design |

Если нужна семантика `SET_NULL` (обнуление `session_id` после удаления чата), её можно реализовать явно через `pre_delete` сигнал в `apps/memory/signals.py`, который шлёт `UPDATE` напрямую в нужную БД в обход cascade-collect.

При добавлении **новых** cross-DB FK (`db_constraint=False`, разные DB у родителя и наследника) всегда ставьте `on_delete=models.DO_NOTHING`. Иначе при `delete()` родителя получите 500.

### Проверка источника AI-контрактов (tools.json/task_types.json/models.json)

На Windows-запуске (в отличие от Docker) `agent_runtime` и Django работают на одной
файловой системе, поэтому дополнительный том не нужен — `data/contracts/ai/` виден
runtime-процессу напрямую (ADR-0031, доставка контрактов, шаг 1 — том нужен только
в Docker-конфигурации, см. `docs/deployment/DEPLOYMENT.md`). При старте runtime пишет
в свой лог фактический источник каждого контракта (`runtime`/`default`/`override`) и
предупреждение `WARNING`, если контракт откатился на packaged default из `contracts/`
(это означало бы, что `data/contracts/ai/*.json` отсутствует). Быстрая проверка без
чтения логов:

```powershell
curl http://127.0.0.1:8090/health/details
```

Поле `contracts` показывает путь и источник для каждого контракта; `contracts_degraded:
true` означает, что хотя бы один контракт читается не из `data/contracts/ai/`. Правки
контрактов через Settings Center подхватываются работающим runtime без перезапуска
(инвалидация кэша по метаданным файла, `services/agent_runtime/contract_cache.py`) —
в отличие от правки `.env`, которая по-прежнему требует перезапуска runtime (см. раздел
про `DJANGO_AI_GATEWAY_URL` выше).

## Полезные команды

Проверка проекта:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py validate_architecture_contracts
```

Запуск runtime вручную:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --reload
```

Запуск Django вручную:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```
