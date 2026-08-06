# Внедрение на сервер IIS (приватный репозиторий)

Конфигурация IIS-развёртывания находится в отдельном приватном репозитории.

## Получение файлов

```bash
mkdir -p deployments
git clone https://github.com/AleksinVS/vob3-deployment.git deployments/vob3
```

Клонируйте приватный репозиторий только в `deployments/<host>/`. Путь `VOB3/` в корне считается legacy/local mistake и оставлен в `.gitignore` только как защита от случайного коммита.

## Содержимое приватного репозитория

- `web.config.template` — шаблон IIS-конфигурации (wfastcgi)
- `.env.example.vob3` — пример переменных окружения для продакшена
- `AD_SETUP.md` — инструкция по настройке Active Directory / LDAP
- `AD_LDAPS_CERTS.md` — настройка LDAPS-сертификатов
- `HTTPS_SETUP.md` — настройка HTTPS на IIS
- `README.md` — общая инструкция по развёртыванию

## Обновление

```bash
cd deployments/vob3 && git pull && cd ../..
```

После обновления основного проекта перенесите в приватный `web.config.template`
исключение `location path="favicon.ico"` из `docs/deployment/IIS_SSO.md`. Оно не
даёт автоматическому запросу браузера попасть в wfastcgi/Django и создать
конкурирующие session/CSRF cookie при первом Windows SSO-входе. Проверка:
`scripts/windows/setup_wfastcgi.ps1 -CheckOnly`.

На существующем хосте конфигурацию можно безопасно применить скриптом
`scripts/windows/update_iis_favicon_bypass.ps1`: сначала `-DryRun`, затем обычный
запуск с явными `-PortalRoot`, `-SiteName` и `-FaviconUrl`. Скрипт создаёт
host-local резервную копию `web.config.backup-*`; она не коммитится.

## Замечания

- Не коммитьте файлы из `deployments/` в основной репозиторий.
- Секреты (`.env`, production-переменные, сертификаты, host-specific compose/web.config) хранятся только в приватном deployment-репозитории или на сервере.
