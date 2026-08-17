# Executor report: settings authority hardening (17b-A)

## Сделано

- В `contracts/role_rules.json` и JSON Schema добавлена критическая capability
  `manage_settings`; в дефолте она включена только у роли `admin`, у остальных
  ролей выключена.
- `is_staff` больше не является продуктовым полномочием Центра настроек.
  `can_manage_settings()` повторно читает активную учетную запись и разрешает
  только active superuser либо активного участника роли с
  `manage_settings`.
- Дескрипторы продуктовых runtime-настроек используют `manage_settings`, а
  учетные записи сохраняют отдельное `manage_users` для superuser-only пути.
  Registry проверяет закрытый набор permission names и обязательные
  `settings_path`/`validator` для editable runtime-дескрипторов.
- Preview контрактов теперь принимает actor и проходит ту же проверку, что и
  apply. Неизвестный `required_permission` закрывается явно, без fallback на
  Django `has_perm`.
- `create_env_proposal()` повторно проверяет свежего активного актора и
  `manage_settings` непосредственно в сервисе.
- Авторинг навыков ИИ удалил отдельный Django permission bypass, повторно
  проверяет активность и `manage_ai_skills` под общим lock, пишет через
  уникальный временный файл в целевом каталоге и выполняет `os.replace`;
  незавершённые временные файлы этого формата учитываются при повторной записи.
- `memory.source.acl_mode` исключён из реестра: это не самостоятельный
  контракт, а параметр источника, редактируемый в составе
  `memory.contract.sources`; таким образом Settings Center не пытается читать
  несуществующий файл без `settings_path`.
- Добавлены регрессионные проверки для staff-only, роли admin без staff,
  inactive actor, неизвестного permission, прямого env-сервиса и полного
  списка editable descriptor validators.

## Editable runtime-дескрипторы и валидаторы

| Дескриптор | Валидатор |
|---|---|
| `core.contract.role_rules` | `validate_role_rules_payload` |
| `core.contract.workflow_rules` | `validate_workflow_rules_payload` |
| `workorders.contract.status_colors` | `validate_workorder_status_colors_payload` |
| `ai.contract.registry` | `validate_ai_registry_payload` |
| `ai.contract.tools` | `validate_ai_tools_payload` |
| `ai.contract.task_types` | `validate_ai_task_types_payload` |
| `ai.contract.chat_settings` | `validate_ai_chat_settings_payload` |
| `memory.contract.sources` | `validate_memory_sources_payload` |
| `memory.contract.profiles` | `validate_memory_profiles_payload` |
| `memory.contract.routing` | `validate_memory_routing_payload` |
| `memory.contract.trust_policy` | `validate_memory_trust_policy_payload` |
| `memory.contract.claims_policy` | `validate_memory_claims_policy_payload` |
| `memory.contract.retrieval_budget` | `validate_memory_retrieval_budget_payload` |
| `memory.contract.ingestion_profiles` | `validate_memory_ingestion_profiles_payload` |
| `memory.contract.file_organization_profiles` | `validate_memory_file_organization_profiles_payload` |
| `memory.contract.graph_schema` | `validate_memory_graph_schema_payload` |

## Проверки

- `git diff --check` — успешно.
- `python3 -m compileall` для затронутых Python-файлов — успешно.
- `python manage.py validate_architecture_contracts` — успешно; обнаруженный
  drift рабочих копий не изменялся.
- `SettingsRegistry` загружен: 32 дескриптора, 16 editable runtime-контрактов,
  у каждого разрешимый валидатор и `manage_settings`.
- Запуск выбранного набора pytest был остановлен первым содержательным падением
  вне write scope: общий импорт memory URL получает `ImportError` для
  `recent_knowledge_commits_for_actor` в параллельных незакоммиченных правках
  memory-исполнителя. Тесты повторно не запускались, чтобы не повредить общую
  SQLite test DB.

Runtime `data/contracts/` и Git не изменялись, commit/push не выполнялись.

## Correction 17b-A после независимого ревью

- Ограниченный writer role definitions теперь требует signed preview token и
  выполняет независимую under-lock проверку actor, target role, состава
  участников, impact и направления critical changes после выполнения factory.
  Прямой вызов без signed preview отклоняется.
- `.env` proposal теперь использует общий access-control lock, под ним повторно
  читает active actor и сохраняет именно fresh actor. Добавлен сценарий
  revoke-before-lock.
- Runtime skills используют canonical resolved root, проверяют containment и
  отклоняют существующие symlink для директории навыка и `SKILL.md`.
- `preview_contract_payload` принимает только `actor`, `setting_id` и payload;
  descriptor всегда берётся из canonical registry.
- Registry разрешает имена validators через фактические доменные validator
  functions, без импорта `contract_services`; неизвестный validator отклоняется
  при построении registry.
- Legacy aliases `settings_center.manage` и `settings_center.manage_users`
  удалены; account descriptors переведены на canonical `manage_users`.

### Проверки correction

- Выполнено: `git diff --check`.
- Выполнено: `./.venv/bin/python -m compileall -q apps/settings_center apps/ai/skill_authoring.py apps/accounts/access_contracts.py`.
- Узкий прогон был запущен после сообщения о готовности отдельным от filehub:
  `PYTHONPATH=. ./.venv/bin/pytest -q apps/settings_center/tests.py::ProductSettingsAuthorityTests apps/ai/tests/test_views.py::PendingActionConcurrencyTests::test_skill_authoring_rechecks_active_actor apps/ai/tests/test_views.py::PendingActionConcurrencyTests::test_skill_authoring_rejects_symlinked_target_directory apps/ai/tests/test_views.py::PendingActionConcurrencyTests::test_skill_authoring_rejects_existing_symlinked_skill_file --maxfail=1`.
  Процесс не выдал итогового счётчика и был принудительно остановлен внешним
  прерыванием; повторный запуск запрещён координацией из-за общей SQLite test
  DB и параллельного filehub-контурa. Активного pytest-процесса после проверки
  нет.
