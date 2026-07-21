# Retrospective: Settings Center GUI

Статус: implemented; owner review pending.

## What Worked

- The accepted descriptor architecture fit the existing contract-driven project structure.
- Reusing Django templates/HTMX kept the first GUI small while preserving service-layer write paths.
- Existing memory `scope_tokens` fields made ACL inheritance mostly an ingestion concern.

## What Changed From Plan

- The contextual help mini-chat is descriptor-aware and safe, but does not yet call a production LLM by default.
- ACL inheritance starts with a replaceable normalized metadata adapter instead of a native Windows ACL reader.
- `.env` flow implements status/proposal; direct local-file mutation remains intentionally out of the production path.

## Follow-up Work

- Add native Windows/UNC ACL collector for production service accounts.
- Add richer field-level forms for high-value memory/AI settings instead of full JSON editing.
- Route contextual help through a trusted local/admin LLM profile after prompt and audit hardening.
