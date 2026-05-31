# Операции worker и очередей

## Назначение

Руководство описывает общий эксплуатационный подход к фоновым задачам. Оно не заменяет профильные инструкции памяти, аналитики и deployment, а задает единый минимум для новых worker-контуров.

Связанный ADR: `docs/adr/ADR-0024-service-extraction-readiness.md`.

## Текущий статус

В проекте уже есть несколько очередей и обработчиков:

- `knowledge_writer_worker`;
- `knowledge_index_worker`;
- `knowledge_reflection_worker`;
- `memory_external_worker`;
- `source_adapter_reconcile`;
- команды discovery/ingestion/reindex памяти;
- команды аналитики sync/extract/dedup/recalculate.

Production scheduler/Celery пока не является обязательной частью MVP. Для локального режима допустимы ручной запуск, cron, systemd timer или Windows Task Scheduler. При росте объема можно вводить Celery/Redis отдельным ADR.

## Единый контракт задачи

Новые очереди должны стремиться к такому минимуму:

```json
{
  "schema_version": "queue-job-v1",
  "job_id": "stable-job-id",
  "job_kind": "memory.index",
  "idempotency_key": "source:object:version",
  "status": "queued",
  "priority": 100,
  "attempt_count": 0,
  "max_attempts": 5,
  "run_after": "2026-05-31T12:00:00+03:00",
  "locked_at": null,
  "locked_by": "",
  "source_ref": {
    "source_code": "workorders",
    "object_type": "workorder",
    "object_id": "123"
  },
  "audit_ref": "",
  "error_code": "",
  "error_message": ""
}
```

Если существующая модель уже имеет свой формат, новый код не обязан механически менять ее сразу. Но при расширении очереди нужно добавлять недостающие поля или документировать, почему они не нужны.

## Статусы

Рекомендуемые статусы:

- `queued` - задача ожидает обработки;
- `running` - worker взял задачу;
- `succeeded` - задача завершилась успешно;
- `retry_wait` - задача ждет повторной попытки;
- `failed` - попытки исчерпаны или ошибка неустранима;
- `cancelled` - задача отменена оператором;
- `needs_review` - нужен ручной разбор.

## Идемпотентность

Worker должен безопасно переживать повторный запуск.

Правила:

- повторная обработка того же `idempotency_key` не должна создавать дубли;
- запись результата должна быть атомарной;
- если результат уже актуален, worker завершает задачу как `succeeded`;
- внешние вызовы должны иметь собственный idempotency key, если внешний API это поддерживает;
- частичный результат должен быть видим через issue/review queue, а не скрыт в логе.

## Retry и dead-letter

Повторять можно:

- временную сетевую ошибку;
- timeout внешнего API;
- временную блокировку файла;
- временную ошибку индекса.

Не повторять автоматически:

- отказ прав;
- найденный секрет;
- unsupported format;
- поврежденный или зашифрованный файл;
- ошибку контракта;
- некорректную настройку источника.

После исчерпания попыток задача должна перейти в `failed` или `needs_review` с безопасным `error_code`. Не писать в `error_message` секреты, prompt, полный путь UNC с чувствительным названием или исходный текст документа.

## Запуск

Примеры текущих команд:

```bash
python manage.py knowledge_writer_worker --dry-run
python manage.py knowledge_index_worker --dry-run
python manage.py knowledge_reflection_worker --dry-run
python manage.py memory_external_worker --dry-run
python manage.py source_adapter_reconcile --target memory --dry-run
python manage.py source_adapter_reconcile --target analytics --dry-run
```

Перед production-запуском новой очереди:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py performance_report --help
```

Профильные проверки памяти остаются в `docs/deployment/MEMORY_DEPLOYMENT.md` и `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

## Наблюдаемость

Для каждой очереди желательно иметь:

- число задач по статусам;
- p50/p95 времени ожидания;
- p50/p95 времени выполнения;
- число retry;
- число `needs_review`;
- последние безопасные `error_code`;
- audit-ссылку на пользовательское или системное действие.

Пока нет общего worker metrics storage, эти данные можно получать из моделей конкретного домена и команд статуса.

## Когда вводить отдельный сервис

Отдельный Go/Rust/Python worker имеет смысл, если:

- p95 обработки стабильно неприемлем;
- задача CPU-heavy или требует внешнего runtime;
- задача должна масштабироваться отдельно от Django web;
- сбой worker не должен влиять на портал;
- контракт уже стабилен и покрыт e2e.

Перед выносом создать ADR или обновить существующий ADR, описать deployment и добавить smoke/e2e-команду.
