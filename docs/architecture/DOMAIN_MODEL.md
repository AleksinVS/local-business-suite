# Domain Model

The platform uses shared building blocks and bounded modules.

Shared entities:

- users and groups from Django auth;
- hierarchical departments from `apps.core`;
- versioned role and workflow rules from `config`.

Current domain modules:

- `inventory`: tracked assets and directory records;
- `workorders`: requests, transitions, comments, attachments and board columns;
- `analytics`: operational dashboards over curated reporting data.

Expected invariant:

- operational models own transactional truth;
- analytics consume exports, not live write-heavy tables;
- shared dictionaries should be normalized once and reused by modules.
