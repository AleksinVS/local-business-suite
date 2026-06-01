# Архитектурное ревью проекта

Дата: 2026-06-01.

Статус: review saved, remediation planned.

## Краткий вывод

Архитектурное направление проекта в целом устойчивое: Django остается источником истины для бизнес-данных, контракты отделены от runtime-состояния, решения фиксируются в ADR, AI runtime не пишет напрямую в бизнес-БД, а память и аналитика развиваются через source adapters и `SourceObjectEnvelope`.

Основные риски находятся не в выборе стека, а в расхождении между принятыми правилами и отдельными путями запуска или изменения состояния:

- production-старт не применяет миграции ко всем раздельным базам;
- часть изменений ролевого контракта обходит Settings Center, аудит и единый сервисный путь;
- AI gateway и MCP-фасад требуют более строгой привязки service identity к пользователю;
- agent runtime пишет фрагмент пользовательского prompt в технический лог;
- часть архитектурной документации ссылается на старые пути.

Корневой `BACKLOG.md` по решению владельца считается личными заметками владельца проекта и не входит в scope чистки. Рабочий backlog для агентов остается в `docs/planning/backlog.md`.

## Проверки

В ходе ревью выполнены:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
git diff --check
```

Результат: проверки прошли.

Полный `manage.py test` и браузерные e2e не запускались, потому что ревью не меняло прикладной код.

## Prompt, Логи И Разбор Ошибок

Пользовательский prompt уже хранится в системе как обычное сообщение чата:

- `apps.ai.views.AIChatMessageCreateView` создает `ChatMessage` с ролью `user`;
- текст сообщения хранится в `ChatMessage.content`;
- при включенном разделении баз эти данные физически находятся в `data/db/chat.sqlite3`;
- `AgentActionLog` для ошибок runtime хранит `prompt_sha256` и `prompt_length`, но не сырой prompt.

Значит, для разбора ошибок не нужно писать сырой prompt в технический лог agent runtime. Безопасный путь разбора:

1. Пользователь сообщает `request_id`, который показывается в сообщении об ошибке.
2. Оператор находит `AgentActionLog` по `request_payload.request_id`.
3. Через связанный `session` и `message` смотрит исходный `ChatMessage.content`, если у него есть право на разбор таких данных.
4. Для передачи разработчику делается обезличенная выдержка или синтетический пример в `.local/`.
5. В технических логах остаются `request_id`, `conversation_id`, длина prompt, хэш prompt, модель, код ошибки и trace tool-вызовов.

Рекомендуемое изменение: убрать из `services/agent_runtime/app.py` логирование `prompt[:100]` и полного `actor_context`. При необходимости добавить отдельный debug-режим, который по умолчанию выключен и пишет только обезличенный диагностический пакет в `.local/` или `data/logs/` с явным сроком хранения.

## Находки

### 1. Production-старт не мигрирует раздельные базы

Приоритет: critical.

Факты:

- `config/settings.py` определяет базы `default`, `chat`, `knowledge_meta`, `analytics_control`;
- `apps/core/db_routers.py` маршрутизирует `ai`, `memory` и `analytics` в отдельные базы;
- `docker/entrypoint.prod.sh` запускает только `python manage.py migrate --noinput`;
- README, Windows-скрипт и часть deployment-документов также показывают одиночный `migrate`.

Риск: на чистом развертывании таблицы для чата, памяти и управляющей аналитики могут не создаться, а ошибка проявится только при первом обращении к соответствующему контуру.

Рекомендация: ввести единый management command или shell-скрипт применения миграций по всем runtime-базам и использовать его в Docker, Windows/IIS и документации.

### 2. Ролевые контракты меняются несколькими путями

Приоритет: high.

Факты:

- Settings Center применяет runtime contracts через `apply_contract_payload`, валидирует payload, пишет атомарно и создает audit;
- старый экран `apps.core.views.RoleRulesUpdateView` пишет `LOCAL_BUSINESS_ROLE_RULES_FILE` напрямую;
- AI tool `access.update_role_permissions` также пишет role rules напрямую.

Риск: права доступа можно изменить вне единого audit и вне полного workflow Settings Center. Это особенно опасно для ролей, потому что они управляют доступом к заявкам, аналитике, настройкам и AI-инструментам.

Рекомендация: оставить один write-path для runtime contracts. Старые формы и AI-инструменты должны вызывать Settings Center service layer или стать read-only/proposal-only.

### 3. AI gateway и MCP-фасад принимают actor из тела запроса

Приоритет: high.

Факты:

- Django gateway принимает `actor` из JSON-тела запроса;
- проверка `validate_gateway_actor` работает только при переданном и найденном `session_id`;
- MCP tools принимают `user_id`, `username`, `roles` от внешнего клиента и прокидывают их в Django gateway.

Риск: при публикации agent runtime или MCP наружу утечка gateway token или ошибка сетевой изоляции дают возможность подставить другого пользователя. Пока runtime строго внутренний, риск ниже, но внешний MCP-фасад к production-использованию не готов.

Рекомендация: ввести service identity model для runtime/MCP, обязательную привязку сессии к пользователю, запрет tool execution без проверенной session ownership и отдельный ADR/update к ADR-0021 перед внешним MCP-доступом.

### 4. Agent runtime пишет пользовательский prompt в технический лог

Приоритет: high.

Факты:

- `services/agent_runtime/app.py` логирует начало prompt и actor context при `/chat`;
- проектные правила запрещают писать prompt, персональные данные и секреты в технические логи;
- безопасный audit уже есть в Django: `AgentActionLog` хранит `request_id`, prompt hash, длину prompt и ошибку.

Риск: технический лог agent runtime может содержать персональные данные, сведения из заявок, внутренние документы или секреты, введенные пользователем.

Рекомендация: заменить raw prompt logging на `request_id`, `conversation_id`, prompt length/hash, model id и error category. Для глубокого разбора использовать `ChatMessage.content` через контролируемый операторский доступ.

### 5. Временный debug log может попадать в корень проекта

Приоритет: medium.

Факты:

- `apps/core/middleware.py` использует путь `C:\inetpub\portal\debug_path.log`;
- на Linux такой путь становится именем файла в корне проекта;
- временные агентные, debug и runtime-артефакты должны быть в `.local/` или `data/logs/`.

Риск: корень проекта загрязняется, а debug-файлы могут попасть в рабочую область и мешать ревью.

Рекомендация: писать debug PATH_INFO только в `data/logs/` или `.local/logs/`, управлять этим отдельной env-переменной, а в production держать выключенным.

### 6. Архитектурные документы содержат устаревшие ссылки

Приоритет: medium.

Факты:

- `docs/architecture/POLICY_MODEL.md` ссылается на `config/role_rules.json` и `config/workflow_rules.json`;
- `docs/architecture/INTEGRATIONS.md` ссылается на `config/integrations/registry.json`;
- `docs/architecture/ARCHITECTURE.md` ссылается на отсутствующий `ai/chat_agent/ARCHITECTURE.md`.

Риск: новые участники и агенты будут искать source of truth не там, где он реально находится.

Рекомендация: обновить ссылки на `contracts/`, `apps/ai/tool_definitions.py`, `services/agent_runtime/README.md` и актуальные ADR.

## Порядок Исправления

1. Закрыть миграции всех runtime-баз и deployment-документацию.
2. Убрать raw prompt из логов agent runtime и описать безопасный порядок разбора ошибок.
3. Свести изменение runtime contracts к Settings Center service layer.
4. Ужесточить AI gateway/MCP identity checks.
5. Убрать debug log из корня.
6. Обновить устаревшие архитектурные ссылки.

## Остаточный Риск

Пока эти исправления не выполнены, проект можно развивать локально и на закрытом стенде, но production-профиль должен считаться требующим hardening перед расширением AI/MCP-доступа, подключением новых внешних источников и активной эксплуатацией памяти.
