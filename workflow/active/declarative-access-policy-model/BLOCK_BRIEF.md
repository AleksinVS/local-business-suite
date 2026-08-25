# Block Brief: упрощённое управление ролями

## Цель

Удалить преждевременную метаполитику и скрытый доступ, сохранив доменные
проверки, атомарную запись и аудит.

## Gate

ADR-0043 принят. Реализация ведётся в `feature/lean-access-control`. До code и
test packages выполняется Sol high review архитектуры, затем фиксируется и
публикуется документационный baseline. Перед финальным feature push, merge и
main push выполняется отдельный Sol high review точного commit SHA.

## Порядок

1. `00-baseline-and-golden-matrix`.
2. `01-freeze-capability-metadata`.
3. `02-disable-ai-ad-access-mutations`.
4. `03-single-role-administration-authority`.
5. `04-explicit-viewer-migration`.
6. `05-explain-cleanup`.
7. `06-ui-and-e2e-acceptance`.
8. `07-final-security-acceptance`.

## Главные границы

- Один `role_rules.json`; новый policy framework не создаётся.
- `manage_roles` — единственный product authority для обычных ролей.
- Protected roles — только active superuser; полный набор сохраняет текущие
  critical data/admin boundaries.
- Нет роли — нет общего role-derived product access; явная техническая власть
  домена остаётся ограниченной своим ACL.
- Domain policy/selector/service и memory/source ACL сохраняются.
- AI и AD не применяют изменения ролей.
- DB migration ролей и упрощение status semantics не входят.

## Приёмка

- `$capabilities` нельзя изменить через apply/rollback/Save, а deployment update
  требует current-runtime/target-Git hashes и отдельной команды;
- ordinary admin управляет только ordinary roles и не меняет себя;
- protected roles и technical flags доступны только active superuser;
- пользователи без роли не получают скрытый viewer-доступ; least-privilege
  `viewer` назначается только по явному решению;
- обычный UI сохраняет одним request; внутренний signed plan не является частью
  пользовательского протокола и не удаляется в этом блоке;
- AI/AD/Admin/commands не обходят согласованные границы;
- contract/service/HTTP/browser tests и полный verify проходят;
- Sol high даёт PASS перед merge и push.
