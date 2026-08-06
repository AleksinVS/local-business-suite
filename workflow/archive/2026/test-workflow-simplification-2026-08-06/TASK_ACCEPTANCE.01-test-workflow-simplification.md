# Приемка 01-test-workflow-simplification

Статус: accepted.

Дата: 2026-08-06.

Критерии выполнены:

- тесты не зависят от локальной `staticfiles/`;
- тестовая SQLite-база восстанавливается явной ограниченной командой;
- каждый pytest-тест имеет ровно один marker `unit`/`integration`;
- `serial` не выполняется xdist workers;
- CI и локальный запуск используют общие Make/script entrypoints;
- browser smoke выполняет реальный вход и проверяет shell портала;
- профильные и полный приемочный прогоны успешны.

ADR не требуется.
