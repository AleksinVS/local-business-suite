# Приёмка: 12-planning-docs-hygiene

Дата: 2026-07-07.
Роли: исполнение и приёмка — агент-оркестратор (контекстно-насыщенная
реструктуризация; список архивации согласован с владельцем одним вопросом).

## Вердикт

**Принят.** Планирование, документация и структура приведены в соответствие с
фактическим состоянием; список архивации утверждён владельцем.

## Согласование с владельцем (2026-07-07)

Сверка 7 блоков-кандидатов показала: не все неактуальны. Владельцу представлен
разбор по каждому; решение:
- **В архив:** architecture-review-remediation-2026-06-01 (superseded) +
  memory-audit-review-ui, settings-center-gui,
  testing-policy-and-independent-verification, universal-right-drawer-ai-navigation
  (implemented — владелец засчитал приёмку их фич).
- **Остаются active:** design-patterns-hardening-2026-06-01 (backlog Next,
  подготовленный будущий блок) и memory-hybrid-ranking-profiles (backlog Later,
  управляемо отложен).

## Acceptance-проверки

- `node scripts/dev/generate-structure.js` (`make gen-struct`) — проходит,
  PROJECT_STRUCTURE.yaml отражает переносы.
- `git ls-files deployments/DEPLOY_PRIVATE.md` — файл отслеживается.
- Сверка: каждый из 17 оставшихся блоков `workflow/active` имеет соответствие в
  backlog (0 сирот).
- Ссылки: `grep` повисших active-ссылок на перенесённые файлы — 0; битая ссылка
  ARCHITECTURE.md устранена; 6 ссылок перенаправлены на archive-пути.
- `.desc.json` всех затронутых каталогов валидны (`json.load`).

## Замечание

Текущий блок (architecture-review-remediation-2026-07-04) остаётся в
`workflow/active` и `docs/planning/active` — его архивация и удаление из active
backlog выполняются ПОСЛЕ приёмки всего блока владельцем (стандартный порядок
проекта). Отчёты/приёмки всех 12 пакетов — в этом каталоге.

## Отложено (в рекомендацию)

- DOMAIN_MODEL.md — обновление под inventory-модель (Department OID/FRMO после
  слияния ветки) не входило в write_scope пакета; отдельная doc-задача.
- Кандидаты в пакет 13 / отдельные задачи из находок блока: защищённая раздача
  `ChatAttachment` (следствие п.03), решение по цепочке таймаутов (следствие
  п.05), развязка core→workorders в contract_store/forms через реестр валидаторов
  (следствие п.11) — все зафиксированы в backlog / TASK_ACCEPTANCE соответствующих
  пакетов.
