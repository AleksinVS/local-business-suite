# Настройка LDAPS без сертификатов AD

## Ситуация

Вы правы - **LDAPS без настроенных сертификатов не имеет особого смысла** с точки зрения безопасности, но может быть полезен для совместимости.

## Текущая настройка

Я изменил конфигурацию на использование **LDAPS с отключенной проверкой сертификата**:

```xml
<add key="AD_LDAP_TRANSPORT" value="ldaps" />
<add key="AD_LDAP_PORT" value="636" />
<add key="AD_LDAP_VERIFY_CERT" value="false" />
```

**Что это означает:**
- Соединение шифруется (используется TLS)
- Но сертификат сервера не проверяется (уязвимость Man-in-the-Middle)
- Трафик зашифрован, но источник не подтвержден

## Альтернативные варианты

### Вариант 1: Обычный LDAP (небезопасно)
```xml
<add key="AD_LDAP_TRANSPORT" value="plain" />
<add key="AD_LDAP_PORT" value="389" />
<add key="AD_LDAP_ALLOW_INSECURE" value="true" />
```
**Плюсы:** Простой, гарантированно работает
**Минусы:** Пароли передаются в открытом виде, перехват трафика возможен

### Вариант 2: STARTTLS (рекомендуется если поддерживается)
```xml
<add key="AD_LDAP_TRANSPORT" value="starttls" />
<add key="AD_LDAP_PORT" value="389" />
<add key="AD_LDAP_VERIFY_CERT" value="false" />
```
**Плюсы:** Начинается как обычный LDAP, затем апгрейдится до TLS
**Минусы:** Требует поддержки STARTTLS на контроллере домена

### Вариант 3: LDAPS с отключенной проверкой сертификата (текущий)
```xml
<add key="AD_LDAP_TRANSPORT" value="ldaps" />
<add key="AD_LDAP_PORT" value="636" />
<add key="AD_LDAP_VERIFY_CERT" value="false" />
```
**Плюсы:** Трафик зашифрован, работает с самоподписанными сертификатами
**Минусы:** Уязвимость Man-in-the-Middle, источник не подтвержден

### Вариант 4: Настроить сертификаты AD (наиболее безопасно)
**Требует действий от системного администратора:**

1. **Создать Certificate Authority (CA)** в AD:
```powershell
# На контроллере домена (Domain Controller):
Install-WindowsFeature -Name AD-Certificate -IncludeManagementTools
```

2. **Выпустить сертификаты для контроллеров домена:**
```powershell
# На контроллере домена:
certutil -setreg CA\DSConfigDN "CN=Configuration,DC=mscher,DC=local"
certutil -setreg CA\CRLPublicationURLs "65:C:\Windows\System32\CertSrv\CertEnroll\%3%8%9.crl\n10:%3%8%9.crl\n6:http://%1/CertEnroll/%3%8%9.crl"
```

3. **Настроить службы Certificate Services на DC:**
```powershell
# На каждом контроллере домена:
certutil -setreg HKLM\SYSTEM\CurrentControlSet\Services\NTDS\Parameters\ServerCert **Thumbprint**
net stop NTDS
net start NTDS
```

4. **Проверить работу LDAPS:**
```powershell
Test-NetConnection -ComputerName stc-dc01.mscher.local -Port 636
```

## Рекомендация

### Для внутренней сети (за брандмауэром):
Используйте **текущую настройку** (LDAPS с отключенной проверкой сертификата):
- Трафик зашифрован
- Работает с существующей инфраструктурой
- Риск MITM минимален внутри доверенной сети

### Для публичного доступа или строгих требований безопасности:
1. **Обратитесь к системному администратору** для настройки Certificate Services в AD
2. Используйте **LDAPS с проверкой сертификата**:
```xml
<add key="AD_LDAP_TRANSPORT" value="ldaps" />
<add key="AD_LDAP_PORT" value="636" />
<add key="AD_LDAP_VERIFY_CERT" value="true" />
<!-- Удалите AD_LDAP_VERIFY_CERT=false -->
```

## Тестирование разных вариантов

### Протестировать обычный LDAP:
Измените в `web.config`:
```xml
<add key="AD_LDAP_TRANSPORT" value="plain" />
<add key="AD_LDAP_PORT" value="389" />
<add key="AD_LDAP_ALLOW_INSECURE" value="true" />
```

### Протестировать STARTTLS:
Измените в `web.config`:
```xml
<add key="AD_LDAP_TRANSPORT" value="starttls" />
<add key="AD_LDAP_PORT" value="389" />
```

После каждого изменения:
```powershell
iisreset
```

## Проверка поддержки STARTTLS на контроллере домена

```powershell
# Тестирование STARTTLS (на сервере или с модулем):
Import-Module ActiveDirectory
$domainController = "stc-dc01.mscher.local"
$port = 389

# Попробовать подключение с STARTTLS
try {
    $connection = New-Object System.Net.Sockets.TcpClient($domainController, $port)
    $stream = $connection.GetStream()
    $writer = New-Object System.IO.StreamWriter($stream)
    $reader = New-Object System.IO.StreamReader($stream)

    # Отправить STARTTLS запрос
    $writer.WriteLine("")
    $writer.Flush()

    # Проверить ответ
    $response = $reader.ReadLine()
    Write-Host "Ответ сервера: $response"

    $connection.Close()
} catch {
    Write-Host "Ошибка подключения: $_"
}
```

## Итог

**Для текущей инфраструктуры (внутренняя сеть):**
- Используйте LDAPS с `AD_LDAP_VERIFY_CERT=false` (текущая настройка)
- Это обеспечивает шифрование трафика без необходимости настройки сертификатов

**Для высокой безопасности:**
- Настройте Certificate Services в AD
- Используйте LDAPS с проверкой сертификата

**Вывод:** LDAPS без проверки сертификата лучше, чем обычный LDAP, но хуже, чем LDAPS с правильными сертификатами. Для внутренней сети текущая настройка приемлема.