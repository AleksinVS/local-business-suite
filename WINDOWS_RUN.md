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
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1 -Setup -Migrate -SeedRoles
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
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1 -WebOnly
```

Или поднять Django и AI runtime вместе:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1 -StartRuntime
```

## Что поднимается

- Django web: `http://127.0.0.1:8000`
- Agent runtime: `http://127.0.0.1:8090`

## Если нужен доступ с хоста или из другой машины

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1 -WebOnly -BindHost 0.0.0.0 -Port 8000
```

Для `VirtualBox` после этого нужно еще пробросить порт или использовать `Bridged Adapter`.

## Важные замечания

- Основной Django UI можно запускать без `OPENAI_API_KEY`.
- Без `agent_runtime` обычные Django-экраны работают, но AI-часть не будет полноценной.
- Если `OPENAI_API_KEY` не задан, runtime может стартовать, но AI-запросы будут завершаться ошибкой.
- Если PowerShell блокирует скрипт, используйте `-ExecutionPolicy Bypass`, как в примерах выше.

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
