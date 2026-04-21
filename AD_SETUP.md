# Настройка интеграции с Active Directory

## Автоматически настроенные параметры

Следующие параметры уже настроены и работают:
- `AD_LDAP_HOST` = `stc-dc01.mscher.local` (основной контроллер домена)
- `AD_LDAP_PORT` = `636` (порт LDAPS)
- `AD_LDAP_TRANSPORT` = `ldaps` (безопасное соединение)
- `AD_SEARCH_DN` = `DC=MSCHER,DC=LOCAL` (базовый DN домена)
- `AD_LDAP_DOMAIN` = `MSCHER` (имя домена)
- `AD_LDAP_USER_FILTER` = `(sAMAccountName={username})` (фильтр поиска)

## Параметры, которые нужно настроить вручную

### 1. Создайте сервисную учетную запись в AD

Обратитесь к системному администратору для создания учетной записи с правами чтения AD:

**Требования к сервисной учетной записи:**
- Права на чтение пользователей и групп в AD
- Сложный пароль (рекомендуется 20+ символов)
- Действие: "Не ограничено" (Never expires)

**Пример создания в PowerShell (для админа):**
```powershell
New-ADUser -Name "svc_portal_read" `
           -SamAccountName "svc_portal_read" `
           -UserPrincipalName "svc_portal_read@mscher.local" `
           -Path "OU=Service Accounts,DC=mscher,DC=local" `
           -Enabled $true `
           -ChangePasswordAtLogon $false `
           -PasswordNeverExpires $true

# Установите пароль:
Set-ADAccountPassword -Identity "svc_portal_read" -Reset -NewPassword (ConvertTo-SecureString "СложныйПароль123!" -AsPlainText -Force)

# Добавьте права на чтение (Delegation):
# Группы: Domain Users (чтение), Domain Admins (полный доступ)
```

### 2. Установите сервисную учетную запись в web.config

Откройте файл `C:\inetpub\portal\web.config` и замените:

```xml
<add key="AD_SERVICE_ACCOUNT" value="YOUR_SERVICE_ACCOUNT" />
<add key="AD_SERVICE_PASSWORD" value="YOUR_SERVICE_PASSWORD" />
```

На реальные значения:

```xml
<add key="AD_SERVICE_ACCOUNT" value="svc_portal_read@mscher.local" />
<add key="AD_SERVICE_PASSWORD" value="ВашСложныйПароль123!" />
```

### 3. Настройте маппинг групп AD в роли Django (опционально)

Если вы хотите автоматически назначать роли пользователям на их членства в AD группах:

**Пример AD групп:**
- `IT Support` → роль `admin` в Django
- `HR Department` → роль `hr` в Django
- `Warehouse` → роль `warehouse` в Django

**В web.config замените:**
```xml
<add key="AD_GROUP_ROLE_MAP" value="{}" />
```

**На:**
```xml
<add key="AD_GROUP_ROLE_MAP" value='{"IT Support": "admin", "HR Department": "hr", "Warehouse": "warehouse"}' />
```

## Альтернативный способ настройки через IIS Manager

Если предпочитаете настройку через графический интерфейс:

1. Откройте IIS Manager
2. Выберите сайт `Default Web Site`
3. Дважды кликните на `FastCGI Settings`
4. Выберите приложение Python
5. Нажмите `Environment Variables`
6. Добавьте/редактируйте переменные:
   - `AD_SERVICE_ACCOUNT` = `svc_portal_read@mscher.local`
   - `AD_SERVICE_PASSWORD` = `ВашСложныйПароль123!`
   - `AD_GROUP_ROLE_MAP` = `{"IT Support": "admin"}`

## Тестирование настройки

После настройки:

1. Перезапустите IIS:
```powershell
iisreset
```

2. Проверьте логи при попытке входа нового пользователя:
```powershell
Get-Content C:\inetpub\portal\wfastcgi_error.log -Tail 50
```

3. Проверьте, что пользователь создался в базе:
```powershell
cd C:\inetpub\portal
.\.venv\Scripts\python.exe manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.all())"
```

## Доступные контроллеры домена

По состоянию на сегодня доступны следующие контроллеры домена:
- `stc-dc01.mscher.local` [PDC] - основной (используется по умолчанию)
- `pol2-dc02.mscher.local`
- `pol1-dc2.mscher.local`
- `rdom-dc2.mscher.local`

Если основной контроллер недоступен, можно указать другой в `web.config`.

## Безопасность

**Рекомендации:**
- Используйте LDAPS (порт 636) вместо обычного LDAP
- Установите сильный пароль для сервисной учетной записи
- Ограничьте права сервисной учетной записи только чтением
- Не включайте логирование паролей
- Регулярно меняйте пароль сервисной учетной записи

**Для работы без SSL (не рекомендуется):**
```xml
<add key="AD_LDAP_TRANSPORT" value="plain" />
<add key="AD_LDAP_PORT" value="389" />
<add key="AD_LDAP_ALLOW_INSECURE" value="true" />
```

## Справочная информация

**Структура домена:**
- Домен: `MSCHER.LOCAL`
- NetBIOS имя: `MSCHER`
- Контроллеры: 4 шт.

**Поиск пользователей:**
- Фильтр: `(sAMAccountName={username})`
- База: `DC=MSCHER,DC=LOCAL`

**Доступные атрибуты пользователя:**
- `mail` - email
- `displayName` - полное имя
- `givenName` - имя
- `sn` - фамилия
- `memberOf` - группы
- `sAMAccountName` - логин
- `userPrincipalName` - UPN

## Контакты

Для получения дополнительных параметров обратитесь к:
- Системному администратору домена AD
- За созданием сервисной учетной записи
- За списком AD групп для маппинга ролей