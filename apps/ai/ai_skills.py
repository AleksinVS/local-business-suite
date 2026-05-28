from __future__ import annotations

from apps.core.ai_skills import AgentSkillDescriptor, register_agent_skill


SKILL_CREATOR_BODY = """
# Создание AI skill

Используй этот skill, когда администратор просит создать, описать, проверить или обновить instruction-only AI skill для локального агента.

Не используй этот skill для обычных пользовательских задач, открытия карточек, поиска заявок или редактирования бизнес-объектов.

## Порядок работы

1. Уточни узкий повторяемый сценарий: что пользователь говорит, какой модуль участвует, какой результат нужен.
2. Сформируй `skill_id` в нижнем регистре через точку, например `module.workflow`.
3. Сформируй короткие `name` и `description`. Описание должно объяснять, когда выбирать skill без чтения полного тела.
4. Заполни `source_code`, `object_types`, `required_tools` и `trigger_examples`.
5. Проверь, что `required_tools` уже существуют. Skill не выдает новых прав и не обходит gateway.
6. В body опиши только workflow: когда использовать, когда не использовать, порядок tools, правила неоднозначности и безопасный ответ пользователю.
7. Если описание слишком широкое, опасное, меняет права, скрывает аудит или требует произвольных файлов/scripts/assets, попроси сузить задачу.
8. Если у пользователя есть право `ai.manage_skills` и он подтвердил запись, вызови `ai.skills.create_or_update`.
9. Если права нет, подготовь проект SKILL.md и объясни, что сохранить его может администратор с правом `ai.manage_skills`.

Не записывай файлы напрямую и не утверждай, что skill создан, пока tool не вернул успешный статус.
""".strip()


def register() -> None:
    register_agent_skill(
        AgentSkillDescriptor(
            skill_id="ai.skill_creator",
            name="ai-skill-creator",
            description=(
                "Помогает администратору создать или обновить узкий instruction-only AI skill "
                "и при наличии права ai.manage_skills сохранить его через audited tool."
            ),
            source_code="ai",
            object_types=("agent_skill",),
            required_tools=("ai.skills.create_or_update",),
            trigger_examples=(
                "Создай skill для открытия карточек нового модуля",
                "Проверь SKILL.md и сохрани runtime skill",
            ),
            body=SKILL_CREATOR_BODY,
        ),
        replace=True,
    )
