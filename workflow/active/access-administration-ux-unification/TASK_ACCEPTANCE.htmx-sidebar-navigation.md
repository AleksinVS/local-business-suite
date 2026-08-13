# Приёмка пакета 09: HTMX-навигация боковых панелей

## Результат

Левый редактор и правый инспектор единого окна доступа загружаются частичным
серверным HTML без перезагрузки документа. Обычные Django-ссылки и POST/redirect
сохранены как прогрессивный fallback.

## Принятые инварианты

- сервер принимает только известные HTMX target-регионы;
- preview и ошибки заменяют только активную панель;
- apply обновляет панель и табличную проекцию одним ответом;
- URL и Back/Forward восстанавливают выбранную панель;
- `hx-preserve` сохраняет живой DOM встроенного ИИ-чата при восстановлении истории;
- history cache miss возвращает полный канонический документ;
- dirty guard, focus, inert и busy-состояния повторно применяются после swap;
- права, CSRF, preview token, stale-check и аудит остаются серверными.

## Проверки

- `make verify-fast TEST_SCOPE=apps/settings_center/tests.py` — 65 passed,
  1 deselected, 9 subtests passed;
- `node --check static/src/js/access_workspace.js` — успешно;
- `git diff --check` — успешно;
- `make verify-profile PROFILE=ui` — 269 passed, 18 subtests passed;
  Playwright smoke-профиль — 11 passed;
- целевой Playwright `access_administration.spec.ts` — 10 passed;
- независимая Luna-критика выявила замену живого DOM ИИ-чата при history restore,
  cache-miss 400, stale root, потерю dirty и фокуса после ошибок/swap; все замечания
  исправлены и закрыты повторными серверными и браузерными проверками;
- основной агент отдельно подтвердил строгую идентичность узла ИИ-чата после
  открытия, Back и Forward.

## Остаточная граница

Вкладки и фильтры намеренно используют обычную полную навигацию; пакет ограничен
открытием, закрытием и изменением данных в боковых панелях.
