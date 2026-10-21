# LBS Access — план миграции, задания агентам и проверочная матрица

**Статус:** **Accepted — согласованный исполнительный план и тестовая матрица; ещё не выполнено.** **Не запускать автоматический production cutover**. Использовать вместе с `07_ACCESS_ARCHITECTURE.md`, `06_PLUGGABLE_BUSINESS_MODULES.md` и `AGENTS.md` репозитория.

## 1. Что считается успехом

Работает тот же существующий администраторский интерфейс, те же права реальных пользователей и предметные ограничения, но систему ролей можно включить без `workorders`, а подключаемый модуль самостоятельно декларирует свои capabilities. Telegram/WebChat/Bitrix24 и Pi/Claude/LangGraph используют проверенный контекст без возможности расширить доступ через payload. Для минимального внедрения внешний IAM и отдельный сервис прав не требуются.

Результат **не должен** быть реализован путём новой параллельной RBAC-БД или полного переписывания `apps.accounts`.

## 2. Инвентаризация и фиксирование исходного поведения (ACCESS-00)

Перед изменением кода зафиксировать:

- архитектурный граф `apps.accounts`, `apps.workorders.policies`, `apps.warehouse.policies`, `apps.waiting_list`, `apps.memory.policies`, `apps.core`, `apps.settings_center`, каналов и AI gateway;
- `models.ForeignKey` и наследуемые Django связи `User`, `Group`, `Department`, `Board`, `MemorySource` и `StockDocument`;
- весь capability catalog: `flag`, `scope`, `targets`, защищённые/технические роли, пути редактирования и разрешения;
- все обращения к `role_rules` и `active_role_rules`, включая lazy imports, шаблоны, celery/jobs и AI tools;
- фактическую конфигурацию runtime role document: файлы, PostgreSQL allowlist, Git defaults, миграции/rollback;
- текущие матрицы реального доступа (должностные роли, суперпользователь, отсутствующая роль, отключённая учётка, ветка подразделения, состояния объекта);
- показатели p50/p95 на типовых списках и одиночных проверках; SQL counts при доступе к множеству объектов;
- полную резервную копию настроек, таблиц и аудитов до миграций; способ восстановления.

**DoD:** reproducible snapshot + тестовые фикстуры с *ожидаемым до рефакторинга* решением, ADR и отсутствие изменений прикладного кода.

## 3. Пошаговая миграция

| Этап | Содержание | Не делать | Acceptance gate |
|---|---|---|---|
| ACCESS-00 | Инвентаризация и baseline | Оптимизации до фактов | Зафиксированы grants и матрица negative cases |
| ACCESS-01 | Вынести из WorkOrders общую часть ролей/grant parsing и org scope в `apps.accounts`/отдельный нейтральный пакет | Вводить новый policy DSL | Новая и старая реализация эквивалентны на golden matrix |
| ACCESS-02 | Сформировать модульный декларативный каталог capabilities и адаптер к текущим `$capabilities` | Создавать второй изменяемый каталог | Добавление модуля не требует правки accounts; нет автоматического назначения |
| ACCESS-03 | Перевести Warehouse и Waiting List на общий нейтральный port; оставить предметные проверки локальными | Менять инварианты склада или ACL листа ожидания | Модули проходят e2e без импорта `workorders.policies` |
| ACCESS-04 | Вынести TrustedActorContext/identity linking для Local, AD, Telegram, Bitrix24; интеграция с AgentTask | Принимать неподтверждённые identity claims | Чужой external ID/installation отклоняется, audit сохраняется |
| ACCESS-05 | Подключить Wiki и групповые комнаты к доступу по аудитории; закрытый retrieval и публикация | Использовать только права инициатора | Не допускается cross-room/cross-source leakage |
| ACCESS-06 | Делегированные agent grants, отзыв, revalidation перед side effects, approval binding | Встроить права агента как текстовый prompt | Два runtime не могут повысить права при делегировании |
| ACCESS-07 | LocalResourceACL port по умолчанию; OpenFGA adapter только при доказанном сложном объектном ACL | Делать OpenFGA/IAM обязательным | Локальный профиль независим, optional backend проходит golden/negative tests |

**Зависимости:** ACCESS-00 должен завершиться до ACCESS-01..03; ACCESS-01 перед ACCESS-03; ACCESS-02 перед полным отключением модулей (BM-01/BM-05); ACCESS-04 до external agent A2A (A06), Bitrix24 write (A08) и корпоративного Telegram; ACCESS-05 до production WebChat/Knowledge; ACCESS-06 до произвольного межагентного делегирования. ACCESS-07 не блокирует минимальный пилот.

### Особая оговорка о переносе `active_role_rules`

Переносить код *с сохранением семантики*, а не по схожести имён. `apps.workorders.policies.active_role_rules()` обрабатывает `superuser`, отдельные целые ролевые grants, `role_rules` и fallback значения. Извлечённый нейтральный resolver должен давать точно те же решения. Предметные `scope_matches/can_transition` остаются в WorkOrders. Пользовательские выборки делать пакетно; не создавать N запросов `accounts` на N строк результатов.

### Встраивание в текущую Django-реализацию

- Первый шаг может быть адаптером поверх имеющихся Django `Group`/`ExternalIdentity`/role JSON. Не требуется переписывать всю ORM и `Settings Center`.
- `apps.accounts` не должен импортировать `workorders`. Допускается временный compatibility re-export из `workorders.policies` в новый общий модуль, но **не наоборот**.
- `warehouse.policies` и `waiting_list.services` импортируют только нейтральный access port и собственные предметные правила.
- Django User может остаться локальной реализацией `IdentityProvider`; он не становится обязательной моделью внешних микросервисов.
- Если меняется хранилище роли (file → PostgreSQL), это **отдельная миграция** с планом expand/backfill/cutover/rollback по ADR-0048. Не совмещать с отделением `accounts` от `workorders`.

## 4. Пакеты задач для агентов

| ID | Исполнитель / примерный scope | Разрешённая запись | Результат |
|---|---|---|---|
| AX-00 | Архитектор-аудитор | Только `docs`/отчёты | Dependency map, goldens, ADR, риски |
| AX-01 | Разработчик Access | Общая access library и совместимые обёртки | Neutral roles resolver + unit tests |
| AX-02 | Разработчик Registry | Manifest/capability registration + tests | Доменные descriptors, корректный `enabled` gate |
| AX-03 | Предметные разработчики | Warehouse/Waiting List ports, selectors/tests | Нет зависимости от WorkOrders; права не расширены |
| AX-04 | Identity & Integrations | Проверенные адаптеры внешних ID, корреляция, тесты | Контекст не формируется из необработанного payload |
| AX-05 | Wiki / Chat security | Policy integration и negative e2e | ACL аудитории, отзыв прав, нет утечки |
| AX-06 | Agent security | AgentTask authority refs, policy checks, audit | Least privilege delegation + revocation |
| AX-07 | Независимый reviewer | Тесты и отчёты, без несанкционированной правки исходников | Подтверждённая матрица регрессий |

**Правила параллельной работы:** AX-01 и AX-02 могут проектироваться параллельно после AX-00, но изменения `apps.accounts`/catalog мигрируются согласованно. AX-03 не менять общий access API одновременно с AX-01. AX-05/06 работать с заранее зафиксированным контрактом; независимый reviewer получает code diff, fixtures и матрицу, а не весь сырой клиентский контекст.

Каждый исполнитель следует существующему `AGENTS.md`: сохраняет `git status`, не меняет чужую работу, создаёт ADR по необходимости, обновляет `.desc.json` и `PROJECT_STRUCTURE.yaml` при изменении структуры. Полный прогон тестов выполняется в приёмочном gate, а не каждым субагентом по кругу.

## 5. Acceptance matrix

| Сценарий | Unit | Integration | E2E | Обязательное поведение |
|---|---|---|---|---|
| Роль без capability | x | x | x | Deny |
| Пользователь без роли / inactive | x | x | x | Deny; нет скрытого viewer |
| Защищённая роль / изменение privileged flags | x | x | x | Только разрешённый superuser через защищённый путь |
| Self-role escalation / last-superuser | x | x | x | Запрет с audit; резервный superuser сохранён |
| Одинаковый набор grants до/после выделения | x | x | x | Совпадают на golden matrix |
| Перемешивание scope/targets из разных ролей | x | x | x | Нет искусственного расширения |
| Warehouse + Waiting List без WorkOrders | x | x | x | Оба работают; нет import/init failures |
| Включение/отключение provider | x | x | x | Grants не становятся доступными, данные не удаляются |
| Новый capability в manifest | x | x | x | Роли не получают его автоматически |
| Отзыв роли в середине AgentTask | x | x | x | Защищённая запись отклонена перед commit |
| Подложный `actor` в MCP/A2A/Telegram | x | x | x | Deny; нет повышенных прав |
| Ошибочный identity link в Telegram/Bitrix | x | x | x | Нет автоматической привязки по совпадению атрибутов |
| Wiki: скрытый документ/заголовок/ссылка | x | x | x | Не попадает ни в search, ни в контекст модели |
| Общая комната с неподтверждённой аудиторией | x | x | x | Не раскрывает private Wiki; safe fallback |
| Bitrix24 API и LBS policy | x | x | x | Нельзя обойти запрет одной из систем |
| Аудит / correlation / rollback ролей | x | x | x | История целая, нет duplicate writes |
| Списки из 1k+ элементов | x | x |  | Нет N+1 access checks; p95 не хуже baseline без объяснения |
| Профиль без внешнего IAM/PDP | x | x | x | Работает в пределах локальной настройки без OpenFGA/OPA |

## 6. Пример безопасного распределённого сценария

**Пользователь → Telegram → агент → Wiki → Битрикс24:**

1. Telegram Adapter проверяет update/bot token и связывает отправителя с подтверждённым локальным `subject_ref`.
2. AgentTask получает `installation_id`, инициатора и ссылку на серверную политику. Прямой текстовый список ролей не становится разрешением.
3. LLM-Wiki применяет ACL до возврата выдержек. В групповом диалоге действует политика аудитории, не расширенная роль инициатора.
4. Агент предлагает создать задачу. Domain TaskProvider проверяет LBS Access, наличие capability и реальные полномочия в Битрикс24.
5. Перед записью повторно проверяются актуальная роль и `approval_ref` с привязкой к точному действию; запись выполняется с idempotency key.
6. Сохраняются внешняя ссылка/номер задачи и audit с correlation ID. При network retry повторное создание не происходит.
7. Системное сообщение в комнату содержит только разрешённую всем участникам информацию; ссылку на закрытую задачу не превращать в раскрытие её содержания.

## 7. Обратимость и условия остановки

- Рефакторинг начинается с compatibility adapter и тестов эквивалентности, а не удаления старого `workorders.policies`.
- Изменения определения ролей, capability namespace и link identities отдельны; если нарушена матрица исходного доступа, **пакет не принимается**.
- Миграцию ключей прав допускается сделать только вместе с versioned alias/mapping и dry-run отчётом фактического изменения разрешений.
- При обнаружении ACL leak, невалидной cross-tenant связки, потери аудита, дубля side effects или разрыва last-superuser восстановить прежний профайл и прекратить внедрение.
- Не проводить автоматическую пересинхронизацию AD/Bitrix ролей или раздачу прав по умолчанию.

## 8. Не вводить до реальной необходимости

Отдельный IAM-server как обязательную зависимость, общий policy DSL, универсальный compiler, централизованный ReBAC graph/relationship service, сложную иерархию ролей, OPA/OpenFGA, распределённые кеши авторизации, серверные plugins с hot-reload, новый язык backend. Внедрение любого пункта — отдельный ADR с измеримой причиной, migration plan, security review и rollback.

## 9. ADR и ссылки

Предложить **ADR-F07: LBS Access as optional authorization provider / module-declared capabilities / trusted agent authority**, поверх текущих ADR-0040, 0043, 0045, 0046, 0048. Не заменять принятые ADR молча. Для external ACL provider — отдельный ADR при реальном пилоте.

Базовые команды: `make verify-fast TEST_SCOPE=...`, `make verify-profile PROFILE=contracts|ai|memory`, после рискованного этапа — `make verify-full` и один сквозной e2e согласно `AGENTS.md`.

## 10. Отложенный пилот OpenFGA (v3.4)

Сейчас предусмотреть небольшой ресурсный порт и локальную реализацию. Реальный OpenFGA — отдельный пилот для одного типа документа/комнаты с verified IDs, pinned model/store, read-only сверкой решений, backfill и rollback. При недоступности — закрытая деградация, не расширение прав. Не изменять одновременно хранилище существующих ролей и объектный ACL. См. [09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md](09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md).

## 11. Privacy как обязательная граница доступа к содержимому

В тестах ACCESS-05 и группового чата дополнительно проверять целевое представление текста: исходная разрешённая запись `Source Adapter` не должна раскрывать PII через `adapter_check`, заголовок, citation или внешнюю LLM. Это **не замена существующих прав** и не внедрение OpenFGA: privacy и access — отдельные gates. [Проверки PRIV-T01..T14](10_CONTENT_PRIVACY_PIPELINE.md).

## 12. CROW / OKF — негативные тесты доступа

ACCESS-05 до CROW pilot проверяет **оба уровня** доступа:
- два пользователя в двух пространствах; внутри одного bundle **разные разрешённые Note** до `select`/classifier, включая fallback;
- Note, недоступная из-за отдельной restriction, не выдаёт title, filename, path или citations;
- `source/raw/.archive` с более строгим ACL не читаются по одному праву на производную Note; контекст помечает пропущенные материалы как неполный;
- изменение разрешений/отзыв группы немедленно лишает доступа несмотря на кэш базового дерева; финальная проверка выполняется заново;
- автоматический CROW ingest **не** объединяет источники с несовместимыми write-ACL: выбран разрешённый bundle/write-partition или отказ;
- отсутствие CROW/OpenFGA не разрушает LBS Access и право базово читать OKF в пределах разрешённого пространства.

Запрещено заводить одновременно две изменяемые ACL authority (LBS `scope_tokens` и CROW Frontmatter grants). Доступ к штатным CROW CLI/HTTP write не предоставляется пользователю. Полная матрица в [12_CROW_IMPLEMENTATION_PLAN.md](12_CROW_IMPLEMENTATION_PLAN.md) и [03_LLM_WIKI.md](03_LLM_WIKI.md).
