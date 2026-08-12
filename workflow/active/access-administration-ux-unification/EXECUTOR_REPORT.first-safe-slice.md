# Отчёт исполнения: первый безопасный срез

Дата: 2026-08-12.

## Выполнено

- `00a`: защищены прямые пути Django Admin, AI и LDAP; добавлен резервный
  superuser preview/apply; lifecycle и inactive-account guards.
- `00b`: введён contract allowlist (`manager` → `customer`, `technician`),
  non-superuser self-assignment закрыт, superuser self-assignment сохранён с
  отдельным риском; определения ролей ограничены superuser.
- часть `01`: один пункт «Доступ», серверный поиск/фильтры, таблица из пяти
  столбцов, исправленная семантика меню и клавиатурный фокус.
- часть `02`: после создания открывается назначение роли; технические источники
  убраны в экспертное раскрытие; protected roles показываются read-only.
- role contract усилен строгими типами, известными capabilities и проверкой
  allowlist; старый контракт без `$administration` работает fail-closed.

## Проверки

- целевой набор accounts/settings/contract: 72 passed, 8 subtests;
- AI + agent runtime: 133 passed, 2 subtests;
- расширенный affected-suite: 407 passed, 9 deselected, 34 subtests;
- профиль `ui`: 248 passed + Playwright smoke 3 passed;
- профиль `contracts`: 48 passed (62 deselected);
- профиль `ai`: 196 passed, 6 subtests;
- полный `make verify-full`: 644 passed, 97 subtests;
- `python manage.py access_management_e2e` — OK, данные откатились;
- Playwright smoke desktop + 320px — 3 passed;
- `validate_architecture_contracts`, `makemigrations --check --dry-run`,
  `manage.py check`, `git diff --check` — успешно.

## Независимая проверка

Проверочная роль покрыла actor/path matrix и выявила LDAP inactive/race,
привилегированное создание пользователя, Django Admin password/group обходы,
подделку audit source, UX protected roles и quarantine department через AI.
Находки исправлены и покрыты регресс-тестами. Финальный повторный вывод хранится в
техническом handoff текущего исполнения.

## Не выполнено в этом срезе

- `00c`: staged file/audit protocol, reconciliation и межпроцессная блокировка;
- `00d`: полноценные доменные write-сервисы Board и memory technical groups;
- отдельный role catalog/impact editor, общий audit projection и explain adapters;
- модерируемый usability-тест на реальных администраторах.

Эти задачи остаются активными; workflow-блок не архивируется.
