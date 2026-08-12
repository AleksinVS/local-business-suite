# Block Brief: единый UX администрирования доступа

## Цель

Свести административные сценарии доступа в один понятный раздел и гарантировать,
что UI, Django Admin, ИИ и AD не обходят доменные проверки, preview и аудит.

## Пользовательская ценность

Администратор быстро находит человека, понимает итоговый доступ и его источник,
видит последствия до сохранения и расследует изменения в одном месте.

## Границы

- Сохраняются контрактные роли и доменные policies/selectors.
- Row-level пробелы ревью 2026-07-30 не входят в этот блок.
- JIT, approval, SoD workflow и регулярные access review не входят без отдельного
  решения. Privilege ceiling и запрет self-assignment для non-superuser входят как
  базовый инвариант; действующий superuser сохраняет рискованный self-assignment.
- Новый внешний policy engine и per-object ACL не вводятся.
- ИИ и AD получают адаптеры к доменным сервисам, но не владеют бизнес-правилами.

## Gate

ADR-0040 принят владельцем. Django Admin остаётся резервным адаптером к общему
service layer, а не прямым ORM-путём; AD ownership и разделение `manage_roles`
реализуются по принятому решению.

## Порядок

1. `00a-direct-write-path-containment`.
2. `00b-administration-policy-and-ceiling`.
3. `00c-contract-write-integrity`.
4. `00d-special-assignment-ownership`.
5. `01-access-shell-and-user-discovery`.
6. `02-user-access-workspace`.
7. `03-role-catalog-impact-editor`.
8. `04-audit-troubleshooter-and-sources`.
9. `05-e2e-usability-docs-acceptance`.

## Приемка

- нет прямых обходных путей изменения доступа; резервный Admin-сценарий использует
  тот же preview/apply и аудит;
- единый раздел покрывает пользователей, роли и аудит; источники раскрываются
  контекстно;
- критичные изменения имеют серверный impact preview;
- назначение и изменение определений разделены privilege ceiling;
- unit/integration/e2e, матрица путей и usability-проверка выполнены;
- документация и структура актуальны.

Пакеты 02/03 выполняются последовательно: они используют общий effective-access
read model, Settings Center views/tests и CSS.
