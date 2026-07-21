from __future__ import annotations

from apps.core.ai_skills import AgentSkillDescriptor, register_agent_skill


BODY = """
# Открытие заявки в правом сайдбаре

Используй этот skill, когда пользователь просит открыть, показать справа или вывести в правом сайдбаре заявку/наряд.

Не используй его для создания заявки, изменения статуса, назначения исполнителя или комментариев.

## Workflow

1. Если пользователь указал номер заявки (`№17`, `заявка 17`) или в ближайшей истории есть такой номер, вызови `workorders.get(number="17")`.
2. Если пользователь говорит `ее`, `эту заявку`, `эту карточку`, `текущую заявку` и номер не ясен, вызови `ui.get_current_context`.
3. Если текущий контекст содержит `source_code=workorders`, `object_type=workorder`, возьми `selection.object_id`.
4. Если `workorders.get` вернул заявку, возьми ее `id` как `object_id`.
5. Вызови `ui.open_right_panel(source_code="workorders", object_type="workorder", object_id=<id>, mode="view")`.
6. Если объект недоступен или неоднозначен, не придумывай id. Попроси уточнить номер заявки.

После успешного открытия ответь кратко: `Открываю заявку справа.`
""".strip()


def register() -> None:
    register_agent_skill(
        AgentSkillDescriptor(
            skill_id="workorders.open_right_panel",
            name="workorders-open-right-panel",
            description=(
                "Используй, когда пользователь просит открыть видимую заявку или текущую "
                "карточку заявки в правом сайдбаре."
            ),
            source_code="workorders",
            object_types=("workorder",),
            required_tools=("workorders.get", "ui.get_current_context", "ui.open_right_panel"),
            trigger_examples=("Открой заявку №17", "Открой ее в правом сайдбаре", "Покажи текущую заявку справа"),
            body=BODY,
        ),
        replace=True,
    )
