# IIS SSO And LDAP Auth

## Назначение

Проект поддерживает четыре режима авторизации через `DJANGO_AUTH_MODE`:

- `local` - только локальные пользователи Django.
- `ldap` - вход через форму Django, пароль проверяется в Active Directory через LDAP.
- `remote_user` - SSO через внешний веб-сервер, например IIS Windows Authentication.
- `hybrid` - основной режим: SSO через `REMOTE_USER`, если он есть, плюс fallback на форму Django с LDAP-проверкой пароля.

Текущий быстрый режим для доверенной сети:

```env
DJANGO_AUTH_MODE=hybrid
AD_LDAP_TRANSPORT=plain
AD_LDAP_ALLOW_INSECURE=true
AD_LDAP_VERIFY_CERT=false
```

Этот режим не требует сертификатов, но доменные пароли при LDAP bind не защищены TLS. Используйте его только как временный первый этап в доверенной сети.

## Как работает hybrid

1. Если IIS передал `REMOTE_USER`, Django создает или находит локального пользователя.
2. Имя нормализуется из `MSCHER\ivanov` или `ivanov@mscher.local` в `ivanov`.
3. Django пытается синхронизировать профиль из AD: `mail`, `displayName`, `givenName`, `sn`, `memberOf`.
4. Если `REMOTE_USER` нет, пользователь может войти через `/accounts/login/`.
5. Форма логина проверяет пароль через LDAP и также синхронизирует профиль.

На Linux SSO без ввода логина и пароля тоже возможно, но только если перед Django стоит сервер, который выполняет Kerberos/Negotiate и передает `REMOTE_USER`, например Apache с `mod_auth_gssapi`. Один только Django на Linux не делает Kerberos SSO автоматически.

## Быстрая настройка без сертификатов

```env
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=replace-me
DJANGO_ALLOWED_HOSTS=suite.mscher.local

DJANGO_AUTH_MODE=hybrid

AD_LDAP_TRANSPORT=plain
AD_LDAP_ALLOW_INSECURE=true
AD_LDAP_VERIFY_CERT=false
AD_LDAP_HOST=dc01.mscher.local
AD_LDAP_PORT=389
AD_LDAP_DOMAIN=MSCHER
AD_SEARCH_DN=DC=mscher,DC=local
AD_SERVICE_ACCOUNT=MSCHER\svc_local_business
AD_SERVICE_PASSWORD=replace-me
AD_LDAP_USER_FILTER=(sAMAccountName={username})
AD_GROUP_ROLE_MAP={"Domain Admins":"manager","IT Support":"technician","Employees":"customer"}
```

`AD_SERVICE_ACCOUNT` нужен для поиска пользователя и чтения атрибутов. Для входа через форму пользовательский пароль проверяется отдельным bind от DN найденного пользователя.

## IIS: публикация на верхнем уровне

Создайте отдельный IIS Site, а не application внутри другого сайта.

Пример:

- Site name: `Local Business Suite`
- Physical path: `C:\inetpub\local-business-suite`
- Binding: `https`, host name `suite.mscher.local`, port `443`
- Application Pool: отдельный pool, например `LocalBusinessSuite`

URL приложения будет:

```text
https://suite.mscher.local/
```

а не:

```text
https://suite.mscher.local/local-business-suite/
```

Если на этом IIS уже есть 1С-сервис с SSO, например `http://stc-web/WL/`, самый безопасный вариант - оставить его как есть и дать Local Business Suite отдельное имя хоста на том же сервере:

```text
http://stc-lbs/
```

или:

```text
http://local-business-suite/
```

Так 1С остается на `http://stc-web/WL/`, а Python FastCGI handler, `web.config` и правила auth нового приложения не наследуются 1С-сервисом.

Для отдельного имени нужна DNS-настройка:

- `A` record на IP IIS-сервера; или
- `CNAME` на существующее имя `stc-web`.

Для временной проверки можно прописать имя в `hosts` на одной машине, но для доменного SSO лучше использовать нормальную DNS-запись. Браузер должен открывать приложение по тому же имени, для которого настроены IIS binding и Kerberos/SPN.

Если принципиально нужно разместить Local Business Suite в корне `http://stc-web/`, оставьте `/WL/` отдельным IIS application с собственным application pool и проверьте, что корневой `web.config` Django не перехватывает `/WL/`. В этом варианте особенно важно изолировать handler mappings и authentication rules для `/WL/`.

При отдельном host header для Kerberos SSO может понадобиться SPN для нового имени, например `HTTP/stc-lbs`, на учетной записи application pool или компьютера IIS. Если используется прежнее имя `stc-web`, существующий SPN, скорее всего, уже настроен для 1С.

## IIS: Windows Authentication

Для SSO включите на сайте:

- `Windows Authentication`: `Enabled`
- `Anonymous Authentication`: см. ниже

В `Windows Authentication -> Providers` поставьте:

1. `Negotiate`
2. `NTLM`

`Negotiate` нужен для Kerberos. `NTLM` остается fallback.

### Строгий SSO

Если нужен только SSO:

- на всем сайте `Anonymous Authentication = Disabled`;
- `Windows Authentication = Enabled`;
- `DJANGO_AUTH_MODE=remote_user` или `hybrid`.

В этом варианте пользователь без доменной Windows-аутентификации до Django login-формы не дойдет.

### SSO плюс fallback-форма

Если нужен SSO и запасной вход по логину/паролю:

- на сайте `Windows Authentication = Enabled`;
- для `/accounts/login/` разрешите `Anonymous Authentication`;
- оставьте `DJANGO_AUTH_MODE=hybrid`.

В IIS это обычно делают отдельным location/application rule для пути `accounts/login`, чтобы форма была доступна без Windows auth. Остальные рабочие страницы могут оставаться под Windows auth.

## Пример web.config

Файл кладется в корень проекта рядом с `manage.py`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <handlers>
      <add name="Python FastCGI"
           path="*"
           verb="*"
           modules="FastCgiModule"
           scriptProcessor="C:\inetpub\local-business-suite\.venv\Scripts\python.exe|C:\inetpub\local-business-suite\.venv\Lib\site-packages\wfastcgi.py"
           resourceType="Unspecified"
           requireAccess="Script" />
    </handlers>

    <security>
      <authentication>
        <anonymousAuthentication enabled="false" />
        <windowsAuthentication enabled="true" />
      </authentication>
    </security>
  </system.webServer>

  <appSettings>
    <add key="DJANGO_SETTINGS_MODULE" value="config.settings" />
    <add key="WSGI_HANDLER" value="config.wsgi.application" />
    <add key="PYTHONPATH" value="C:\inetpub\local-business-suite" />

    <add key="DJANGO_DEBUG" value="0" />
    <add key="DJANGO_SECRET_KEY" value="replace-me" />
    <add key="DJANGO_ALLOWED_HOSTS" value="suite.mscher.local" />
    <add key="DJANGO_AUTH_MODE" value="hybrid" />

    <add key="AD_LDAP_TRANSPORT" value="plain" />
    <add key="AD_LDAP_ALLOW_INSECURE" value="true" />
    <add key="AD_LDAP_VERIFY_CERT" value="false" />
    <add key="AD_LDAP_HOST" value="dc01.mscher.local" />
    <add key="AD_LDAP_PORT" value="389" />
    <add key="AD_LDAP_DOMAIN" value="MSCHER" />
    <add key="AD_SEARCH_DN" value="DC=mscher,DC=local" />
    <add key="AD_SERVICE_ACCOUNT" value="MSCHER\svc_local_business" />
    <add key="AD_SERVICE_PASSWORD" value="replace-me" />
    <add key="AD_LDAP_USER_FILTER" value="(sAMAccountName={username})" />
    <add key="AD_GROUP_ROLE_MAP" value="{&quot;Domain Admins&quot;:&quot;manager&quot;,&quot;IT Support&quot;:&quot;technician&quot;,&quot;Employees&quot;:&quot;customer&quot;}" />
  </appSettings>
</configuration>
```

Для fallback-формы через `/accounts/login/` настройте IIS так, чтобы этот путь мог открываться anonymous. Иначе IIS перехватит запрос раньше Django.

## Установка на Windows Server

```powershell
cd C:\inetpub\local-business-suite

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\pip.exe install wfastcgi
.\.venv\Scripts\python.exe -m wfastcgi enable

.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py seed_roles
.\.venv\Scripts\python.exe manage.py check
```

## Переход на нормальный LDAPS

Когда сертификаты будут готовы, меняйте только транспортные env-переменные:

```env
AD_LDAP_TRANSPORT=ldaps
AD_LDAP_ALLOW_INSECURE=false
AD_LDAP_VERIFY_CERT=true
AD_LDAP_HOST=dc01.mscher.local
AD_LDAP_PORT=636
AD_LDAP_CA_FILE=C:\certs\mscher-root-ca.pem
```

Альтернатива через StartTLS на 389:

```env
AD_LDAP_TRANSPORT=starttls
AD_LDAP_ALLOW_INSECURE=false
AD_LDAP_VERIFY_CERT=true
AD_LDAP_HOST=dc01.mscher.local
AD_LDAP_PORT=389
AD_LDAP_CA_FILE=C:\certs\mscher-root-ca.pem
```

При `ldaps` и `starttls` имя в сертификате должно совпадать с `AD_LDAP_HOST`.

## Проверка

Проверить базовый старт:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Проверить SSO:

1. Откройте `https://suite.mscher.local/` с доменной машины.
2. Убедитесь, что IIS не спрашивает пароль, если Kerberos работает.
3. В Django admin проверьте, что пользователь создан с нормализованным username.
4. Проверьте email/ФИО и группы.

Проверить fallback:

1. Откройте `/accounts/login/`.
2. Введите доменный логин `ivanov` и пароль.
3. Пользователь должен войти через LDAP bind.

Если SSO не работает, сначала проверьте IIS logs и Windows Authentication providers. Если fallback не работает, проверьте доступность `AD_LDAP_HOST:389`, service account и `AD_SEARCH_DN`.
