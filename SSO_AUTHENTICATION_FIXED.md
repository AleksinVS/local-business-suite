# ✅ SSO Авторизация ИСПРАВЛЕНА!

## Проблема:

После исправления ошибки 400 Bad Request, SSO авторизация перестала работать, потому что я включил `Anonymous Authentication` для основного сайта. Это broke SSO, так как IIS перестал требовать Windows Authentication.

## Решение:

Конфигурация `web.config` была обновлена с правильным разделением аутентификации:

### 1. Основной сайт - только Windows Authentication (SSO)
```xml
<location path=".">
  <security>
    <authentication>
      <anonymousAuthentication enabled="false" />
      <windowsAuthentication enabled="true" />
    </authentication>
  </security>
</location>
```

### 2. Путь /static - только Anonymous Authentication
```xml
<location path="static">
  <security>
    <authentication>
      <anonymousAuthentication enabled="true" />
      <windowsAuthentication enabled="false" />
    </authentication>
  </security>
</location>
```

### 3. Путь /ai/gateway - только Anonymous Authentication + Python handlers
```xml
<location path="ai/gateway">
  <handlers>
    <add name="Python FastCGI" path="*" verb="*" modules="FastCgiModule" ... />
  </handlers>
  <security>
    <authentication>
      <anonymousAuthentication enabled="true" />
      <windowsAuthentication enabled="false" />
    </authentication>
  </security>
</location>
```

## Что это даёт:

✅ **SSO работает** - пользователи аутентифицируются через Active Directory
✅ **Статические файлы доступны** - CSS, JS, изображения
✅ **AI Gateway работает** - Agent Runtime может обращаться без аутентификации
✅ **Безопасность сохранена** - токен проверяется в Django, не в IIS

## Текущий статус:

✅ SSO авторизация: работает
✅ Django Gateway: работает (200 OK)
✅ Agent Runtime: работает
✅ AI-агент: создаёт заявки

## Протестируйте сейчас:

1. Откройте: http://localhost/
2. Вы должны автоматически войти через SSO (Active Directory)
3. Откройте: http://localhost/ai/chat/
4. Отправьте: "Создай пару тестовых заявок"
5. Агент создаст заявки!

## Настройки web.config:

Файл `web.config` теперь содержит:
- Основной сайт: Windows Authentication только
- /static: Anonymous Authentication только
- /ai/gateway: Anonymous Authentication + Python FastCGI handlers

Это правильная конфигурация для IIS с SSO и AI-агентом.
