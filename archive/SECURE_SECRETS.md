# Безопасное хранение секретов для IIS + Django

## Проблема

Текущий `web.config` содержит plaintext пароли:
```xml
<add key="AD_SERVICE_PASSWORD" value="YOUR_SERVICE_PASSWORD" />
```

Это небезопасно, так как:
- Пароли видны в файловой системе
- Любой с доступом к серверу может прочитать пароли
- Пароли могут попасть в бэкапы
- Нет ротации секретов

## Решения

### Вариант 1: Environment Variables (Рекомендуемый для текущей настройки)

**Преимущества:**
- ✅ Простая реализация
- ✅ Нет паролей в файлах
- ✅ Легкая ротация
- ✅ Стандартный подход

**Реализация:**

```powershell
# Настройка environment variables на уровне системы
[Environment]::SetEnvironmentVariable("AD_SERVICE_ACCOUNT", "svc_portal_read@mscher.local", "Machine")
[Environment]::SetEnvironmentVariable("AD_SERVICE_PASSWORD", "your-secure-password-here", "Machine")

# Или для Application Pool пользователя
[Environment]::SetEnvironmentVariable("AD_SERVICE_ACCOUNT", "svc_portal_read@mscher.local", "User")
[Environment]::SetEnvironmentVariable("AD_SERVICE_PASSWORD", "your-secure-password-here", "User")
```

**Обновить web.config (удалить секреты):**
```xml
<add key="AD_SERVICE_ACCOUNT" value="" />
<add key="AD_SERVICE_PASSWORD" value="" />
<!-- Пароли будут браться из environment variables -->
```

**Проверка:**
```powershell
# Проверить установленные переменные
[Environment]::GetEnvironmentVariable("AD_SERVICE_ACCOUNT", "Machine")
[Environment]::GetEnvironmentVariable("AD_SERVICE_PASSWORD", "Machine")
```

---

### Вариант 2: Windows Registry (Более безопасный)

**Преимущества:**
- ✅ Дополнительный уровень защиты
- ✅ Контроль доступа через ACL
- ✅ Логирование доступа

**Реализация:**

```powershell
# Создать ключ для приложения
New-Item -Path "HKLM:\SOFTWARE\PortalVOB3" -Force

# Хранить секреты в реестре
New-ItemProperty -Path "HKLM:\SOFTWARE\PortalVOB3" `
    -Name "AD_SERVICE_ACCOUNT" `
    -Value "svc_portal_read@mscher.local" `
    -Force

New-ItemProperty -Path "HKLM:\SOFTWARE\PortalVOB3" `
    -Name "AD_SERVICE_PASSWORD" `
    -Value "your-secure-password-here" `
    -Force

# Ограничить доступ к ключу
$acl = Get-Acl "HKLM:\SOFTWARE\PortalVOB3"
$rule = New-Object System.Security.AccessControl.RegistryAccessRule(`
    "IIS APPPOOL\DefaultAppPool", "ReadKey", "Allow"
)
$acl.SetAccessRule($rule)
Set-Acl "HKLM:\SOFTWARE\PortalVOB3" $acl
```

**Обновить Django settings для чтения из реестра:**

```python
# В config/settings.py или отдельный файл secrets.py
import winreg

def get_registry_secret(key_name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\PortalVOB3") as key:
            value, _ = winreg.QueryValueEx(key, key_name)
            return value
    except WindowsError:
        return os.environ.get(key_name, "")

AD_SERVICE_ACCOUNT = get_registry_secret("AD_SERVICE_ACCOUNT")
AD_SERVICE_PASSWORD = get_registry_secret("AD_SERVICE_PASSWORD")
```

---

### Вариант 3: Windows Credential Manager (Наиболее безопасный)

**Преимущества:**
- ✅ Шифрование DPAPI
- ✅ Интеграция с Windows
- ✅ Не требует паролей в открытом виде

**Реализация:**

```powershell
# Добавить credentials в Windows Credential Manager
cmdkey /generic:PortalVOB3_AD /user:svc_portal_read@mscher.local /pass:your-secure-password-here

# Для чтения в Python:
import win32cred

def get_credential(target_name):
    try:
        cred = win32cred.CredRead(target_name, win32cred.CRED_TYPE_GENERIC, 0)
        return cred['UserName'], cred['CredentialBlob'].decode('utf-16')
    except:
        return None, None

AD_SERVICE_ACCOUNT, AD_SERVICE_PASSWORD = get_credential("PortalVOB3_AD")
```

---

### Вариант 4: Отдельный .env файл (Простой, но менее безопасный)

**Преимущества:**
- ✅ Простой для разработчиков
- ✅ Изолирован от кода
- ✅ Не коммитится в git

**Недостатки:**
- ❌ Файл может быть скопирован
- ❌ Требует настройки прав доступа

**Реализация:**

```powershell
# Создать .env файл в корне проекта
@"
AD_SERVICE_ACCOUNT=svc_portal_read@mscher.local
AD_SERVICE_PASSWORD=your-secure-password-here
"@ | Out-File -FilePath "C:\inetpub\portal\.env" -Encoding UTF8

# Установить права доступа (только IIS AppPool и администраторы)
$acl = Get-Acl "C:\inetpub\portal\.env"
$accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(`
    "IIS APPPOOL\DefaultAppPool", "Read", "Allow"
)
$acl.SetAccessRule($accessRule)
Set-Acl "C:\inetpub\portal\.env" $acl
```

**Обновить web.config для загрузки .env:**
```xml
<appSettings>
  <add key="DJANGO_SETTINGS_MODULE" value="config.settings" />
  <add key="PYTHONPATH" value="C:\inetpub\portal" />
  <!-- Другие настройки без секретов -->
</appSettings>
```

**Обновить Django settings для чтения .env:**

```python
# В config/settings.py
from pathlib import Path
from dotenv import load_dotenv

# Загрузить .env файл
env_file = BASE_DIR / ".env"
load_dotenv(env_file)

AD_SERVICE_ACCOUNT = os.getenv("AD_SERVICE_ACCOUNT")
AD_SERVICE_PASSWORD = os.getenv("AD_SERVICE_PASSWORD")
```

---

## Рекомендация для текущей настройки

Для текущего внедрения рекомендую **Вариант 1 (Environment Variables)** или **Вариант 3 (Windows Credential Manager)**:

### Если выберете Environment Variables:

```powershell
# 1. Установить переменные
[Environment]::SetEnvironmentVariable("AD_SERVICE_ACCOUNT", "svc_portal_read@mscher.local", "Machine")
[Environment]::SetEnvironmentVariable("AD_SERVICE_PASSWORD", "your-actual-password-here", "Machine")

# 2. Удалить из web.config
# Замените строки 40-41 на пустые значения

# 3. Перезапустить IIS
iisreset
```

### Если выберете Windows Credential Manager:

```powershell
# 1. Установить credentials
cmdkey /generic:PortalVOB3_AD /user:svc_portal_read@mscher.local /pass:your-actual-password-here

# 2. Обновить Django settings для чтения из Credential Manager
# (потребуется python library: pip install pywin32)

# 3. Удалить из web.config
# Замените строки 40-41 на пустые значения

# 4. Перезапустить IIS
iisreset
```

## Безопасные практики

### Общие рекомендации:
1. ✅ Никогда не коммитьте секреты в git
2. ✅ Используйте разные пароли для разных окружений
3. ✅ Регулярно меняйте пароли сервисных учетных записей
4. ✅ Логируйте попытки доступа к секретам
5. ✅ Ограничивайте доступ к файлам с секретами
6. ✅ Используйте минимальные права для сервисных учетных записей

### Для этого проекта:
- ✅ `web.config` уже в `.gitignore`
- ✅ Используйте `.env` файлы для локальной разработки
- ✅ Для production используйте Environment Variables или Credential Manager

## Аудит безопасности

```powershell
# Проверить, где хранятся секреты
Get-Content "C:\inetpub\portal\web.config" | Select-String "PASSWORD|SECRET|TOKEN"

# Проверить environment variables
[Environment]::GetEnvironmentVariables("Machine") | Format-List

# Проверить Windows Credential Manager
cmdkey /list | Select-String "PortalVOB3"

# Проверить права доступа к конфигурационным файлам
Get-Acl "C:\inetpub\portal\web.config"
```

Хотите, чтобы я реализовал один из этих вариантов для вашего проекта?