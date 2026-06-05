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

Если в Task Scheduler действительно **две** задачи (например, старая в корне из `archive/TASK_SCHEDULER_COMPLETED.md` и новая в `\Portal\`), то это **настоящий** дубль. Удалить лишнюю можно через `setup_agent_runtime_autostart.ps1 -Force` — он перед регистрацией найдёт и предложит удалить чужие задачи по совпадению в `Actions` (см. `setup_agent_runtime_autostart.ps1:44-114`).

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
