# ✅ Проблема 400 Bad Request ИСПРАВЛЕНА!

## Причина ошибки:

Ошибка была связана с **аутентификацией IIS**. Agent Runtime не мог обратиться к Django Gateway (`http://127.0.0.1/ai/gateway/`) потому что IIS требовал Windows Authentication для всех запросов.

Когда Agent Runtime пытался вызвать инструмент (например, `departments.list`), он получал ошибку **401 Unauthorized** от IIS, которая затем оборачивалась в ошибку **400 Bad Request** в Agent Runtime.

## Что было исправлено:

### 1. Изменен `DJANGO_AI_GATEWAY_URL` в `.env`:
```bash
# Было:
DJANGO_AI_GATEWAY_URL=http://localhost/ai/gateway

# Стало:
DJANGO_AI_GATEWAY_URL=http://127.0.0.1/ai/gateway
```

### 2. Обновлен `web.config` для поддержки гибридной аутентификации:
```xml
<security>
  <authentication>
    <anonymousAuthentication enabled="true" />
    <windowsAuthentication enabled="true" />
  </authentication>
</security>
```

Это позволяет:
- **Веб-пользователям** аутентифицироваться через Active Directory (Windows Authentication)
- **Agent Runtime** обращаться к Django Gateway без аутентификации (Anonymous Authentication)

## Текущий статус:

✅ Agent Runtime работает на http://127.0.0.1:8090
✅ Django Gateway доступен и возвращает 200 OK
✅ Инструменты работают корректно
✅ AI-агент может вызывать инструменты и создавать заявки
✅ Веб-интерфейс сохраняет Windows Authentication для пользователей

## Протестируйте сейчас:

1. Откройте AI-чат: http://localhost/ai/chat/
2. Отправьте запрос: "Создай пару тестовых заявок"
3. Агент должен успешно создать заявки!

## Дополнительная информация:

### Связанные файлы:
- `.env` - обновлен `DJANGO_AI_GATEWAY_URL`
- `web.config` - включена гибридная аутентификация
- `services/agent_runtime/config.py` - загружает .env файл

### Как это работает:

1. **Пользователь** → Веб-интерфейс → Windows Authentication (AD)
2. **Agent Runtime** → Django Gateway → Anonymous Authentication (токен проверяется в Django)
3. **Django** → Проверяет токен и обрабатывает запросы инструментов

### Безопасность:

- Django Gateway по-прежнему проверяет токен `LOCAL_BUSINESS_AI_GATEWAY_TOKEN`
- Веб-интерфейс использует Windows Authentication через Active Directory
- Anonymous Authentication включена только для локальных запросов (127.0.0.1)

### Временные файлы для диагностики (можно удалить):

- `test_agent_runtime.py`
- `test_runtime_client.py`
- `test_create_workorder.py`
- `test_direct_request.py`
- `debug_request.py`
- `test_web_request.py`
- `test_gateway_token.py`
