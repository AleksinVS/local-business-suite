# TASK_ACCEPTANCE.06 — AI gateway и доставка agent-runtime

Решение: **APPROVE для технической реализации и тестового среза**.

По `EXECUTOR_REPORT.06-ai-agent-runtime-delivery.md` приняты read-only gateway
с явным allowlist, service-token boundary, strong ETag, schema/hash checks,
атомарная замена last-known-good aggregate snapshot и fail-closed поведение при
ошибке/устаревании. Git-static security contracts не передаются через legacy
runtime files; DB-effective chat settings доставляются тем же проверяемым
контуром. Identity и tool/code parity остаются под code review.

Ограничения решения:

- production gateway и приватный allowlist не переключались;
- AG-UI/CopilotKit dependencies и wire contract не менялись;
- PostgreSQL recovery drill и полный `make verify-full` остаются частью package08;
- acceptance означает техническую готовность, не production cutover.

Остаточный риск: перед эксплуатационным включением нужны deployment backup,
restart всех consumers, gateway smoke и наблюдение на целевом профиле.
