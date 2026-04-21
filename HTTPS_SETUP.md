# Настройка HTTPS для полной безопасности

## Текущая ситуация

**Почему LDAPS бессмысленен без HTTPS:**

```
❌ Безопасность:
Клиент -> [HTTP] -> Веб-сервер -> [LDAPS] -> AD
   ❌              ✅
Перехват       Защищено
возможен
```

**Проблема:**
- Если есть HTTPS между клиентом и веб-сервером - LDAPS полезен
- Если только HTTP - LDAPS почти бесполезен

## Решение: Настройка HTTPS

### Вариант 1: Самоподписанный сертификат (для внутренней сети)

**Подходит для:**
- Внутреннего использования
- Доверенных пользователей
- Тестирования

**Создание самоподписанного сертификата:**
```powershell
# Создание сертификата
$cert = New-SelfSignedCertificate `
    -DnsName "stc-web.mscher.local", "stc-web" `
    -CertStoreLocation "cert:\LocalMachine\My" `
    -KeyLength 2048 `
    -KeyUsage DigitalSignature,KeyEncipherment `
    -Type SSLServerAuthentication

# Добавление в доверенные корневые сертификаты (на клиентских машинах):
$certPath = "cert:\LocalMachine\Root\"
$cert | Export-Certificate -FilePath "C:\temp\portal_cert.cer"

# На клиентских машинах:
Import-Certificate -FilePath "\\server\share\portal_cert.cer" -CertStoreLocation "cert:\LocalMachine\Root"
```

**Настройка HTTPS в IIS:**
```powershell
# Добавление HTTPS binding
Import-Module WebAdministration
$siteName = "Default Web Site"
$certThumbprint = (Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {$_.Subject -like "*stc-web*"}).Thumbprint

New-WebBinding -Name $siteName `
    -Protocol "https" `
    -Port 443 `
    -IPAddress "*" `
    -SslFlags 0

# Привязка сертификата
(Get-WebBinding -Name $siteName -Protocol "https").AddSslCertificate($certThumbprint, "my")

# Перенаправление HTTP на HTTPS (опционально)
$httpsRedirect = @"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="HTTP to HTTPS redirect" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTPS}" pattern="off" ignoreCase="true" />
          </conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@

$httpsRedirect | Out-File -FilePath "C:\inetpub\portal\web_https.config" -Encoding UTF8
```

### Вариант 2: Let's Encrypt (бесплатный, но требует публичный DNS)

**Требования:**
- Публичный DNS домен (например, portal.yourcompany.com)
- Доступ к серверу из интернета

**Установка certbot:**
```powershell
# Скачать и установить Win-ACME
# https://www.win-acme.com/

# Или использовать certbot для Windows
choco install certbot -y

# Получение сертификата
certbot certonly --standalone -d portal.yourcompany.com
```

### Вариант 3: Корпоративный PKI (наиболее надежный)

**Подходит для:**
- Корпоративной сети с настроенным PKI
- Большого количества пользователей

**Требует:**
- Запрос сертификата в корпоративном PKI
- Выпуск сертификата администратором PKI

**Процесс:**
1. Создать CSR (Certificate Signing Request)
2. Отправить администратору PKI
3. Получить сертификат
4. Импортировать в IIS

## После настройки HTTPS

### 1. Обновить URL в Django settings:

```python
# В C:\inetpub\portal\config\settings.py:
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

### 2. Обновить ALLOWED_HOSTS:

```python
ALLOWED_HOSTS = [
    "stc-web.mscher.local",
    "stc-web",
    "127.0.0.1",
    "localhost",
]
```

### 3. Обновить web.config для HTTPS:

```xml
<configuration>
  <system.webServer>
    <!-- Добавить редирект с HTTP на HTTPS -->
    <rewrite>
      <rules>
        <rule name="HTTP to HTTPS redirect" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTPS}" pattern="off" ignoreCase="true" />
          </conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

### 4. Установить сертификат на клиентских машинах (если самоподписанный):

**Через GPO (Group Policy):**
```
Computer Configuration -> Policies -> Windows Settings ->
Security Settings -> Public Key Policies -> Trusted Root Certification Authorities
```

**Или вручную:**
```powershell
# На клиентской машине:
Import-Certificate -FilePath "\\stc-web\share\portal_cert.cer" -CertStoreLocation "cert:\LocalMachine\Root"
```

## Проверка HTTPS

### 1. Проверка IIS binding:
```powershell
Get-WebBinding -Name "Default Web Site"
```

Должно показать:
- http *:80:
- https *:443:

### 2. Проверка сертификата:
```powershell
Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {$_.Subject -like "*stc-web*"}
```

### 3. Тестирование доступа:
```powershell
# Должен работать:
Invoke-WebRequest -Uri "https://stc-web/" -UseDefaultCredentials -UseBasicParsing

# Должен перенаправлять на HTTPS:
Invoke-WebRequest -Uri "http://stc-web/" -UseDefaultCredentials -UseBasicParsing -MaximumRedirection 0
```

## Итоговая архитектура безопасности

**С HTTPS:**
```
Клиент -> [HTTPS] -> Веб-сервер -> [LDAPS] -> AD
   ✅              ✅
Защищено        Защищено
```

**Без HTTPS:**
```
Клинет -> [HTTP] -> Веб-сервер -> [LDAPS] -> AD
   ❌              ✅
Уязвимо        Защищено (но уже поздно)
```

## Рекомендация

1. **Срочно:** Настроить HTTPS (самоподписанный сертификат)
2. **Долгосрочно:** Получить сертификат от корпоративного PKI или Let's Encrypt
3. **После HTTPS:** LDAPS станет полезным для защиты связи с AD

## Быстрый старт (самоподписанный сертификат)

```powershell
# 1. Создать сертификат
$cert = New-SelfSignedCertificate -DnsName "stc-web.mscher.local" -CertStoreLocation "cert:\LocalMachine\My"

# 2. Добавить HTTPS binding
New-WebBinding -Name "Default Web Site" -Protocol "https" -Port 443
$certThumbprint = $cert.Thumbprint
(Get-WebBinding -Name "Default Web Site" -Protocol "https").AddSslCertificate($certThumbprint, "my")

# 3. Перезапустить IIS
iisreset

# 4. Тестировать
Start-Process "https://stc-web"
```

**На клиентских машинах добавить сертификат в доверенные:**
```powershell
# Экспортировать сертификат с сервера:
$cert = Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {$_.Subject -like "*stc-web*"}
$cert | Export-Certificate -FilePath "\\stc-web\share\portal_cert.cer"

# На клиенте:
Import-Certificate -FilePath "\\stc-web\share\portal_cert.cer" -CertStoreLocation "cert:\LocalMachine\Root"
```

Хотите настроить HTTPS прямо сейчас?