# Исполнительский отчёт: authority hardening редактора ролей

## Реализовано

- В дефолтном role contract добавлен отдельный блок
  $administration.role_definition_editor_roles: ["admin"]; он не смешан с
  allowlist назначения ролей.
- Добавлен Python-selector из одного снимка role_rules:
  отсутствующее поле временно совместимо и означает admin, malformed,
  повторяющееся или неизвестное значение закрывает доступ. JSON Schema и
  доменный валидатор проверяют тип, уникальность и известность кодов ролей.
- is_staff больше не является продуктовой властью редактора определений ролей:
  он сохраняет только вход в Django Admin. Product editor — active superuser
  либо участник настроенной editor-role.
- Delegated editor не может менять определение роли, которой сам обладает.
  Для чужой роли normal/elevated изменения проходят обычный preview/apply;
  critical capability можно только монотонно сужать с подтверждением риска.
  Critical expansion и mixed/incomparable change доступны только active
  superuser. Self-assignment superuser не затрагивался.
- Полный apply_contract_payload для core.contract.role_rules ограничен
  active superuser. Для delegated editor добавлен отдельный внутренний
  single-role transport; публичный apply_role_definition_payload отсутствует.
  Кандидат строится после чтения свежего файла под lock, а service-level
  invariant запрещает пустой/служебный/несуществующий role_code, изменение
  sibling roles и служебных блоков, добавление или удаление top-level ключей.
- Callback lock-протокола теперь получает свежий before payload; перед
  записью повторно проверяются actor/editor roles, target-held policy, base
  hash, направление critical change, member fingerprint и impact.
- Обновлены ADR-0040, активный план и руководство пользователя.

## Проверки

- .venv/bin/python -m pytest apps/settings_center/tests.py --reuse-db -q -k
  'test_role_definition_administration_matrix_and_click_without_field or
  test_delegated_editor_critical_policy_and_target_role_ceiling or
  test_role_contract_service_rejects_non_superuser_direct_call or
  test_delegated_role_writer_rejects_sibling_and_service_blocks or
  test_staff_is_not_product_role_editor_but_superuser_can_use_raw_writer'
  — 5 passed.
- .venv/bin/python manage.py validate_architecture_contracts — успешно;
  обнаружен только ожидаемый drift рабочих копий контрактов.
- .venv/bin/python -m py_compile для затронутых модулей — успешно.
- git diff --check — успешно.

Дополнительный correction-cycle прогон:

- новые и изменённые проверки Settings Center — 7 passed;
- structural-writer regression — 1 passed;
- проверены selector fallback/fail-closed, generic raw deny,
  superuser critical expansion, delegated critical scope/targets и
  отсутствие публичного transport API.

## Остатки

- Рабочие копии data/contracts/ напрямую не изменялись; если новый ключ
  требуется в runtime, его следует перенести через Settings Center
  preview/apply/CAS/audit.
- Полный общий прогон не выполнялся в этом изолированном цикле; параллельный
  пакет 16 продолжает менять соседние модули.
