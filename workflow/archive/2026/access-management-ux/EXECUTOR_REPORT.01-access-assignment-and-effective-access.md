# Executor Report: 01 — назначение и итоговый доступ

## Результат

Реализован существующий пользовательский контур Settings Center: список пользователей и
карточка доступа доступны суперпользователю либо пользователю с capability `manage_roles`.
Создание, отключение пользователя и привязка AD остались доступны только суперпользователю.

Назначение ролей выполняется через `apps.accounts.services`: принимаются только группы,
соответствующие ролям текущего `role_rules`; служебные ключи `$*` и неизвестные роли
отклоняются. Технические и memory-группы не участвуют в записи и сохраняются.

## Файлы

- `apps/accounts/models.py` — модель `AccessAssignmentAudit`.
- `apps/accounts/migrations/0007_accessassignmentaudit.py` — схема аудита и индексы actor/target/date.
- `apps/accounts/selectors.py` — роли контракта, технические группы, итоговые capability,
  флаги и Django permissions с источниками.
- `apps/accounts/services.py` — preview/apply, подпись preview, проверка риска,
  `select_for_update`, изменение M2M и audit в одной транзакции.
- `apps/accounts/management/commands/access_management_e2e.py` — откатываемый сквозной
  сценарий рискованного назначения.
- `apps/accounts/tests.py` — сервисные, selector и e2e-проверки.
- `apps/accounts/.desc.json` — описания новых узлов.
- `apps/settings_center/forms.py`, `views.py`, `tests.py` — форма ролей, авторизация,
  preview/apply и интеграционные тесты существующих маршрутов.
- `templates/settings_center/user_form.html`, `user_list.html` — карточка и список доступа.

## Решения и защита

- Preview подписывается стандартным `django.core.signing`; токен на 10 минут связан с
  actor ID, target ID, исходными и выбранными ролями. Raw token в audit не хранится.
- Apply повторно проверяет capability администратора, подпись и канонический diff, затем
  блокирует target через `select_for_update`. Прямой POST без preview и устаревший diff
  отклоняются.
- Риск выводится из `$capabilities[*].risk` (`elevated`/`critical`), label и description;
  при старой рабочей копии без `risk` применяется безопасный fallback `critical`.
- Рискованное добавление, включая self-escalation, требует явного server-side confirm.
- Audit хранит только связи actor/target, технические имена ролей, diff и маркеры риска;
  username, ФИО, email, токены и профильный payload не сохраняются. Связи защищены `PROTECT`.
- Endpoint назначения ролей не меняет `is_staff` и `is_superuser`.
- Для неавторизованного пользователя target не извлекается до проверки права, что не даёт
  различать существующий и отсутствующий ID по ответу.

## Проверки

- `make check` — Django system check прошёл; общая команда остановилась на чужой
  рассинхронизации `static/src` и `staticfiles`.
- `make test-fast TEST_SCOPE=apps/accounts/tests.py` — **17 passed, 2 subtests passed**.
- `make test-fast TEST_SCOPE=apps/settings_center/tests.py` — **17 passed**.
- объединённый прогон до добавления последнего self-escalation кейса — **33 passed,
  2 subtests passed**; после кейса файл accounts повторно прошёл полностью.
- `python manage.py check` — **OK**.
- `git diff --check -- apps/accounts apps/settings_center templates/settings_center` — **OK**.
- `makemigrations accounts --check --dry-run` — новая миграция audit согласована с моделью;
  команда всё ещё предлагает отдельную `AlterField(User.department)` из параллельной правки.

## Остаточные риски и внешние изменения

- В общем рабочем дереве параллельно изменён `User.department`: `SET_NULL/null=True` заменён
  на `PROTECT/non-null` без accounts-миграции. Это не относится к packet 01, не откатывалось;
  изменение вызывает падение старого `DemoSeedCommandTests` при удалении демо-подразделений
  и требует решения владельца параллельной правки.
- `make check` блокируется изменениями `static/src/css/app.css` и
  `static/src/js/access_role_editor.js` вне разрешённого write scope. `staticfiles` не менялся.
- Миграция `0007` не применялась к рабочей БД; сквозная management-команда проверена в
  тестовой БД и откатывает все создаваемые записи.
- Пользовательская/архитектурная документация и `PROJECT_STRUCTURE.yaml` не обновлялись:
  это запрещено write scope packet 01 и предусмотрено последующим packet 03. `.desc.json`
  приложения обновлён.
