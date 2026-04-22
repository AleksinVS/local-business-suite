# Корпоративный портал ВОБ №3

Корпоративный портал для управления техническим обслуживанием и ремонтами с поддержкой Active Directory интеграции.

## Основные возможности

- **Канбан-доска заявок** на ТО и ремонты с workflow
- **Справочник медицинских изделий** с архивацией
- **Active Directory интеграция** с SSO через Windows Authentication
- **AI чат** с интеграцией в бизнес-процессы
- **Аналитика** по заявкам и устройствам
- **Ролевая модель** с правами доступа

## Поддерживаемые платформы

### Linux/VPS (рекомендуется)
- Docker + Docker Compose
- Gunicorn + Caddy
- Полная документация в `DEPLOYMENT.md`

### Windows Server (IIS)
- IIS 10.0+ с FastCGI
- wfastcgi 3.0.0
- Python 3.11.9
- Документация в `IIS_SSO.md`

## Быстрый старт

### Разработка (Linux/VPS)

```bash
# Клонирование и настройка
git clone https://github.com/AleksinVS/local-business-suite.git
cd local-business-suite
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Настройте .env файл
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Разработка (Windows)

```cmd
git clone https://github.com/AleksinVS/local-business-suite.git
cd local-business-suite
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
REM Настройте .env файл
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Production (IIS)

См. `IIS_SSO.md` и `DEPLOYMENT.md` для детальных инструкций.

## Документация

- `PROJECT_HANDOFF.md` - обзор проекта для команды
- `DEPLOYMENT.md` - инструкции по развертыванию
- `IIS_SSO.md` - настройка IIS и Active Directory
- `SECURE_SECRETS.md` - безопасное хранение секретов
- `AGENTS.md` - протокол для AI-агентов
- `ENV_MIGRATION.md` - миграция на .env файлы

## Текущее состояние

Проект находится в активной разработке. Основные функции реализованы и работают:

✅ Канбан-доска с workflow  
✅ Справочник медицинских изделий  
✅ AD интеграция с SSO  
✅ AI чат  
✅ Аналитика  
✅ Ролевая модель  

## Лицензия

Проект является внутренним корпоративным приложением.

## Поддержка

Для вопросов по развертыванию и настройке см. соответствующие файлы документации.
