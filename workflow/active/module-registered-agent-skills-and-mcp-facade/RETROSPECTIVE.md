# Retrospective

Дата: 2026-05-29.

## Что получилось

- Универсальный механизм открытия объектов теперь опирается на module skills и общий `ui.open_right_panel`, а не на доменную ветку в runtime graph.
- Runtime skills можно добавлять через файловый контракт без restart.
- Администраторский путь создания skills отделен от skill body: запись идет только через audited tool.
- MCP расширен безопасными resources без смены внутреннего транспорта sidebar-чата.

## Что оставлено на потом

- `ui.resolve_open_target` и отдельный resolver registry.
- UI Settings Center для runtime skills: просмотр, disable/delete, история.
- Полная генерация MCP tools из registry вместо typed wrappers.
- MCP prompts и внешний auth/deployment profile.
- Scripts/assets для runtime skills после отдельного security-review.

## Наблюдения

- Confirmation flow для `ai.skills.create_or_update` сохраняет прежнюю модель write tools. Это чуть длиннее для администратора, но лучше согласуется с текущим audit-подходом.
- `waiting_list.get` намеренно возвращает безопасные метаданные без телефона и даты рождения пациента; для открытия сайдбара агенту достаточно `id`.
