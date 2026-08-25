# ADR-0002: Config-driven Policy And Workflow

## Status

Accepted

## Decision

Store role capabilities and workflow transitions in versioned JSON contracts instead of hardcoding them in Python branches.

## Consequences

- mutable rules become reviewable in git;
- validation becomes mandatory;
- future roles and states can be added without rewriting core policy flow.

## Clarification 2026-08-25

`Config-driven` не означает, что весь язык авторизации становится изменяемой
runtime-настройкой. Роли и значения уже зарегистрированных прав могут
изменяться через проверяемый runtime-контракт. Код capability, тип значения и
его серверный смысл изменяются только через Git, ревью, тесты и deployment.
Принятый ADR-0043 сохраняет текущие короткие capability-коды и не вводит новый
DSL, compiler или registry evaluator.
