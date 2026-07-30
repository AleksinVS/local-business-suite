# Отчет исполнения 01-test-runtime-and-agent-cost-optimization

Статус: accepted.

Дата: 2026-07-30.

## Реализовано

- единый pytest-контур для Make и CI;
- отдельные `config.settings_test` с быстрым хешером, locmem email и артефактами в `.local/`;
- зафиксированные `requirements-dev.txt` и `requirements-dev.lock`;
- повторное использование SQLite test DB, повтор падений, профилирование и экспериментальный xdist;
- маркеры `unit`, `integration`, `slow`, `serial`;
- перенос общих Django-фикстур в `setUpTestData` и тестов без БД в `SimpleTestCase`;
- устранено случайное обнаружение вспомогательной функции как теста и сокращен тестовый timeout;
- Playwright-теги и экономные trace/video;
- CI с отменой устаревших запусков, кэшем, одним coverage и дешевым compatibility-контуром pull request;
- ступенчатые правила тестирования для людей и агентов, включая запрет общего stash/restore/reset.

## Проверки

- 40 `unit`: passed, 0,42 s;
- 247 целевых Django/AI/domain тестов и 4 подтеста: passed, 10,98 s;
- 170 core/filehub/memory/settings/runtime тестов и 22 подтеста: passed, 7,31 s;
- повтор предыдущих падений через `make test-failed`: 131 passed, 11,15 s;
- чистый `make test`: 523 passed, 63 subtests, 67,94 s;
- `make contracts`: passed;
- `manage.py check`: passed;
- `npm run test:e2e:smoke`: 1 passed, 1,3 s;
- JSON и workflow YAML: parsed successfully;
- `git diff --check`: выполняется после архивирования и генерации карты структуры.

## Ограничения

`make check` завершает успешный Django system check, но падает на уже существующем рассогласовании `static/src/` и `staticfiles/`. Синхронизация staticfiles не выполнялась: она затронула бы пользовательское незакоммиченное изменение `static/src/css/app.css` и другие файлы вне write scope.

## Производительность

Исходный профиль полного прогона: 25 минут 16 секунд. Чистый приемочный прогон после оптимизации: 67,94 секунды, то есть примерно в 22 раза быстрее. Повторный набор с сохраненной схемой базы устраняет примерно 40 секунд миграционной подготовки.
