# Executor Report: task-header-rebranding

## Task Summary
- **Block:** kanban-ui-polish-2026-04-07
- **Goal:** Move branding from sidebar to main header and repair app.css layout.

## Changes
### static/src/css/app.css
- Fixed `.app-layout` block by adding the missing closing brace.
- Cleaned up duplicate `.page-shell` rules, ensuring consistent padding using `var(--page-shell-padding)`.
- Added `.brand` class with `font-size: 1.08rem; font-weight: 700; color: var(--text-main);`.
- Added `.site-header-main` flexbox rules to align toggle button, brand, and context.
- Verified `.sidebar-header` and `.site-header` both have `height: 60px;` and `border-bottom: 1px solid var(--border)`.

### templates/base.html
- Removed the brand link from `.sidebar-header`.
- Ensured the brand link in `.site-header-main` is correctly placed after the sidebar toggle.

## Verification
- Ran `./.venv/bin/python manage.py check`: Success.
- Visual structure confirmed: Sidebar (empty header) | Main Content (Header with Toggle + Brand + Breadcrumbs).
