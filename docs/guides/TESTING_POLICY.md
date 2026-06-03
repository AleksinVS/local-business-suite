# Политика тестирования

Статус: active.

Дата: 2026-05-29.

## Назначение

Документ задает минимальные правила тестирования для изменений в проекте. Цель — проверять не только отдельные функции, но и реальные пользовательские, интеграционные и эксплуатационные сценарии.

Эта политика дополняет:

- `AGENTS.md`;
- `README.md`;
- `pytest.ini`;
- `scripts/e2e/playwright.config.ts`;
- профильные ADR и planning-документы.

## Уровни проверок

### Быстрые проверки

Используются для ранней обратной связи:

```bash
.venv/bin/python manage.py check
.venv/bin/python -m py_compile <changed-python-files>
git diff --check
```

### Unit-тесты

Обязательны для code changes по затронутому scope. Unit-тест должен проверять локальное правило, сервис, валидатор, policy или преобразование данных без зависимости от браузера и внешнего LLM.

Примеры:

```bash
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
```

Для локального повторного запуска без пересоздания тестовых баз используйте штатный Django-режим `--keepdb`:

```bash
make test-fast
make test-fast TEST_SCOPE=apps.ai.tests
make test TEST_SCOPE=apps.ai.tests
```

`test-fast` не снижает покрытие сам по себе: он запускает тот же набор тестов, но переиспользует уже созданные тестовые базы и создает их заново только при отсутствии. Выборочный `TEST_SCOPE` нужен для быстрой обратной связи по затронутому приложению; перед завершением крупной или рискованной работы нужен полный прогон `make test` или `make test-fast` без `TEST_SCOPE`.

### Integration-тесты

Нужны, когда изменение проходит через несколько компонентов: Django view, service layer, tool gateway, контракты, память, индекс, audit или runtime wrapper.

Integration-тест должен проверять фактическую связку компонентов, а не повторять внутреннюю реализацию.

### E2E-тесты

Для крупных блоков разработки обязателен e2e-сценарий через один из рабочих контуров:

- HTTP/UI через Django Client или Playwright;
- management command, если проверяется фоновый или файловый контур;
- API/tool gateway, если пользовательский путь реализован как инструментальный workflow.

Playwright-артефакты и временные логи должны оставаться в `.local/`.

```bash
npm run test:e2e -- --project=chromium
```

### Контрактные проверки

Обязательны при изменении `contracts/`, AI tools, task types, runtime-настроек, role/workflow rules, memory profiles и source contracts.

```bash
.venv/bin/python manage.py validate_architecture_contracts
```

## Матрица обязательных проверок

| Тип изменения | Минимальные проверки |
| --- | --- |
| Django model/service/policy/view | `manage.py check`, unit-тесты затронутого приложения |
| AI tool или task type | unit/integration для `apps.ai`, runtime wrapper test, contract validation |
| Agent runtime prompt/tools/MCP | `services.agent_runtime` tests, gateway integration where applicable |
| Контракты в `contracts/` | contract validation, targeted tests for consumers |
| Память, ingestion, FTS/vector | memory unit/integration, e2e command or equivalent management-command scenario |
| Права доступа, privacy, secret handling | negative tests, audit assertions, fail-closed checks |
| UI/шаблоны/браузерный мост | Django view tests and Playwright e2e for the main path |
| Deployment/runtime commands | dry-run command, documentation update, no secrets in repo |
| Documentation-only | link/reference check by review, `make gen-struct` if structure changed |

## Независимая проверка субагентом

Для крупных, рискованных или многошаговых изменений рекомендуется разделять роли:

- основной агент реализует код и добавляет или обновляет тесты;
- отдельный быстрый проверочный субагент запускает согласованный набор проверок и сообщает фактические результаты.

Независимая проверка особенно желательна для изменений в:

- AI tools, task types, agent runtime и MCP;
- `contracts/`;
- memory ingestion, FTS/vector, privacy и secret handling;
- role/policy/security слоях;
- миграциях данных;
- deployment-процедурах;
- Playwright/e2e-сценариях;
- пользовательских сквозных сценариях.

Проверочный субагент должен:

- запускать targeted unit/integration/e2e проверки по затронутому scope;
- проверять, что новые тесты покрывают пользовательское или интеграционное поведение, а не только внутренние детали реализации;
- фиксировать команды, результат, падения и остаточные риски;
- не менять код без явного задания;
- не трогать незакоммиченные изменения пользователя;
- писать временные файлы, логи и артефакты только в `.local/`.

Для малых низкорисковых правок допускается проверка тем же агентом. Независимая проверка не заменяет CI, обязательные команды проекта и финальный отчет.

## Правила для AI-сценариев

Тесты AI-путей должны быть детерминированными:

- бизнес-действия проверяются через Django tool gateway, service layer и audit;
- потоковые ответы LLM в браузерных e2e можно мокировать;
- реальные LLM-вызовы допускаются только для отдельного eval или ручной проверки, если это явно указано;
- write-tools должны проверять confirmation flow, отказ, повторное подтверждение и истечение токена;
- найденные документы и память не должны исполняться как инструкции модели.

## Отчет о проверке

В финальном отчете по задаче нужно указать:

- какие тесты добавлены или обновлены;
- какие команды выполнены и с каким результатом;
- какие проверки не запускались и почему;
- какие документы обновлены или почему документация не требовала изменений;
- остаточный риск, если e2e или независимая проверка невозможны в текущей среде.
