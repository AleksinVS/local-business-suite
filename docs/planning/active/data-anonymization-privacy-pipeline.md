# Active plan: система обезличивания данных и управляемые настройки

Статус: черновик, требует проработки.

Дата: 2026-05-26.

Этот документ является черновиком. Он фиксирует предварительную модель реализации, настройки и порядок внедрения системы обезличивания. Перед началом разработки нужно уточнить пилотные источники, целевые системы, формат контрактов, нагрузку, критерии качества распознавания и требования к интерфейсу Settings Center.

## Цель

Реализовать управляемую систему обезличивания данных, которую можно включать постепенно:

- сначала только на границах выхода данных во внешние системы;
- затем в режиме наблюдения для индексации памяти;
- затем выборочно для отдельных источников;
- позже для OCR, графа, аналитики и экспортных пакетов.

Система должна позволять прозрачно управлять уровнем обработки по источнику, типу данных, целевой системе и этапу обработки.

## Контекст

Связанные документы:

- `docs/adr/ADR-0012-data-anonymization-and-privacy-pipeline.md`;
- `docs/architecture/PRIVACY_DEEP_LAYER_MODELS_REVIEW_2026-07-13.md` — обзор моделей-кандидатов глубокого слоя;
- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `contracts/ai/memory_routing.json`;
- `contracts/ai/memory_ingestion_profiles.json`;
- `docs/planning/archive/2026/settings-center-gui.md`.

Текущие реализации, которые нужно переиспользовать:

- `apps.memory.deidentification`;
- `apps.memory.security`;
- `apps.memory.document_ingestion`;
- `apps.memory.settings_descriptors`;
- `apps.ai.tooling` для внешних LLM/tool-вызовов;
- audit и issue/review queue в `apps.memory`.

## Принципы

- Не включать обезличивание глобально для всех данных.
- Сначала защищать внешние границы: cloud LLM, external API, export package.
- Для новых источников сначала использовать `observe`, затем `warn`, затем принудительную обработку.
- Тяжелые распознаватели не должны попадать в горячий пользовательский путь.
- Псевдонимизация не считается полной анонимизацией.
- Секреты блокируются или заменяются handle, но исходные значения не пишутся в audit.
- Все runtime-настройки валидируются и сохраняются атомарно.

## Модель настроек

Добавить контракт:

```text
contracts/privacy/anonymization_profiles.json
contracts/schemas/anonymization_profiles.schema.json
```

Runtime-копия:

```text
data/contracts/privacy/anonymization_profiles.json
```

Черновая структура:

```json
{
  "version": "0.1-draft",
  "profiles": {
    "external_mvp_redact_v1": {
      "mode": "detect_and_redact",
      "recognizer_stack": ["secrets_v1", "regex_ru_pii_v1"],
      "entities": ["EMAIL", "PHONE", "RU_FULL_NAME", "SNILS", "PASSPORT", "POLICY"],
      "on_low_confidence": "review",
      "on_detector_unavailable": "block",
      "audit_original_values": false
    }
  },
  "routes": [
    {
      "id": "chat_to_cloud_llm_mvp",
      "enabled": true,
      "rollout_state": "pilot",
      "source_kind": "chat",
      "source_code": "*",
      "data_type": "free_text",
      "target": "cloud_llm",
      "stage": "before_cloud_llm",
      "profile": "external_mvp_redact_v1",
      "priority": 100
    }
  ]
}
```

Обязательные оси маршрутизации:

- `source_kind`;
- `source_code`;
- `data_type`;
- `target`;
- `stage`;
- `profile`;
- `mode`;
- `enabled`;
- `rollout_state`;
- `priority`;
- `fallback`.

Этапы pipeline:

- `before_external_export`;
- `before_cloud_llm`;
- `before_memory_index`;
- `before_graph_extract`;
- `before_analytics_export`;
- `before_audit_log_write`.

Режимы:

- `off`;
- `observe`;
- `warn`;
- `detect_and_redact`;
- `stable_pseudonym`;
- `generalize`;
- `suppress`;
- `review`;
- `block`.

## Архитектурные компоненты

### Контракты и загрузка

Добавить:

- schema для `anonymization_profiles.json`;
- загрузчик runtime/default contracts;
- валидацию ссылок между `routes` и `profiles`;
- проверку совместимости с `memory_routing.json`;
- dry-run resolver, который показывает, какой профиль будет применен для конкретного source/target/stage.

### Privacy pipeline

Добавить `apps.memory.privacy_pipeline`.

Ответ pipeline должен содержать:

- исходный `request_id`;
- примененный `profile_id`;
- примененный `route_id`;
- `stage`;
- `mode`;
- `decision`: `allowed`, `modified`, `review_required`, `blocked`;
- `safe_text` или safe structured payload;
- список findings без исходных значений;
- fingerprints;
- counters;
- reasons и warnings;
- profile version.

### Распознаватели

Первый слой:

- текущий `CredentialGuard`;
- текущие regex из `deidentification.py`;
- новые cheap validators для русских и бизнес-идентификаторов.

Следующие слои (кандидаты по обзору 2026-07-13, см. `docs/architecture/PRIVACY_DEEP_LAYER_MODELS_REVIEW_2026-07-13.md`):

- Presidio-compatible adapter с RU-движком (Natasha/Slovnet или spaCy `ru_core_news_lg`) — основная детекция свободного русского текста;
- `openai/privacy-filter` (ONNX, CPU, за feature flag) — дополнительный распознаватель секретов и латинских/формато-подобных PII на границах `before_cloud_llm` и `before_external_export`, сначала в режиме `observe`;
- GLiNER2-PII — кандидат на гибкое расширение таксономии, участник eval-прогона;
- медицинские и бизнес-распознаватели;
- OCR quality checks.

Зависимости глубокого слоя не добавляются в основной `requirements.txt`: отдельный набор зависимостей (по образцу `services/agent_runtime/requirements.lock`) и/или `privacy-worker`. Веса моделей хранятся в приватном deployment-контуре, не в репозитории.

### Audit и issue queue

Нужен журнал обработки:

```text
PrivacyProcessingAudit
  request_id
  source_kind
  source_code
  data_type
  target
  stage
  profile_id
  route_id
  mode
  decision
  findings_count
  blocked_reason
  profile_version
  created_at
```

Журнал не должен хранить исходные PII или secret values.

### Settings Center

Через Settings Center нужно дать управляемый интерфейс:

- список профилей;
- список маршрутов;
- включение/выключение маршрута;
- перевод `rollout_state`;
- выбор режима из разрешенного списка;
- просмотр dry-run preview на синтетическом тексте;
- проверка контракта перед сохранением;
- audit изменений настроек.

Запрещено показывать реальные PII и секреты в настройках, preview и audit.

## Поэтапная реализация

### Этап 0. Проработка черновика

Цель: подготовить реализацию без изменения runtime-поведения.

Работы:

- уточнить список пилотных источников;
- выбрать первые целевые системы;
- согласовать entity types;
- согласовать fallback для внешних систем;
- подготовить синтетический eval corpus;
- утвердить формат contract/schema;
- уточнить, какие настройки нужны в Settings Center на первом срезе.

Критерий завершения: ADR и план готовы к переводу из черновика в принятый статус.

### Этап 1. MVP на внешних границах

Цель: защитить только данные, уходящие во внешние системы.

Включить:

- `before_cloud_llm`;
- `before_external_export`.

Реализовать:

- контракт профилей;
- resolver маршрутов;
- privacy pipeline для plain text;
- secret block;
- PII redact;
- audit без исходных значений;
- dry-run management command.

Не включать:

- обработку всех документов перед индексом;
- OCR;
- Presidio/NER;
- сложный risk scoring;
- Settings Center редактирование, кроме read-only descriptors, если оно дешевое.

### Этап 2. Наблюдение перед памятью

Цель: оценить качество на реальных источниках без изменения индекса.

Включить:

- `before_memory_index` в режиме `observe`;
- только для выбранных `source_code`;
- issue/warning по рискованным документам.

Результат:

- статистика findings;
- список false positive/false negative;
- понимание, где требуется глубокий слой;
- корректировка recognizer rules.

### Этап 3. Пилотная обработка по источникам

Цель: начать реальную замену данных для ограниченных источников.

Включить:

- `detect_and_redact` или `stable_pseudonym`;
- только для утвержденных source/target/stage;
- review для низкой уверенности.

Начальные кандидаты:

- подготовленная тестовая папка документов;
- ограниченные внешние export packages;
- отдельные источники чата при cloud routing;
- безопасные bootstrap packages.

### Этап 4. Глубокий слой и worker

Цель: улучшить качество без перегрузки основного приложения.

Реализовать:

- Presidio-compatible adapter за feature flag;
- RU/medical/business recognizer registry;
- background processing;
- `privacy-worker` для тяжелых задач;
- лимиты CPU/RAM/timeouts;
- повторные попытки и dead-letter для задач.

### Этап 5. Таблицы, аналитика и экспорт

Цель: покрыть structured datasets и отчеты.

Реализовать:

- column classification;
- direct/quasi/sensitive attribute classification;
- обобщение дат и возрастов;
- подавление малых групп;
- risk scoring для rare combinations;
- отдельные профили для external reports.

### Этап 6. Settings Center и эксплуатация

Цель: дать прозрачное управление без редактирования JSON вручную.

Реализовать:

- UI для profiles/routes;
- dry-run preview;
- audit изменений;
- роли `privacy_view`, `privacy_edit`, `privacy_approve`;
- workflow утверждения risky profile changes;
- операторский guide.

## Критерии приемки MVP

- Контракт профилей валидируется.
- Для `before_cloud_llm` можно определить профиль по source/target/stage.
- PII в synthetic text редактируется перед внешней передачей.
- Secret-like content блокируется или заменяется handle по политике.
- Audit содержит типы и счетчики findings, но не исходные значения.
- Если обязательный detector недоступен, внешняя передача блокируется.
- В режиме `observe` текст не меняется, но audit/eval записывается.
- Unit tests покрывают resolver, pipeline modes и fail-closed behavior.
- Есть dry-run команда для проверки маршрута и результата.

## Проверки

Черновой список:

```bash
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests
./.venv/bin/python manage.py memory_eval --dry-run
```

После появления команды privacy eval:

```bash
./.venv/bin/python manage.py memory_privacy_eval --dry-run
```

Для крупного блока реализации нужен e2e-сценарий:

```text
chat/external payload
  -> privacy route resolution
  -> redaction/block
  -> external-boundary call denied or sanitized
  -> audit without raw PII
```

## Риски и открытые вопросы

- Какие external targets включаются в первый MVP.
- Какие источники считать пилотными.
- Какой минимальный набор entity types нужен до production.
- Нужна ли отдельная модель `PrivacyProcessingAudit` или достаточно расширить текущий audit слой.
- Какие настройки редактировать через Settings Center на первом срезе.
- Какие роли утверждают risky profile changes.
- Как проводить ручную проверку без показа лишних PII.
- Какой допустимый уровень false positives для блокировки внешних передач.

## Не входит в первый MVP

- Полная обработка всех корпоративных документов.
- Production OCR/NER.
- Полная анонимизация всех аналитических витрин.
- Облачная обработка чувствительных документов.
- Автоматическое принятие risky profile changes.
- Перенос secret backend.
