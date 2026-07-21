# Обзор моделей-кандидатов для глубокого слоя обезличивания

Статус: принят к сведению, входные данные для проработки ADR-0012.

Дата: 2026-07-13.

Назначение: анализ модели `openai/privacy-filter`, обзор альтернатив и оценка применимости в контуре обезличивания проекта (ADR-0012, план `docs/planning/active/data-anonymization-privacy-pipeline.md`). Документ фиксирует кандидатов в «глубокий слой» распознавания и рекомендуемую роль каждого. Решение о составе распознавателей принимается после eval-пилота и фиксируется обновлением ADR-0012.

## 1. Метод проверки

Факты о модели `openai/privacy-filter` проверены по нескольким независимым источникам: карточка модели и API Hugging Face, публикации MarkTechPost и VentureBeat, практический обзор (Medium/Data Science Collective), документация huggingface/transformers. Данные об альтернативах — по карточкам моделей и статье GLiNER2-PII (arXiv 2605.09973). Полный список источников — в конце документа.

## 2. Модель openai/privacy-filter — проверенные факты

Выпущена OpenAI 17–28 апреля 2026 года.

- **Назначение:** локальная детекция и маскирование PII в тексте (token classification), высокопроизводительная санитизация данных on-premise.
- **Архитектура:** двунаправленный token-классификатор из линейки gpt-oss: 8 блоков, d_model=640, grouped-query attention, MoE со 128 экспертами и top-4 маршрутизацией; **1.5 млрд параметров всего, ~50 млн активных на инференсе**; ленточное внимание (эффективный локальный контекст ~257 токенов), окно до 128k токенов.
- **Обучение:** авторегрессивное предобучение -> конверсия в двунаправленный классификатор -> supervised post-training на размеченных PII-данных.
- **Категории (8):** `account_number`, `private_address`, `private_email`, `private_person`, `private_phone`, `private_url`, `private_date`, `secret`; схема BIOES, 33 выходных класса.
- **Декодер:** Витерби с ограничениями; 6 настраиваемых смещений переходов позволяют смещать баланс точность/полнота на рантайме без переобучения.
- **Поставка:** Apache 2.0; safetensors + ONNX (включая квантованные Q4/Q4F16); работает через transformers, transformers.js (WebGPU) и onnxruntime на CPU; заявлено data-efficient дообучение.
- **Ограничения (из карточки):** «Primarily English»; деградация на не-английском тексте и **не-латинских алфавитах**; недодетекция редких имен и региональных схем именования; пере-редактирование публичных сущностей; пропуск нестандартных форматов секретов; ложные срабатывания на безобидных высокоэнтропийных строках. Численных бенчмарков в карточке нет; заявление о SOTA на PII-Masking-300k «с исправленной разметкой» независимый обзор ставит под сомнение.
- **Практический обзор (Medium):** модель быстрая на CPU и удобна локально, но 8 категорий — узкое покрытие для production без доработки; замены/псевдонимизации в модели нет — только детекция спанов (для нашего контура это плюс: трансформации остаются за политикой проекта).

## 3. Текущее состояние контура в проекте

- Быстрый слой реализован: `apps/memory/deidentification.py` — 8 regex-распознавателей RU-профиля (EMAIL, PHONE, DATE, SNILS, PASSPORT, POLICY, PATIENT_ID, RU_FULL_NAME), HMAC-псевдонимизация, слияние пересекающихся спанов; `apps/memory/security.py` (`CredentialGuard`) — блокировка секретов.
- Глубокого слоя нет; `contracts/privacy/` не создан; ML-зависимостей (transformers/onnxruntime/spacy) в `requirements.txt` нет.
- Целевой контур описан в ADR-0012: быстрый слой всегда, глубокий — по профилю за feature flag; владелец политики — `apps.memory`; в MVP обязательны границы `before_external_export` и `before_cloud_llm`; режимы `off -> observe -> warn -> redact/pseudonymize -> block/review`; fail closed для чувствительного.

## 4. Кандидаты в глубокий слой

| Кандидат | Тип | Русский язык | Сильные стороны | Слабые стороны |
|---|---|---|---|---|
| `openai/privacy-filter` | NER 1.5B/50M акт., 8 категорий | **Нет** (англ.; не-латиница деградирует) | CPU/ONNX Q4, категория `secret`, баланс точность/полнота на рантайме, 128k контекст, Apache 2.0 | Узкая таксономия; RU-пробел; только детекция |
| GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`) | NER 0.3B, 42 типа, таксономия задается списком меток без переобучения | **Нет** (en/fr/es/de/it/pt/nl) | Гибкая таксономия; в бенчмарке SPY авторов обходит privacy-filter (avg F1 0.477 против 0.380); Apache 2.0 | Молодая экосистема (библиотека `gliner2`); RU не заявлен |
| Piiranha v1 (`iiiorg/piiranha-v1-detect-personal-information`) | NER на mdeberta-v3-base, 17 типов | **Нет** заявленного (6 языков); многоязычная база — кандидат на RU-дообучение | Компактная; высокая точность на поддерживаемых языках | RU не заявлен; фиксированная таксономия |
| Microsoft Presidio | Framework: regex + подключаемый NER-движок + валидаторы + анонимайзеры | **Через подключаемый движок** (spaCy `ru_core_news_lg`, Stanza ru, любой transformers-NER) | Активно развивается (v2.2.362, 2026); расширяемость; уже заложен в ADR-0012 как адаптер | Из коробки RU нет; качество = качество подключенной RU-модели |
| Natasha/Slovnet | RU-специфичный NER (PER/LOC/ORG), CPU | **Да, родной** | Лучший легкий RU NER; локальный, без GPU; подходит как движок для Presidio-адаптера | Только 3 типа сущностей — покрывает ФИО/адреса/организации, не PII-таксономию |
| DeepPavlov `ner_rus_bert` | RU NER (RuBERT + CRF) | **Да** | Качество RU NER | Тяжелая зависимость; тоже только базовые типы |

**Ключевой факт:** ни одна готовая открытая PII-модель не заявляет поддержку русского языка. Для свободного русского текста рабочая схема — связка Presidio-совместимого адаптера с RU-NER-движком (Natasha/Slovnet или spaCy `ru_core_news_lg`) плюс доменные RU/med распознаватели проекта. Это совпадает с планом ADR-0012.

## 5. Оценка применимости privacy-filter

Применима **ограниченно: как дополнительный распознаватель глубокого слоя, а не как его основа**.

1. Основной корпус проекта — русский медицинский. Категории `private_person`, `private_address`, `private_date` на кириллице будут работать хуже заявленного (прямое предупреждение карточки о не-латинских алфавитах). RU-сущности (СНИЛС, паспорт, полис, ФИО) уже покрыты быстрым слоем и целевой связкой Presidio+RU-NER.
2. Реальная ценность сейчас — формато-подобные и латинские сущности даже в русском тексте: `secret`, `account_number`, `private_email`, `private_url`, `private_phone` (ключи API, логины, почта, ссылки, номера). Это второй независимый слой поверх `CredentialGuard` на границах выхода (`before_cloud_llm`, `before_external_export`) — «defense in depth» из ADR-0012 §9 при низкой цене инференса (50M активных параметров, ONNX Q4, CPU).
3. Как эталон для eval: прогон синтетического корпуса в режиме `observe` дает дешевое измерение пропусков быстрого слоя без включения модели в боевой путь.
4. Дообучение на RU заявлено как data-efficient (Apache 2.0 позволяет), но англоцентричное предобучение делает это исследовательской ставкой. Для RU-дообучения перспективнее многоязычные базы (mdeberta у Piiranha, GLiNER2). В план как обязательный шаг не закладывать.
5. Ресурсно проходит «практичный production-минимум» ADR-0012 (4 vCPU/16 GB): квантованный ONNX-вариант — сотни МБ (полный репозиторий модели ~17.4 GB содержит все варианты весов; скачивается только нужный; точный размер проверить при загрузке).

## 6. Рекомендуемые роли кандидатов

- **Быстрый слой (есть):** regex + HMAC (`deidentification.py`), `CredentialGuard` — всегда включен, RU-идентификаторы с фиксированным форматом.
- **Глубокий слой, основная RU-детекция:** Presidio-совместимый адаптер + RU-движок (Natasha/Slovnet или spaCy `ru_core_news_lg`) + доменные RU/med распознаватели — главный кандидат на свободный русский текст.
- **Глубокий слой, дополнительная детекция:** `openai/privacy-filter` (ONNX, CPU) — секреты и латинские/формато-подобные PII на границах выхода; режим `observe` до подтверждения качества.
- **Глубокий слой, кандидат на замену/расширение:** GLiNER2-PII — гибкая таксономия (42 типа); включить в eval-прогон наравне с privacy-filter.
- **Резерв для RU-дообучения:** Piiranha (mdeberta-база) — если eval покажет недостаточность связки Presidio+RU-NER.

## 7. Предложение по встраиванию (в терминах ADR-0012)

1. **Контракт и каркас без ML-зависимостей:** `contracts/privacy/anonymization_profiles.json` + JSON Schema; оркестратор `apps/memory/privacy_pipeline/` с реестром распознавателей `{id, engine, entity_types, languages, thresholds}`, `engine ∈ {regex_fast, credential_guard, privacy_filter_onnx, presidio, gliner}`. Быстрый слой подключается как первые два engine без изменения поведения.
2. **Адаптер privacy-filter за feature flag:** `recognizers/privacy_filter_onnx.py`, onnxruntime CPU, ленивый импорт, выключен по умолчанию. Зависимости — в отдельном `requirements-privacy.txt` (по образцу `services/agent_runtime/requirements.lock`), не в основном runtime. Веса модели — в приватном deployment-контуре (`deployments/<host>/models/`), не в репозитории.
3. **Слияние спанов по приоритету:** `CredentialGuard block` > `privacy_filter secret` > regex > NER; трансформации (redact/HMAC-псевдоним) выполняют только операторы проекта. Fail closed для чувствительных целей.
4. **Включение в `observe` на двух границах MVP:** `before_cloud_llm`, `before_external_export`; только findings в audit/eval, текст не меняется.
5. **Eval до любого enforce:** команда вида `manage.py memory_privacy_eval --dry-run`; синтетический RU/EN корпус (PII + secret bait); отчеты в `data/memory/eval/`; метрики precision/recall по типам сущностей на каждый engine; сравнение: быстрый слой / +privacy-filter / +Presidio-RU / +GLiNER2-PII.
6. **Формализация:** по итогам пилота обновить ADR-0012 (состав распознавателей глубокого слоя), обновить `.desc.json` и `PROJECT_STRUCTURE.yaml`, вести задачу через `docs/planning/backlog.md`.

Чего не делать: не назначать privacy-filter владельцем политики; не включать `detect_and_redact` на индексирование памяти до приемки качества; не считать модель решением для русских ФИО/адресов; не добавлять transformers в основной runtime (ONNX-путь развязывает версии).

## 8. Риски

- Качество privacy-filter на кириллице не подтверждено численно — обязателен собственный eval до enforce.
- Категории модели уже, чем потребности проекта: RU-специфичные сущности остаются за быстрым слоем и Presidio/доменными распознавателями.
- Пере-редактирование публичных сущностей (организации, локации) — риск ложных срабатываний в справочных текстах; парируется режимом `observe` и порогами.
- Новая тяжелая зависимость (onnxruntime) — держать вне основного runtime, в отдельном наборе зависимостей/privacy-worker.
- GLiNER2-PII — молодая экосистема; проверять стабильность библиотеки перед production.

## 9. Источники

- Карточка модели: https://huggingface.co/openai/privacy-filter
- MarkTechPost (2026-04-28): https://www.marktechpost.com/2026/04/28/openai-releases-privacy-filter-a-1-5b-parameter-open-source-pii-redaction-model-with-50m-active-parameters/
- VentureBeat: https://venturebeat.com/data/openai-launches-privacy-filter-an-open-source-on-device-data-sanitization-model-that-removes-personal-information-from-enterprise-datasets
- Практический обзор: https://medium.com/data-science-collective/pii-detection-with-openais-privacy-filter-a-hands-on-review-48b7e3d1b5c4
- Документация transformers: https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/openai_privacy_filter.md
- GLiNER2-PII (arXiv 2605.09973): https://arxiv.org/abs/2605.09973
- fastino/gliner2-privacy-filter-PII-multi: https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi
- urchade/gliner_multi_pii-v1: https://huggingface.co/urchade/gliner_multi_pii-v1
- iiiorg/piiranha-v1: https://huggingface.co/iiiorg/piiranha-v1-detect-personal-information
- Microsoft Presidio, языки и NLP-движки: https://microsoft.github.io/presidio/tutorial/05_languages/ , https://microsoft.github.io/presidio/analyzer/customizing_nlp_models/
- Natasha NER: https://natasha.github.io/ner/
