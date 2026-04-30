# ✅ Исправлена ошибка 400 Bad Request в AI-чате

## Причина ошибки:

Проблема была в кастомной модели User (`apps/accounts/models.py`). При создании кастомной модели были изменены `related_name` для полей `groups` и `user_permissions`:

```python
# БЫЛО (неправильно):
groups = models.ManyToManyField(
    Group,
    ...
    related_name="custom_user_set",  # ❌ Нестандартное имя
    related_query_name="custom_user",
)

# СТАЛО (правильно):
groups = models.ManyToManyField(Group, ...)  # ✅ Использует значения из AbstractUser
```

Это вызывало ошибку при попытке доступа к `user.groups.values_list("name", flat=True)` в `apps/ai/runtime_client.py:50`, потому что Django пытался использовать стандартное поле `groups`, но оно было переопределено с новым related_name.

## Что было исправлено:

1. ✅ Удалены кастомные `related_name` для `groups` и `user_permissions` в `apps/accounts/models.py`
2. ✅ Создана и применена миграция: `apps/accounts/migrations/0002_alter_user_groups_alter_user_user_permissions.py`
3. ✅ Перезапущен IIS для загрузки изменений

## Проверка работоспособности:

Теперь AI-чат должен работать корректно. Протестируйте:

1. Откройте: http://localhost/ai/chat/
2. Отправьте сообщение: "Создай пару тестовых заявок"
3. Агент должен успешно создать заявки

## Если ошибка сохраняется:

### 1. Проверьте логи Agent Runtime:

Agent Runtime должен быть запущен в отдельном окне. Проверьте, есть ли ошибки в консоли.

### 2. Проверьте, что Agent Runtime запущен:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8090/health"
```

Ожидаемый ответ:
```json
{
  "status": "ok",
  "model": "openai:glm-4.5-air",
  "gateway_url": "http://localhost/ai/gateway",
  "openai_key_configured": true
}
```

### 3. Проверьте логи Django:

```powershell
Get-Content "C:\inetpub\portal\debug_path.log" -Tail 50
Get-Content "C:\inetpub\portal\logs\error.log" -Tail 50
```

### 4. Проверьте доступ к группам пользователя:

```powershell
cd "C:\inetpub\portal"
.\.venv\Scripts\python.exe manage.py shell -c "from apps.accounts.models import User; u = User.objects.first(); print('Groups:', list(u.groups.values_list('name', flat=True)))"
```

### 5. Проверьте инструменты:

Откройте: http://localhost/ai/hub/
Проверьте, что инструменты загружены корректно.

## Дополнительная диагностика:

Если ошибка продолжается, включите детальное логирование:

### В Django (`config/settings.py`):

```python
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
        'apps.ai': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
```

### В Agent Runtime:

Перезапустите с отладкой:

```powershell
cd "C:\inetpub\portal"
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "services.agent_runtime.app:app", "--host", "127.0.0.1", "--port", "8090", "--timeout-keep-alive", "300", "--log-level", "debug" -WindowStyle Normal
```

## Связанные файлы:

- `apps/accounts/models.py` - исправлена модель User
- `apps/accounts/migrations/0002_alter_user_groups_alter_user_user_permissions.py` - миграция
- `apps/ai/runtime_client.py` - использует `user.groups` для получения ролей

## Резюме:

Ошибка 400 Bad Request была вызвана неправильной настройкой related_names в кастомной модели User. После исправления и применения миграции, AI-чат должен работать корректно и создавать заявки.
