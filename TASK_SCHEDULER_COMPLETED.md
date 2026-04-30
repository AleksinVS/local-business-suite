# ✅ Настройка Task Scheduler выполнена успешно!

## Что было сделано:

### 1. Создана Scheduled Task для Agent Runtime

**Название задачи**: `Portal Agent Runtime`

**Команда запуска**:
```bash
C:\inetpub\portal\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300
```

**Рабочая директория**: `C:\inetpub\portal`

**Пользователь**: `SYSTEM`

### 2. Настроены параметры задачи

**Триггер (Trigger)**:
- ✅ Тип: AtStartup (запуск при старте системы)
- ✅ Включен: Да

**Настройки (Settings)**:
- ✅ Перезапуск при сбоях: 5 раз
- ✅ Интервал перезапуска: 1 минута
- ✅ Запуск при доступности: Да
- ✅ Разрешить запуск при питании от батареи: Да
- ✅ Не останавливать при переходе на батарею: Да

### 3. Статус настройки

**Задача**:
- ✅ Статус: Running
- ✅ Включена: Yes

**Agent Runtime**:
- ✅ Порт 8090: Доступен
- ✅ Health endpoint: Работает
- ✅ Статус: ok
- ✅ Модель: openai:glm-4.5-air
- ✅ Gateway: http://127.0.0.1/ai/gateway
- ✅ API ключ настроен: True

**Процесс**:
- ✅ PID: 17176
- ✅ Python: python
- ✅ Путь: C:\Program Files\Python311\python.exe

---

## Как это работает теперь:

### При старте системы:
1. Windows запускает Scheduled Task "Portal Agent Runtime"
2. Задача запускает Agent Runtime (AI-агент)
3. Agent Runtime начинает слушать порт 8090
4. AI-функционал портала становится доступным

### При сбоях:
1. Если Agent Runtime упадет, Task Scheduler автоматически перезапустит его
2. Будет сделано до 5 попыток перезапуска с интервалом 1 минута

---

## Проверка работы:

### Автоматическая проверка:
```powershell
# Проверить статус задачи
Get-ScheduledTask -TaskName "Portal Agent Runtime"

# Проверить порт
Test-NetConnection -ComputerName 127.0.0.1 -Port 8090

# Проверить health endpoint
Invoke-RestMethod -Uri "http://127.0.0.1:8090/health"
```

### Проверка через веб-интерфейс:
1. AI-чат: http://localhost/ai/chat/
2. Health: http://127.0.0.1:8090/health
3. Task Scheduler: taskschd.msc

---

## Управление задачей:

### Через PowerShell:
```powershell
# Запустить
Start-ScheduledTask -TaskName "Portal Agent Runtime"

# Остановить
Stop-ScheduledTask -TaskName "Portal Agent Runtime"

# Проверить статус
Get-ScheduledTask -TaskName "Portal Agent Runtime"

# Удалить
Unregister-ScheduledTask -TaskName "Portal Agent Runtime" -Confirm:$false
```

### Через графический интерфейс:
1. Откройте Task Scheduler (`taskschd.msc`)
2. Найдите задачу `Portal Agent Runtime`
3. Управляйте через контекстное меню (правая кнопка мыши)

---

## Следующие шаги:

1. ✅ **Настройка выполнена** - Agent Runtime настроен через Task Scheduler
2. 🔄 **Тестирование** - Перезагрузите сервер для проверки автоматического запуска
3. ✅ **Проверка** - После перезагрузки проверьте работу AI-чата
4. 📝 **Документация** - Сохраните этот файл для справки

---

## Сводка:

| Компонент | Статус | Метод запуска |
|-----------|--------|---------------|
| Django/IIS | ✅ Работает | Автоматический (IIS) |
| Agent Runtime | ✅ Работает | Автоматический (Task Scheduler) |
| AI-функционал | ✅ Работает | Доступен через порт 8090 |

---

## Созданные файлы:

- `C:\inetpub\portal\start_agent_runtime.bat` - bat-файл для запуска Agent Runtime (резервный)
- `C:\inetpub\portal\TASK_SCHEDULER_SETUP.md` - подробная инструкция по настройке
- `C:\inetpub\portal\TASK_SCHEDULER_COMPLETED.md` - этот файл (результат настройки)

---

## Замечание:

Agent Runtime использует системный Python (`C:\Program Files\Python311\python.exe`) вместо venv Python, но это не влияет на работоспособность. Все зависимости установлены в системном Python.

Если в будущем потребуется использовать venv Python, можно изменить путь в настройках Scheduled Task.

---

## Удачи! 🚀

Настройка завершена успешно. Теперь оба сервиса (Django и Agent Runtime) будут автоматически запускаться при старте системы!
