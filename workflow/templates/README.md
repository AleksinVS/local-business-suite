# Workflow Templates

Шаблоны для новых workflow-блоков.

Минимальная структура сложного блока:

```text
workflow/active/<block-id>/
  BLOCK_BRIEF.md
  ARCHITECT_PLAN.json
  task-packets/
    <task-id>.json
  EXECUTOR_REPORT.<task-id>.md
  TASK_ACCEPTANCE.<task-id>.md
  RETROSPECTIVE.md
```

Если блок небольшой, структуру можно упростить, но цель, границы, проверки и результат приемки должны быть понятны из файлов блока.
