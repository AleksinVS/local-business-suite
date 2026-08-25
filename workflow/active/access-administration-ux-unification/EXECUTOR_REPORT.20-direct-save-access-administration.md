# Executor report: direct Save для продуктового администрирования доступа

## Результат

Обычные web-редакторы workspace и standalone используют один POST `action=save`.
Проверены и синхронизированы пользовательские формулировки пакета 20: composite
user, профиль, AD identity, роли пользователя, определение и состав роли, доска и
группы памяти применяются через `save_*` сервисы с доменным аудитом.

В `AccessWorkspaceView` удалены безопасные переходные аргументы `action` из
внутренних `_post_*`, удалены обращения к отсутствующему `preview_token`,
`field_preview` и неиспользуемый `_set_form_value`. Generic settings preview
сохранён. Доменные preview/apply-сервисы и их сообщения не изменялись.

## Документация

- `BLOCK_BRIEF.md` и `ARCHITECT_PLAN.json` дополнены пакетом 20 и прямым Save;
  явно сохранены исключения Django Admin, AI и generic runtime settings.
- Активный план обновлён: product web UX описан как один Save, а старые
  preview/apply утверждения ограничены исключёнными контурами или доменным
  переходным слоем.

## Проверки

- `python3 -m py_compile apps/settings_center/views.py apps/settings_center/forms.py apps/settings_center/management/commands/access_administration_e2e.py apps/settings_center/tests.py` — успешно.
- `python3 -m json.tool workflow/active/access-administration-ux-unification/ARCHITECT_PLAN.json >/dev/null` — успешно.
- `git diff --check` — успешно.

Долгие тестовые наборы и `verify-full` не запускались по указанию задачи.

## Остаточный риск

Playwright и полный Django-набор после этой документно-мёртвой очистки не
запускались; ранее целевые проверки пакета 20 были выполнены. Рабочее дерево
не коммитилось.
