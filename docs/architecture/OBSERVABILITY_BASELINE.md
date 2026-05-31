# Базовая наблюдаемость

## Назначение

Документ задает минимальный набор метрик, который нужен до оптимизаций и до обсуждения выноса компонентов в другой стек. Решения о производительности должны опираться на p50/p95, ошибки и объемы, а не на ощущение скорости.

Связанный ADR: `docs/adr/ADR-0024-service-extraction-readiness.md`.

## Что измерять

Минимальные пользовательские сценарии:

- открытие доски заявок;
- открытие правой панели заявки;
- создание или редактирование заявки;
- поиск по памяти через `memory.search`;
- ответ ИИ-чата;
- reconcile source adapters;
- discovery/ingestion документов;
- индексация FTS/vector;
- пересчет аналитических метрик.

Минимальные показатели:

- `p50_ms` - обычная скорость;
- `p95_ms` - хвост медленных случаев;
- `max_ms` - самый медленный случай в выборке;
- `count` - объем выборки;
- `status_codes` - ошибки HTTP или статусы обработки;
- для worker: время ожидания в очереди, время выполнения, число попыток, число dead-letter случаев.

## Встроенный HTTP baseline

В проект добавлен опциональный сбор latency-событий HTTP-запросов.

Включение:

```env
LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED=true
LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE=1.0
LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH=data/logs/performance_events.jsonl
```

По умолчанию сбор выключен, чтобы не добавлять лишнюю запись на диск без явного решения администратора.

Событие пишется в JSONL:

```json
{
  "schema_version": "performance-event-v1",
  "event_type": "http_request",
  "created_at": "2026-05-31T12:00:00+00:00",
  "method": "GET",
  "route_name": "workorders:board",
  "route_pattern": "workorders/",
  "status_code": 200,
  "duration_ms": 124.5,
  "db_query_count": null
}
```

Событие не содержит:

- полный URL;
- query string;
- тело запроса;
- prompt;
- имя пользователя или `user_id`;
- значения форм;
- исходные документы;
- секреты.

Ограничение: для streaming responses middleware измеряет время до возврата HTTP-ответа Django, а не полную длительность передачи stream. Для полного времени ИИ-чата нужен отдельный прикладной замер в `apps.ai` или `services/agent_runtime`.

Исключенные префиксы по умолчанию:

```env
LOCAL_BUSINESS_PERFORMANCE_METRICS_EXCLUDE_PREFIXES=/static/,/media/,/favicon.
```

## Отчет p50/p95

Команда:

```bash
python manage.py performance_report
```

Примеры:

```bash
python manage.py performance_report --group-by route_name --min-count 20
python manage.py performance_report --group-by route_pattern --top 50
python manage.py performance_report --json
```

Формат:

```text
group | count | p50_ms | p95_ms | max_ms | status_codes
workorders:board | 120 | 180.2 | 920.1 | 1400.4 | {'200': 120}
```

## Пороговые ориентиры

Порог не является жестким SLA до пилота, но помогает искать проблемы.

| Сценарий | Начальный ориентир p95 |
| --- | ---: |
| Простая HTML-страница | до 1000 мс |
| Правая панель | до 800 мс |
| Список/доска заявок | до 1500 мс |
| Локальный поиск по памяти без LLM | до 1500 мс |
| ИИ-чат с tool call | измерять отдельно, зависит от модели |
| Ingestion/индексация | измерять batch-временем и временем очереди |

Если p95 превышает ориентир, сначала проверять SQL-запросы, индексы, объем выборки, кэширование и фоновые задачи. Смена языка рассматривается только после этих шагов.

## Хранение и очистка

`performance_events.jsonl` является runtime-логом и хранится в `data/logs/`. Он не коммитится.

Рекомендуемый порядок:

- включать сбор на пилоте или при расследовании;
- использовать sampling меньше 1.0 при большом трафике;
- ротировать или удалять старые файлы вместе с обычными логами;
- не использовать этот файл как постоянный аналитический источник истины.

## Следующие шаги

Отдельными задачами можно добавить:

- p50/p95 для management commands и workers;
- счетчик времени ожидания в очереди;
- экспорт агрегатов в `data/analytics/`;
- staff-only страницу с последним отчетом;
- проверку порогов в smoke-команде.
