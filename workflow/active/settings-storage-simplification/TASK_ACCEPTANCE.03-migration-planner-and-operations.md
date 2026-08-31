# Приёмка пакета 03: миграция и операции

Статус: **Accepted**  
Дата: 2026-08-31

## Принятый результат

- read-only plan классифицирует legacy drift без записи и не выбирает уже
  активные DB-документы;
- apply требует PostgreSQL, активного superuser, явного полного среза и
  защищённого backup-root;
- импортируется только подтверждённый audit-историей override; default/missing
  остаются no-op, неоднозначные и security-состояния закрывают весь срез;
- backup и export имеют проверяемые manifest/hash и не перезаписывают
  существующее операторское доказательство;
- source/default/audit перепроверяются перед каждым INSERT и перед commit,
  транзакция откатывает весь многодокументный срез;
- raw secrets, включая acronym, compact и nested-варианты, запрещены единым
  gate; health не раскрывает payload, пути, URL или тексты исключений;
- Windows mutation закрыта отказом, stdout-plan остаётся доступным.

## Доказательства

- `make verify-fast` по registry/repository/migration/health/pilot:
  112 passed, 2 skipped, 19 subtests passed;
- профиль контрактов: 52 passed;
- профиль развёртывания: 29 passed;
- `makemigrations --check --dry-run`: No changes detected;
- `validate_architecture_contracts`, `compileall`, `git diff --check`: успешно.

## Независимая проверка

Luna xhigh выполнила три read-only цикла. Найденные проблемы lock/source TOCTOU,
Windows, секретов, malformed legacy, backend guard, атомарности среза, health и
операторских доказательств исправлены. Итоговый verdict — **approve**.

## Остаточный риск

Гарантия рассчитана на portal writers, использующие общий lock, и защищённый
runtime-каталог. Прямое вмешательство процессом того же service account не может
быть атомарно связано с PostgreSQL и считается нарушением freeze. Production
apply этим пакетом не выполнялся.
