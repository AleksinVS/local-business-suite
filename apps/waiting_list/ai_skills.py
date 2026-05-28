from __future__ import annotations

from apps.core.ai_skills import AgentSkillDescriptor, register_agent_skill


BODY = """
# Открытие записи листа ожидания в правом сайдбаре

Используй этот skill, когда пользователь просит открыть, показать справа или вывести в правом сайдбаре запись листа ожидания.

Не используй его для создания, редактирования или смены статуса записи.

## Workflow

1. Если пользователь указал номер записи (`запись 12`, `лист ожидания 12`), вызови `waiting_list.get(entry_id=12)`.
2. Если пользователь говорит `ее`, `эту запись`, `текущую карточку` и номер не ясен, вызови `ui.get_current_context`.
3. Если текущий контекст содержит `source_code=waiting_list`, `object_type=waiting_list_entry`, возьми `selection.object_id`.
4. Если `waiting_list.get` вернул запись, возьми ее `id` как `object_id`.
5. Вызови `ui.open_right_panel(source_code="waiting_list", object_type="waiting_list_entry", object_id=<id>, mode="view")`.
6. Если запись не найдена, недоступна или неоднозначна, попроси уточнить номер записи.

После успешного открытия ответь кратко: `Открываю запись листа ожидания справа.`
""".strip()


def register() -> None:
    register_agent_skill(
        AgentSkillDescriptor(
            skill_id="waiting_list.open_right_panel",
            name="waiting-list-open-right-panel",
            description=(
                "Используй, когда пользователь просит открыть видимую запись листа "
                "ожидания или текущую карточку листа ожидания в правом сайдбаре."
            ),
            source_code="waiting_list",
            object_types=("waiting_list_entry",),
            required_tools=("waiting_list.get", "ui.get_current_context", "ui.open_right_panel"),
            trigger_examples=(
                "Открой запись листа ожидания 12",
                "Открой ее справа",
                "Покажи текущую запись листа ожидания",
            ),
            body=BODY,
        ),
        replace=True,
    )
