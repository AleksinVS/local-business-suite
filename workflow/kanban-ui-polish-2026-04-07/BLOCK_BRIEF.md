# Summary
- goal: Improve Kanban board and shared layout by moving branding to header, aligning header borders, and optimizing board grid for 5-column display.
- changes: Move branding from sidebar to site header in templates/base.html and align header borders in app.css.
- changes: Optimize .board-grid CSS calculation in static/src/css/app.css to allow 5 columns without overflow.
- verification: Manual visual check of header alignment and board column display on desktop.
- verification: Run manage.py check to ensure template integrity.
