# Executor report: 12-planning-docs-hygiene

Дата: 2026-07-07. Исполнитель: агент-оркестратор (напрямую — контекстно-насыщенная
реструктуризация документации с перекрёстными ссылками).

## Что сделано

### Архивация блоков (по решению владельца 2026-07-07)

Владелец согласовал: архивировать superseded [1] + принять-и-архивировать 4
реализованных ([3][5][6][7]); оставить active [2] design-patterns и [4]
memory-hybrid-ranking-profiles (будущая работа: backlog Next/Later).

Перенесено `git mv` в архив:
- **workflow/active → workflow/archive/2026/** (5 блоков):
  architecture-review-remediation-2026-06-01 (superseded, поглощён текущим),
  memory-audit-review-ui, settings-center-gui,
  testing-policy-and-independent-verification, universal-right-drawer-ai-navigation
  (4 последних — implemented, приняты владельцем).
- **docs/planning/active → docs/planning/archive/2026/** (4 плана; у
  testing-policy плана в active не было).

### .desc.json (структурно, через Python — порядок ключей сохранён)

- workflow/active: удалены 5 записей; workflow/archive/2026: добавлены 5.
- docs/planning/active: удалены 4; docs/planning/archive/2026: добавлены 4.
- Все 4 файла проходят `json.load`.

### backlog.md

- Удалена устаревшая Next-секция «Исправления по архитектурному ревью 2026-06-01»
  (весь её scope поглощён текущим блоком: role_rules→п01, prompt/identity→п05,
  IIS/PATH_INFO→п04, SQLite→п10, ссылки→п12).
- Ссылка на перенесённый план settings-center-gui в разделе обезличивания →
  archive-путь.
- «Оставшееся действие» текущего блока: отражено, что все 12 пакетов исполнены и
  приняты; блок ожидает приёмки владельцем.
- Устаревшие после ADR-0032 упоминания драйвера `legacy` в smoke/e2e-списках
  блоков native-ag-ui и copilotkit — убраны.

### Ссылки и структура

- **ARCHITECTURE.md**: битая ссылка `../../ai/chat_agent/ARCHITECTURE.md` заменена
  на существующие `AI_UI_PROTOCOL_FOUNDATION_PLAN.md` / `NATIVE_AG_UI_CHAT_DEVELOPMENT_PLAN.md`;
  в список ADR добавлены 0030, 0031, 0032, 0033.
- Исправлены 6 «повисших» ссылок на перенесённые файлы (active→archive пути) в
  ARCHITECTURE_REVIEW_2026-07-04.md, backlog.md, текущем плане,
  design-patterns-плане, data-anonymization-плане.
- **DEPLOY_PRIVATE.md**: перенос в deployments/ (+ .gitignore-негации, deployments/.desc.json)
  выполнен ранее (2026-07-05) — только проверено: файл отслеживается git.
- `make gen-struct` → PROJECT_STRUCTURE.yaml перегенерирован.

## Проверки

- `make gen-struct` — проходит.
- `git ls-files deployments/DEPLOY_PRIVATE.md` — файл отслеживается.
- Каждый из 17 оставшихся блоков в workflow/active имеет соответствие в backlog
  (0 сирот).
- grep повисших active-ссылок на перенесённые блоки/планы — 0.
- `grep "ai/chat_agent/ARCHITECTURE.md" ARCHITECTURE.md` — вхождений нет.

## Не входило / вне scope

- learning/, drafts/, корневой личный BACKLOG.md — не тронуты (решение владельца).
- Текущий блок (architecture-review-remediation-2026-07-04) НЕ архивирован —
  архивация всего блока после приёмки владельцем (см. backlog «Оставшееся действие»).
- DOMAIN_MODEL.md (Department OID/FRMO после слияния inventory) не входил в
  write_scope — кандидат в отдельную doc-задачу.
