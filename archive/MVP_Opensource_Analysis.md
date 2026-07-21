# Анализ opensource решений для MVP Architecture

## 1. Стек технологии (из MVP_Architecture.md)
- **Backend:** Django 5.x (monorepo)
- **Database:** SQLite (WAL mode) + DuckDB (аналитика)
- **Auth:** LDAP (Active Directory через django-auth-ldap)
- **Frontend:** Django Templates + HTMX + Tailwind CSS
- **Deployment:** Docker Compose

---

## 2. Найденные подходящие opensource решения

### 2.1. Django + HTMX + Tailwind CSS (Frontend Boilerplates)

#### 📦 **django-saas-boilerplate**
- **URL:** https://github.com/eriktaveras/django-saas-boilerplate
- **Описание:** Modern, production-ready Django boilerplate для SaaS с HTMX, Tailwind CSS и Alpine.js
- **Подходит ли MVP:** ✅ Да
- **Почему подходит:**
  - Готовая интеграция HTMX + Tailwind
  - Современные best practices
  - Production-ready конфигурация
- **Примечание:** Использует Alpine.js для client-side интерактивности, что может быть избыточно для MVP, но можно отключить

#### 📦 **django-htmx-tailwind**
- **URL:** https://github.com/rayonx/django-htmx-tailwind
- **Описание:** Django + HTMX + AlpineJS + TailwindCSS/DaisyUI boilerplate
- **Подходит ли MVP:** ✅ Да
- **Почему подходит:**
  - Минималистичный стартовый шаблон
  - Включает Alpine.js (опционально)
  - Docker Compose включён в состав
- **Примечание:** Может быть хорошей базой для быстрого старта

#### 📚 **Tutorial: Rapid Prototyping with Django, htmx, and Tailwind CSS**
- **URL:** https://testdriven.io/blog/django-htmx-tailwind/
- **Описание:** Туториал по интеграции HTMX и Tailwind в Django
- **Подходит ли MVP:** ✅ Да (как обучающий материал)
- **Почему подходит:**
  - Подробное объяснение интеграции
  - Best practices для SSR + HTMX
- **Примечание:** Не готовый проект, а руководство

### 2.2. Django + DuckDB + SQLite (Аналитический слой)

#### 📦 **DuckDB SQLite Extension (sqlite_scanner)**
- **URL:** https://github.com/duckdb/sqlite_scanner
- **Описание:** Официальное расширение DuckDB для чтения/записи SQLite баз данных
- **Подходит ли MVP:** ✅ Да
- **Почему подходит:**
  - Позволяет делать аналитические запросы напрямую к SQLite файлу
  - Именно этот механизм упоминается в ТЗ
  - Официальная поддержка от команды DuckDB
- **Интеграция с Django:**
  ```python
  import duckdb
  
  # Пример запроса из файла SQLite
  db_path = settings.DATABASES['default']['NAME']
  query = f"""
      SELECT category, AVG(completion_time)
      FROM sqlite_scan('{db_path}', 'maintenance_task')
      GROUP BY category
  """
  result = duckdb.query(query).to_df()
  ```

#### 📚 **DuckDB Docs: SQLite Integration**
- **URL:** https://duckdb.org/docs/stable/guides/database_integration/sqlite
- **Описание:** Официальная документация по интеграции SQLite с DuckDB
- **Подходит ли MVP:** ✅ Да
- **Ключевые команды:**
  - `INSTALL sqlite` - установить расширение (один раз)
  - `LOAD sqlite` - загрузить расширение
  - `SELECT * FROM sqlite_scan('test.db', 'table_name')` - чтение таблицы из SQLite

### 2.3. Django + LDAP (Active Directory)

#### 📚 **django-auth-ldap Example Configuration**
- **URL:** https://django-auth-ldap.readthedocs.io/en/latest/example.html
- **Описание:** Официальная документация с примером конфигурации для Active Directory
- **Подходит ли MVP:** ✅ Да
- **Почему подходит:**
  - Стандартный пакет для Django
  - Поддержка Active Directory
  - Примеры конфигурации включают:
    - `AUTH_LDAP_SERVER_URI` - URI сервера LDAP
    - `AUTH_LDAP_BIND_DN` - DN для биндинга
    - `AUTH_LDAP_FIND_GROUP_PERMS` - кэширование прав
- **Пример конфигурации:**
  ```python
  AUTHENTICATION_BACKENDS = (
      'django_auth_ldap.backend.LDAPBackend',
      'django.contrib.auth.backends.ModelBackend',
  )
  AUTH_LDAP_SERVER_URI = "ldap://your-ad-server.local"
  AUTH_LDAP_BIND_DN = "cn=admin,dc=example,dc=com"
  AUTH_LDAP_BIND_PASSWORD = "your-password"
  AUTH_LDAP_FIND_GROUP_PERMS = True
  ```

#### 📚 **Django Auth with an LDAP Active Directory**
- **URL:** https://www.djm.org.uk/posts/using-django-auth-ldap-active-directory-ldaps/
- **Описание:** Практический гайд по настройке AD интеграции
- **Подходит ли MVP:** ✅ Да
- **Почему подходит:**
  - Показывает реальные настройки для продакшена
  - Включает настройку LDAPS (LDAP over SSL)

### 2.4. Kanban Board на Django + HTMX

#### 📦 **derhedwig/kanban**
- **URL:** https://github.com/derhedwig/kanban
- **Описание:** Kanban board with Django and HTMX
- **Подходит ли MVP:** ✅ Да
- **Почему подходит:**
  - ИДЕАЛЬНОЕ совпадение с технологическим стеком: Django + HTMX
  - Реализует drag-and-drop (через HTMX)
  - Можно изучить код для понимания паттернов
- **Примечание:** Нужно проверить актуальность (последний коммит)

#### 📦 **djanban**
- **URL:** https://github.com/diegojromerolopez/djanban
- **Описание:** Stats for kanban boards, Django application
- **Подходит ли MVP:** ✅ Частично
- **Почему подходит:**
  - Django-приложение
  - Можно изучить структуру моделей для Kanban
- **Примечание:** Использует React (не HTMX), но логика моделей может быть полезна

---

## 3. Рекомендации по использованию

### Для старта проекта (Frontend):
1. **django-htmx-tailwind** или **django-saas-boilerplate**:
   - Оба предоставляют готовый стек Django + HTMX + Tailwind
   - Выбирать в зависимости от сложности (boilerplate - для продакшена, ht-tailwind - для простого старта)

### Для аналитического слоя:
1. **Использовать официально расширение sqlite_scanner от DuckDB**:
   - Устанавливается через `INSTALL sqlite`
   - Позволяет делать запросы `SELECT ... FROM sqlite_scan('path.db', 'table_name')`
   - Поддерживается командой DuckDB, что гарантирует актуальность

### Для LDAP интеграции:
1. **django-auth-ldap** (пакет Python) + официальная документация:
   - Документация: https://django-auth-ldap.readthedocs.io/en/latest/example.html
   - Нужен LDAP-сервер с Active Directory

### Для Kanban-доски:
1. **Изучить derhedwig/kanban**:
   - Это прям совпадение: Django + HTMX
   - Реализует drag-and-drop через HTMX
   - Можно использовать как референс для модели данных и views

### Комбинированный подход:
Лучший вариант - взять **django-htmx-tailwind** как основу и:
1. Добавить интеграцию с DuckDB через sqlite_scanner
2. Подключить django-auth-ldap для AD
3. Адаптировать канбан-логику из **derhedwig/kanban** под нужную модель (`MedicalDevice`, `MaintenanceTask`)

---

## 4. Сводная таблица

| Компонент | Opensource решение | URL | Подходит |
|-----------|-------------------|-----|----------|
| Frontend (Django+HTMX+Tailwind) | django-saas-boilerplate | https://github.com/eriktaveras/django-saas-boilerplate | ✅ |
| Frontend (Django+HTMX+Tailwind) | django-htmx-tailwind | https://github.com/rayonx/django-htmx-tailwind | ✅ |
| Аналитика (DuckDB+SQLite) | DuckDB SQLite Extension | https://github.com/duckdb/sqlite_scanner | ✅ |
| Auth (LDAP+AD) | django-auth-ldap (docs) | https://django-auth-ldap.readthedocs.io/en/latest/example.html | ✅ |
| Kanban Board | derhedwig/kanban | https://github.com/derhedwig/kanban | ✅ |
| Kanban Stats | djanban | https://github.com/diegojromerolopez/djanban | ⚠️ (исп. React) |