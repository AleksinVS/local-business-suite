TOOL_REGISTRY_ROOT = {
    "version": "1.0",
    "name": "chat_agent_tool_registry",
    "description": "Заявленные инструменты, доступные чату и агентному блоку.",
    "default_policies": {
        "authentication_required": True,
        "policy_enforced": True,
        "writes_require_confirmation": True,
        "direct_sql_writes_allowed": False,
    },
}

TOOLS = [
    {
        "id": "ui.get_current_context",
        "title": "Получить текущий контекст UI",
        "domain": "ui",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть безопасный контекст текущего окна, связанный с текущим запросом чата.",
        "inputs": [],
        "outputs": [
            "status",
            "context",
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible",
    },
    {
        "id": "ui.open_right_panel",
        "title": "Открыть объект в правой панели",
        "domain": "ui",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть безопасную команду браузера для открытия видимого объекта модуля в общей правой панели.",
        "inputs": [
            "source_code",
            "object_type",
            "object_id",
            "mode",
        ],
        "input_schemas": {
            "mode": {
                "description": "Режим правой панели. В MVP поддерживается только просмотр.",
                "enum": ["view"],
            },
        },
        "outputs": [
            "status",
            "ui_command",
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible",
    },
    {
        "id": "workorders.list",
        "title": "Список заявок",
        "domain": "workorders",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть заявки с фильтром по статусу и ограничением количества.",
        "inputs": [
            "status",
            "limit",
        ],
        "input_schemas": {
            "status": {
                "description": "Фильтр по статусу заявки.",
                "enum": ["new", "accepted", "in_progress", "on_hold", "resolved", "closed", "cancelled"],
            },
            "limit": {
                "description": "Максимальное количество результатов.",
                "type": "integer",
            },
        },
        "outputs": [
            "items",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "workorders.get",
        "title": "Получить заявку",
        "domain": "workorders",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть одну заявку по внутреннему id или человекочитаемому номеру.",
        "inputs": [
            "workorder_id",
            "number",
        ],
        "outputs": [
            "workorder",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "workorders.search",
        "title": "Поиск заявок",
        "domain": "workorders",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Искать индексированные данные заявок через память с проверкой доступа к заявкам.",
        "inputs": [
            "query",
            "limit",
        ],
        "input_schemas": {
            "query": {
                "description": "Поисковый запрос по заявкам на естественном языке.",
                "type": "string",
            },
            "limit": {
                "description": "Максимальное количество найденных заявок.",
                "type": "integer",
            },
        },
        "outputs": [
            "items",
            "citations",
            "meta",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "waiting_list.get",
        "title": "Получить запись листа ожидания",
        "domain": "waiting_list",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть безопасные метаданные одной видимой записи листа ожидания по id.",
        "inputs": [
            "entry_id",
        ],
        "input_schemas": {
            "entry_id": {
                "description": "Внутренний id записи листа ожидания.",
                "type": "integer",
            },
        },
        "outputs": [
            "entry",
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible",
    },
    {
        "id": "workorders.create",
        "title": "Создать заявку",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Создать заявку с подразделением, темой, описанием, необязательным изделием и приоритетом.",
        "inputs": [
            "department_id",
            "subject",
            "description",
            "device_id",
            "priority",
        ],
        "input_schemas": {
            "priority": {
                "description": "Уровень приоритета заявки.",
                "enum": ["low", "medium", "high", "critical"],
            },
        },
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": True,
        "required_role_scope": "create",
    },
    {
        "id": "workorders.transition",
        "title": "Изменить статус заявки",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Перевести заявку в разрешенный следующий статус.",
        "inputs": [
            "workorder_id",
            "target_status",
        ],
        "input_schemas": {
            "target_status": {
                "description": "Целевой статус перехода. Должен быть разрешен правилами процесса.",
                "enum": ["new", "accepted", "in_progress", "on_hold", "resolved", "closed", "cancelled"],
            },
        },
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": True,
        "required_role_scope": "transition",
    },
    {
        "id": "workorders.comment",
        "title": "Добавить комментарий к заявке",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Добавить комментарий в историю заявки.",
        "inputs": [
            "workorder_id",
            "text",
        ],
        "outputs": [
            "comment",
        ],
        "requires_confirmation": False,
        "required_role_scope": "comment",
    },
    {
        "id": "workorders.confirm_closure",
        "title": "Подтвердить закрытие заявки",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Подтвердить закрытие выполненной заявки.",
        "inputs": [
            "workorder_id",
        ],
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": True,
        "required_role_scope": "confirm_closure",
    },
    {
        "id": "workorders.rate",
        "title": "Оценить заявку",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Поставить оценку закрытой заявке.",
        "inputs": [
            "workorder_id",
            "rating",
        ],
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": False,
        "required_role_scope": "rate",
    },
    {
        "id": "departments.list",
        "title": "Список подразделений",
        "domain": "core",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть иерархическое дерево подразделений или отфильтрованную часть.",
        "inputs": [
            "query",
            "parent_id",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "devices.list",
        "title": "Список изделий",
        "domain": "inventory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть изделия для выбора и поиска.",
        "inputs": [
            "query",
            "department_id",
            "archived",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "inventory.devices.create",
        "title": "Создать изделие",
        "domain": "inventory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Создать новое медицинское изделие в инвентаре.",
        "inputs": [
            "name",
            "department_id",
            "model",
            "serial_number",
        ],
        "outputs": [
            "device",
        ],
        "requires_confirmation": True,
        "required_role_scope": "manage",
    },
    {
        "id": "inventory.devices.update",
        "title": "Обновить изделие",
        "domain": "inventory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Обновить существующее медицинское изделие.",
        "inputs": [
            "device_id",
            "name",
            "department_id",
            "model",
            "serial_number",
        ],
        "outputs": [
            "device",
        ],
        "requires_confirmation": True,
        "required_role_scope": "manage",
    },
    {
        "id": "inventory.devices.archive",
        "title": "Архивировать изделие",
        "domain": "inventory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Архивировать медицинское изделие, чтобы его больше нельзя было назначать.",
        "inputs": [
            "device_id",
        ],
        "outputs": [
            "device",
        ],
        "requires_confirmation": True,
        "required_role_scope": "manage",
    },
    {
        "id": "analytics.summary",
        "title": "Сводка аналитики",
        "domain": "analytics",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть аналитические сводки только для чтения по статусам, подразделениям или исполнителям.",
        "inputs": [
            "summary_type",
        ],
        "outputs": [
            "summary",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "memory.search",
        "title": "Поиск в памяти",
        "domain": "memory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": (
            "Искать принятые знания памяти и необязательные ссылки на исходные данные с цитатами и служебными "
            "метаданными маршрутизации. В обычном корпусе единый профиль ранжирования (гибрид FTS + вектор, слияние RRF) "
            "применяется всегда; выбор весов каналов или именованного профиля недоступен ИИ-боту (ADR-0030 "
            "решение 6). Профили ранжирования ADR-0016 — отложенный архитектурный долг, не публичный параметр."
        ),
        "inputs": [
            "query",
            "limit",
            "sensitivity",
            "corpus",
            "bundle_id",
        ],
        "input_schemas": {
            "query": {
                "description": "Поисковый запрос на естественном языке.",
                "type": "string",
            },
            "limit": {
                "description": "Максимальное количество элементов памяти.",
                "type": "integer",
            },
            "sensitivity": {
                "description": "Максимальный допустимый уровень чувствительности для найденного контекста памяти.",
                "enum": [
                    "public",
                    "internal",
                    "confidential",
                    "pii_redacted",
                    "pii_original",
                    "secret",
                ],
            },
            "bundle_id": {"description": "Опциональный раздел Wiki для corpus=knowledge. Поиск ограничен его опубликованными разрешёнными статьями.", "type": "string"},
            "corpus": {
                "description": (
                    "Корпус поиска. knowledge (по умолчанию) — принятые знания, с автоматическим fallback к "
                    "source_data, если знаний не найдено. source_data — только явные исходные объекты "
                    "(файлы/заявки/иные источники), результат всегда помечается предупреждением, что это не "
                    "принятое знание. Веса каналов и именованный профиль ранжирования не передаются: единственный "
                    "серверный профиль (RRF, фикс. веса fulltext/vector) применяется всегда."
                ),
                "enum": ["knowledge", "source_data"],
            },
        },
        "outputs": [
            "items",
            "citations",
            "meta",
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible",
    },
    {
        "id": "memory.remember",
        "title": "Запомнить знание из чата",
        "domain": "memory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Синхронно записать выбранные сообщения ИИ-чата как личную или организационную память: файл знания, git commit и поисковый индекс создаются за один вызов.",
        "inputs": [
            "session_id",
            "message_ids",
            "target_scope",
            "user_note",
            "importance",
        ],
        "input_schemas": {
            "target_scope": {
                "description": "Целевая область памяти. По умолчанию personal.",
                "enum": ["personal", "organization"],
            },
            "message_ids": {
                "description": "ID сообщений чата, которые используются как источник происхождения.",
                "type": "array",
            },
            "user_note": {
                "description": "Необязательная заметка пользователя о том, что нужно запомнить.",
                "type": "string",
            },
            "importance": {
                "description": "Необязательная подсказка важности, например high или organization_candidate.",
                "type": "string",
            },
        },
        "outputs": [
            "memory_id",
            "target_scope",
            "knowledge_file_path",
            "knowledge_file_commit",
            "secret_handles",
            "index_status",
            "message",
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible",
    },
    {
        "id": "memory.update_personal",
        "title": "Обновить личную память",
        "domain": "memory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Изменить или удалить один элемент личной памяти, принадлежащий пользователю.",
        "inputs": [
            "memory_id",
            "operation",
            "new_text",
        ],
        "input_schemas": {
            "operation": {
                "description": "Операция с личной памятью.",
                "enum": ["edit", "delete"],
            },
            "memory_id": {
                "description": "Стабильный id элемента памяти.",
                "type": "string",
            },
            "new_text": {
                "description": "Новый текст памяти для операции изменения.",
                "type": "string",
            },
        },
        "outputs": [
            "memory_id",
            "event_id",
            "status",
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible",
    },
    {
        "id": "ai.skills.create_or_update",
        "title": "Создать или обновить рабочий навык ИИ",
        "domain": "ai",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Атомарно создать или обновить рабочий навык ИИ с инструкциями в data/contracts/ai/skills. Требуется ai.manage_skills.",
        "inputs": [
            "skill_id",
            "name",
            "description",
            "source_code",
            "object_types",
            "required_tools",
            "trigger_examples",
            "body",
        ],
        "input_schemas": {
            "skill_id": {
                "description": "Нормализованный id навыка, например module.workflow.",
                "type": "string",
            },
            "required_tools": {
                "description": "ID существующих инструментов, которые нужны навыку.",
                "type": "array",
            },
            "body": {
                "description": "Тело SKILL.md только с инструкциями. Без скриптов, assets и произвольных файлов.",
                "type": "string",
            },
        },
        "outputs": [
            "status",
            "skill_id",
            "path",
            "required_tools",
            "message",
        ],
        "requires_confirmation": True,
        "required_role_scope": "ai.manage_skills",
    },
    {
        "id": "access.get_role_rules",
        "title": "Получить правила ролей",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть текущую конфигурацию ролей из role_rules.json.",
        "inputs": [],
        "outputs": [
            "rules",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "access.users.list",
        "title": "Список пользователей",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть пользователей с ролями и подразделениями. Только для администраторов.",
        "inputs": [
            "query",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "superuser",
    },
    {
        "id": "access.users.explain",
        "title": "Объяснить эффективный доступ пользователя",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Показать источники эффективного доступа выбранного пользователя без Django permissions, email и AD identity.",
        "inputs": ["user_id"],
        "input_schemas": {
            "user_id": {
                "description": "Внутренний идентификатор существующего пользователя.",
                "type": "integer",
            },
        },
        "outputs": ["user", "assigned", "effective", "notes"],
        "requires_confirmation": False,
        "required_role_scope": "manage_roles",
    },
    {
        "id": "access.open_editor",
        "title": "Открыть редактор доступа",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть серверную команду открытия существующего редактора пользователя или роли; сохранение выполняет человек.",
        "inputs": ["target_type", "target_id"],
        "input_schemas": {
            "target_type": {
                "description": "Тип редактируемого объекта.",
                "enum": ["user", "role"],
            },
            "target_id": {
                "description": "Идентификатор существующего пользователя или контрактной роли.",
                "type": "string",
            },
        },
        "outputs": ["status", "ui_command"],
        "requires_confirmation": False,
        "required_role_scope": "manage_roles",
    },
    {
        "id": "access.groups.list",
        "title": "Список групп",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Вернуть все доступные группы Django. Только для администраторов.",
        "inputs": [],
        "outputs": [
            "items",
        ],
        "required_role_scope": "superuser",
    },
    {
        "id": "knowledge.search",
        "title": "Найти статьи вики",
        "domain": "memory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": (
            "Найти доступный раздел или тематические статьи перед чтением и правкой. "
            "Без bundle_id возвращает имена разделов; с bundle_id без query — список статей; "
            "с query — совпадения по содержанию, limit от 1 до 50. "
            "Статьи возвращаются с ID, путями, заголовками и Git SHA в revision. "
            "Дочитайте найденную статью через knowledge.get, основание — через knowledge.source. "
            "Вики не изменяет. Недоступный раздел, несверенная ревизия или неверные параметры дают отказ. "
            "Пустой список означает отсутствие доступных результатов в выбранной области."
        ),
        "inputs": [
            "bundle_id",
            "query",
            "limit"
        ],
        "input_schemas": {
            "bundle_id": {
                "type": "string"
            },
            "query": {
                "type": "string"
            },
            "limit": {
                "type": "integer"
            }
        },
        "outputs": [
            "bundles",
            "revision",
            "items",
            "engine"
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible"
    },
    {
        "id": "knowledge.get",
        "title": "Прочитать статью вики",
        "domain": "memory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": (
            "Прочитать полный опубликованный Markdown статьи перед её использованием или редактированием. "
            "Укажите bundle_id и ровно один адрес: knowledge_id либо path относительно раздела. "
            "Подходит и для перехода по ссылке на статью вне поисковой выдачи. "
            "Возвращает Markdown, ID, путь, заголовок, revision с Git SHA и confirmation_state. "
            "Основания статьи читайте через knowledge.source. Вики не изменяет. "
            "Недоступная статья, неверный адрес или несверенная ревизия дают отказ."
        ),
        "inputs": [
            "bundle_id",
            "knowledge_id",
            "path"
        ],
        "input_schemas": {
            "bundle_id": {
                "type": "string"
            },
            "knowledge_id": {
                "type": "string"
            },
            "path": {
                "type": "string"
            }
        },
        "outputs": [
            "knowledge_id",
            "title",
            "path",
            "revision",
            "markdown",
            "confirmation_state"
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible"
    },
    {
        "id": "knowledge.source",
        "title": "Прочитать основание статьи",
        "domain": "memory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": (
            "Прочитать разрешённое текущее представление источника перед использованием факта в ответе или статье. "
            "Укажите bundle_id, source_code и source_object_id. Возвращает text и source_ref с полями "
            "source_code, source_object_id, text_hash; эту ссылку включайте в source_refs статьи "
            "или передавайте в knowledge.compare вместе с предлагаемым уточнением. "
            "Вики не изменяет и документ не импортирует. Проверяет права читателя, аудиторию раздела "
            "и допустимость передачи текста модели. Недоступный источник, изменение его версии "
            "во время чтения или неподходящая политика дают отказ."
        ),
        "inputs": [
            "bundle_id",
            "source_code",
            "source_object_id"
        ],
        "input_schemas": {
            "bundle_id": {
                "type": "string"
            },
            "source_code": {
                "type": "string"
            },
            "source_object_id": {
                "type": "string"
            }
        },
        "outputs": [
            "source_ref",
            "text"
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible"
    },
    {
        "id": "knowledge.edit",
        "title": "Отредактировать статьи вики",
        "domain": "memory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": (
            "Сохранить подготовленную автором редакцию одной или нескольких связанных статей. "
            "Сначала дочитайте существующие затронутые статьи через knowledge.get и проверьте основания через knowledge.source. "
            "Передайте прочитанный Git SHA в expected_revision и files с полным Markdown по относительным путям; "
            "null удаляет Note. Сохраняет авторский текст без повторной генерации, поддерживает навигацию, "
            "фиксирует один коммит при изменении и обновляет индекс. Возвращает revision, committed, "
            "changed_paths и index_status. Пустая или уже выполненная правка нового коммита не создаёт. "
            "Независимые коммиты не мешают записи. read_revisions (необязательно) задаёт пути значимых статей и фактически прочитанные SHA, включая целевые статьи, прочитанные в разных ревизиях. Изменение целевой статьи или заявленного основания, чужая незавершённая правка, недопустимые основания или права дают отказ. "
            "При конфликте изучите diff и необходимый контекст, сохраните чужие изменения; при index_pending коммит уже создан — "
            "повторите тот же вызов для сверки индекса. Если нового знания нет, запись не нужна."
        ),
        "inputs": [
            "bundle_id",
            "expected_revision",
            "files",
            "read_revisions"
        ],
        "input_schemas": {
            "bundle_id": {
                "type": "string"
            },
            "expected_revision": {
                "type": "string"
            },
            "read_revisions": {
                "type": "object",
                "additionalProperties": {"type": "string"}
            },
            "files": {
                "type": "object",
                "additionalProperties": {
                    "type": [
                        "string",
                        "null"
                    ]
                }
            }
        },
        "outputs": [
            "revision",
            "committed",
            "changed_paths",
            "index_status"
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible"
    },
    {
        "id": "knowledge.compare",
        "title": "Сопоставить утверждения статей",
        "domain": "memory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": (
            "Получить необязательную подсказку локального классификатора об отношении между утверждениями. "
            "Укажите bundle_id, left_id и либо right_id для второй статьи, либо proposed_text "
            "и проверенный source_ref из knowledge.source для предлагаемого уточнения. "
            "Возвращает relation, probability, model, ID статей и revision. "
            "Результат оценивайте вместе с источниками; он не даёт разрешения на правку. "
            "Вики не изменяет, готовые статьи сохраняются через knowledge.edit. "
            "Недоступный материал, устаревшее основание, неверные параметры или отсутствие совместимой "
            "локальной модели дают отказ. При недоступной модели или неопределённом результате "
            "продолжайте чтение и проверку оснований без этой подсказки."
        ),
        "inputs": [
            "bundle_id",
            "left_id",
            "right_id",
            "proposed_text",
            "source_ref"
        ],
        "input_schemas": {
            "bundle_id": {
                "type": "string"
            },
            "left_id": {
                "type": "string"
            },
            "right_id": {
                "type": "string"
            },
            "proposed_text": {
                "type": "string"
            },
            "source_ref": {
                "type": "object"
            }
        },
        "outputs": [
            "revision",
            "left_id",
            "right_id",
            "relation",
            "probability",
            "model"
        ],
        "requires_confirmation": False,
        "required_role_scope": "visible"
    },
]


def get_tool_registry():
    return {tool["id"]: tool for tool in TOOLS}


def get_registry_payload():
    return {**TOOL_REGISTRY_ROOT, "tools": TOOLS}
