# Task acceptance: автоупорядочивание файловых источников

Дата: 2026-06-02.

## Acceptance status

MVP принят технически и ожидает приемку владельцем.

## Проверенные критерии

- Stable file identity не зависит от `relative_path`.
- Baseline virtual structure создается без изменения физических файлов.
- Incoming worker обрабатывает стабильные файлы и блокирует секреты.
- Виртуальное размещение не обходит scope/access checks.
- Пользователь может создать личное виртуальное размещение для доступного файла через `/memory/files/`.
- Organization proposals создаются только после aggregation thresholds.
- Managed FS transfer выполняет copy/verify/metadata commit/quarantine.
- Purge невозможен без retention и backup checkpoint.
- Контракт `memory_file_organization_profiles` валидируется через `validate_architecture_contracts`.
- UI file organization доступен в контуре review.
- E2E покрывает основной сценарий.

## Остаточный риск

- Реальный пилотный источник еще не выбран.
- Runtime `managed_root`, retention и backup checkpoint должны быть настроены в `data/contracts/ai/` или deployment silo.
- Для production-перехода на S3 нужен отдельный backend implementation и ADR/update.
