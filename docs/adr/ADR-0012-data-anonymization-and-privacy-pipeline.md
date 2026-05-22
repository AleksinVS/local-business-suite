# ADR-0012: Надежное обезличивание данных и контур приватности

## Статус

Proposed

## Дата

2026-05-22

## Контекст

Проект обрабатывает данные из нескольких источников:

- пользовательские и агентные чаты;
- корпоративные документы из local/UNC источников;
- внешние информационные системы;
- заявки, оборудование, аналитические факты и будущие email-источники;
- безопасные пакеты для bootstrapping схемы графа знаний.

В текущей архитектуре уже есть базовый контур приватности:

- `apps.memory.deidentification` выполняет регулярное распознавание PII и HMAC-псевдонимизацию;
- `apps.memory.security` блокирует или отделяет секреты;
- `contracts/ai/memory_routing.json` запрещает попадание original PII и secret в LLM-контекст;
- `contracts/ai/memory_ingestion_profiles.json` задает ingestion-профили, raw mode, ACL-политику и issue queue;
- `memory.search` возвращает только данные после проверки прав, sensitivity, надежности источника и audit.

Этого достаточно для MVP, но недостаточно для надежной промышленной анонимизации. Простое удаление ФИО, телефона и email не защищает от повторной идентификации через редкие сочетания признаков: должность, отдел, дату, событие, номер заявки, путь файла, медицинский контекст или уникальное описание инцидента.

Также важно различать:

- **редактирование** - удаление или замена конкретного фрагмента текста;
- **псевдонимизацию** - стабильная замена идентификатора на псевдоним с сохранением возможности связывать записи;
- **анонимизацию/обезличивание** - снижение риска идентификации до приемлемого уровня для конкретной цели, получателя и модели угроз.

Псевдонимизированные данные не должны считаться полностью анонимными внутри проекта, если сохраняется ключ, salt, таблица соответствий или иная дополнительная информация для восстановления связи с человеком.

## Решение

Создать многоступенчатый контур обезличивания как часть governance-first памяти, а не как отдельный внешний продукт-владелец данных.

Базовый путь обработки:

```text
source/document/api/chat
  -> source classification and sensitivity
  -> parser/OCR to normalized blocks
  -> secret/DLP hard gate
  -> deterministic fast recognizers
  -> Presidio-compatible PII analyzer adapter
  -> project-specific RU/medical/business recognizers
  -> span merge and confidence scoring
  -> transform policy: redact / pseudonymize / generalize / suppress / block
  -> re-identification risk checks
  -> review queue for risky or uncertain cases
  -> safe corpus / knowledge files / indexes / graph
  -> retrieval policy, citations, audit and eval
```

### 1. Оставить Django владельцем политики

`apps.memory` остается владельцем:

- политик приватности;
- audit;
- issue/review queue;
- sensitivity routing;
- source trust;
- связи safe data с исходным объектом;
- запрета на передачу sensitive/original PII в LLM-контекст.

Внешние библиотеки и сервисы используются только как распознаватели, парсеры, OCR или технические backend-компоненты. Они не становятся источником истины для политик проекта.

### 2. Ввести профильный контракт обезличивания

Добавить на этапе реализации контракт:

```text
contracts/privacy/anonymization_profiles.json
contracts/schemas/anonymization_profiles.schema.json
```

Минимальные сущности контракта:

- `profile_id`;
- применимые источники и типы объектов;
- список распознаваемых entity types;
- пороги уверенности;
- правила объединения пересекающихся spans;
- действия по умолчанию: `redact`, `stable_pseudonym`, `generalize`, `suppress`, `block`;
- правила для дат, адресов, редких должностей и малых групп;
- режим работы с cloud/export package;
- требования к ручной приемке;
- версия профиля и совместимость с `memory_routing.json`.

Runtime-редактируемые копии должны храниться в `data/contracts/privacy/`, как остальные runtime-контракты.

### 3. Разделить контур на быстрый и глубокий слой

Быстрый слой работает всегда:

- регулярные выражения;
- контрольные суммы и валидаторы форматов;
- HMAC-псевдонимы;
- словари доменных маркеров;
- deny/allow lists;
- блокировка секретов;
- cheap heuristics для путей файлов, учетных записей, номеров договоров, заявок и оборудования.

Глубокий слой включается по профилю:

- Presidio-compatible analyzer;
- NER-модели для русского и английского языка;
- медицинские и бизнес-распознаватели проекта;
- OCR quality checks;
- поиск косвенных идентификаторов;
- risk scoring для повторной идентификации.

Если глубокий слой недоступен, профиль должен явно определить поведение. Для чувствительных данных режим по умолчанию: fail closed, то есть блокировать или отправлять в review queue, а не индексировать.

### 4. Использовать HMAC-псевдонимизацию, а не простой hash

Стабильные псевдонимы создаются через HMAC с секретом из приватного deployment-контура или vault.

Запрещено считать простой hash надежной анонимизацией для низкоэнтропийных значений:

- телефонов;
- email;
- СНИЛС;
- паспортов;
- номеров полисов;
- табельных номеров;
- patient/workorder identifiers.

Секрет псевдонимизации:

- не хранится в `contracts/`;
- не пишется в audit;
- не попадает в prompt/tool trace;
- поддерживает плановую ротацию;
- может иметь разные области действия: global, source, tenant, export package.

### 5. Отделить псевдонимизацию для памяти от анонимизации для аналитики

Для памяти и поиска нужна связность: один и тот же человек, пациент, пользователь или объект должен получать стабильный псевдоним внутри допустимой области. Это псевдонимизация, а не полная анонимизация.

Для аналитических выгрузок и внешних пакетов нужны дополнительные меры:

- обобщение дат до месяца/квартала/года;
- обобщение возраста или стажа до диапазона;
- подавление малых групп;
- k-anonymity checks для структурированных данных;
- запрет публикации уникальных комбинаций quasi-identifiers;
- differential privacy только для агрегированных отчетов и после отдельного профиля качества.

### 6. Обрабатывать тексты, таблицы и изображения разными стратегиями

Текстовые документы:

- распознавать spans;
- заменять прямые идентификаторы;
- помечать низкую уверенность для review;
- сохранять provenance позиции фрагмента без исходного PII.

Таблицы:

- классифицировать колонки;
- отдельно помечать direct identifiers, quasi-identifiers и sensitive attributes;
- применять column-level и row-level правила;
- проверять малые группы и редкие комбинации.

OCR и изображения:

- считать OCR-output недоверенным до прохождения DLP/PII gates;
- сохранять OCR confidence и issue при плохом качестве;
- не отправлять screenshots и scans в cloud без подготовленного non-sensitive или pseudonymized package.

### 7. Ввести risk review и eval-контур

Надежность подтверждается не только кодом, но и постоянной проверкой.

Обязательные проверки:

- синтетический корпус русских/английских PII-примеров;
- secret bait suite;
- OCR leakage suite;
- regression tests для каждого recognizer;
- ручная выборка false negative/false positive;
- re-identification review для экспортных и аналитических пакетов;
- audit по версии профиля обезличивания.

Runtime eval reports пишутся в `data/memory/eval/`. Временные parser logs, corpus manifests и локальные эксперименты пишутся только в `.local/`.

### 8. Целевая изоляция исполнения

MVP может выполняться внутри Django/management commands.

Целевая production-схема для тяжелой обработки:

```text
Django app
  -> durable queue
  -> privacy-worker
  -> parser/OCR/NER adapters
  -> safe result envelope
  -> memory writer/indexer
```

`privacy-worker` запускается с минимально необходимыми правами:

- read-only доступ к источнику;
- write-доступ только к рабочей зоне в `data/memory/processing/`;
- отсутствие прямого доступа к бизнес-базам сверх нужных metadata;
- отдельные лимиты CPU/RAM/timeouts;
- отдельный audit выполнения.

## Минимальные требования к ресурсам

### Текстовый MVP без OCR и локальных LLM

- 2 vCPU;
- 4-8 GB RAM;
- SSD;
- SQLite FTS;
- один Django worker или management command.

Подходит для регулярных выражений, HMAC-псевдонимизации, secret scan, небольших документов и тестового ingestion.

### Практичный production минимум

- 4 vCPU;
- 16 GB RAM;
- SSD/NVMe;
- отдельный privacy-worker;
- отдельная рабочая директория под `data/memory/processing/`;
- регулярные eval-прогоны.

Подходит для Presidio-compatible analyzer, NER-моделей, крупных текстовых пакетов и умеренного потока документов.

### OCR/тяжелая обработка документов

- 8 vCPU;
- 32 GB RAM;
- NVMe;
- отдельный диск или раздел под OCR/temp/indexes;
- отдельный worker queue;
- GPU не обязателен для базовой надежной анонимизации, но может понадобиться для локального тяжелого OCR/LLM.

## Альтернативы

### Оставить текущий regex/HMAC MVP

Плюсы:

- минимальная сложность;
- быстро;
- не требует новых зависимостей.

Минусы:

- высокий риск пропуска косвенных идентификаторов;
- слабое покрытие свободного русского текста;
- нет оценки риска повторной идентификации;
- недостаточно для cloud/export package и медицинских нарративов.

Решение: оставить как быстрый слой, но не считать финальной системой.

### Использовать Presidio как основной продукт-владелец

Плюсы:

- готовая модель analyzer/anonymizer;
- поддержка собственных recognizer;
- есть операторы redact/replace/hash/encrypt.

Минусы:

- политики, audit, sensitivity routing и source trust уже принадлежат проекту;
- русские и доменные правила все равно нужно дорабатывать;
- нельзя отдавать внешней библиотеке право решать, что можно индексировать или отправлять агенту.

Решение: использовать Presidio-compatible adapter, но не переносить туда владение политикой.

### Отдельный микросервис анонимизации с сетевым API

Плюсы:

- сильная изоляция;
- проще масштабировать независимо;
- можно ограничить права и ресурсы.

Минусы:

- больше deployment-сложности;
- нужна сетевая защита и собственный audit;
- преждевременно для первого production.

Решение: целевой `privacy-worker` как локальный worker/служба; сетевой сервис рассмотреть позже только при доказанной нагрузке.

### Полная анонимизация перед любым хранением

Плюсы:

- снижает риск хранения персональных данных.

Минусы:

- ломает связность памяти;
- ухудшает поиск, расследование источника и исправление ошибок;
- не всегда возможно для рабочих сценариев, где нужна стабильная связь объектов.

Решение: для памяти применять контролируемую псевдонимизацию и routing; для аналитических/export-сценариев применять более строгие анонимизационные профили.

### Облачная обработка PII

Плюсы:

- высокое качество некоторых OCR/LLM/NER инструментов;
- меньше локальных требований к железу.

Минусы:

- высокий privacy/security риск;
- сложнее доказать отсутствие утечек;
- противоречит текущей локальной модели для чувствительных данных.

Решение: разрешать только для подготовленных non-sensitive или pseudonymized test packages с ручным утверждением.

## Последствия

### Положительные

- Контур обезличивания остается совместимым с текущей memory architecture.
- Надежность растет за счет нескольких независимых слоев обнаружения.
- Псевдонимизация не смешивается с полной анонимизацией.
- Cloud/export-сценарии получают явный риск-контроль.
- Ошибки OCR, parser и NER становятся видимыми через issue/review queue.
- Сохраняется локальный-first подход без обязательного GPU.

### Отрицательные

- Появится новый контракт и дополнительные тесты.
- Нужна настройка русских и доменных recognizer.
- Будут false positives, требующие review.
- Глубокий слой увеличит время ingestion.
- Для надежной оценки риска нужны реальные, но безопасно подготовленные тестовые корпуса.

## Требуемые последующие работы

1. Создать `contracts/privacy/anonymization_profiles.json` и JSON Schema.
2. Добавить `apps.memory.privacy_pipeline` как оркестратор этапов.
3. Выделить интерфейсы `Recognizer`, `AnonymizerOperator`, `RiskAssessor`.
4. Подключить текущие `deidentification.py` и `security.py` как быстрый слой.
5. Добавить Presidio-compatible adapter behind feature flag.
6. Добавить RU/medical/business recognizer registry.
7. Добавить risk scoring для structured datasets и export packages.
8. Добавить management command для eval-прогонов.
9. Добавить документацию в `docs/architecture/`, `docs/guides/` и `docs/deployment/`.
10. Обновить `memory_ingestion_profiles.json` или связать его с новым privacy contract.

## Источники и ориентиры

- NIST SP 800-188, De-Identifying Government Datasets: Techniques and Governance: https://csrc.nist.gov/pubs/sp/800/188/final
- NIST SP 800-226, Guidelines for Evaluating Differential Privacy Guarantees: https://csrc.nist.gov/pubs/sp/800/226/final
- HHS HIPAA de-identification guidance: https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
- EDPS/AEPD hash pseudonymisation paper: https://www.edps.europa.eu/data-protection/our-work/publications/papers/introduction-hash-function-personal-data
- ICO anonymisation and pseudonymisation guidance: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/anonymisation/
- Microsoft Presidio documentation: https://microsoft.github.io/presidio/
