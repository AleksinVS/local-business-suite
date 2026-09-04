# Executor report: 08a — автодополнение складских справочников

## Выполнено

- Добавлены bounded providers для фильтров списка остатков: подразделение,
  склад, адрес, номенклатура, категория и источник финансирования. Выборки
  строятся от положительных доступных остатков в области просмотра; чужие,
  архивные и карантинные объекты не попадают в подсказки.
- В фильтрах сохранены URL-параметры и совместимость со старым текстовым
  параметром `item`; entity-выбор использует `item_id`. Серия осталась обычным
  текстом с подсказками.
- Добавлены scoped providers для отчётного подразделения, подразделения и
  склада/адреса в формах управления, а также active category/unit для формы
  номенклатуры. Формы передают actor и сохраняют серверную ModelChoice
  валидацию.
- Relocation destination providers и подписанный selection token не изменялись;
  существующие зависимые warehouse/location подсказки и повторная проверка
  POST сохранены.
- Список остатков всегда использует область просмотра, а элементы перемещения
  выводятся построчно только для подразделений из операционной области. Поэтому
  сочетание глобального просмотра с локальными операциями не скрывает данные и
  не расширяет право записи.
- Обычные операции сервером ограничены активными адресами `available`.
  `unassigned` разрешён только явному legacy-импорту начального остатка от
  активного superuser и с `external_source_id=legacy:*`.
- Текущие архивные категория, единица, позиция и источник сохраняются при
  неизменённом редактировании, но не предлагаются для нового выбора.
- Поставщики подразделения для просмотра отчёта и редактирования профиля
  отчёта разделены по своим capabilities.
- Дополнительно закрыт cross-portal provider `core.departments`: parent
  подразделения использует видимый actor scope и исключает текущий узел и его
  потомков, а POST повторно проверяется той же формой.

## Файлы

Изменены `apps/warehouse/autocomplete.py`, `apps/warehouse/forms.py`,
`apps/warehouse/relocation_selectors.py`, `apps/warehouse/relocation_views.py`,
`apps/warehouse/report_forms.py`, `apps/warehouse/urls.py`,
`templates/warehouse/crud.html`, `templates/warehouse/catalog.html`,
`templates/warehouse/report.html`, `templates/warehouse/relocation/stock_list.html`.
Для cross-portal gap изменены `apps/core/autocomplete.py`, `apps/core/apps.py`,
`apps/core/forms.py`, `apps/core/views.py`, `apps/core/urls.py`,
`templates/core/department_form.html`, `apps/core/tests.py` и описания модулей.

## Проверки

- `manage.py check` — успешно; остаётся штатное предупреждение
  `settings_center.W002`.
- `compileall -q apps/core apps/warehouse` — успешно.
- Core parent provider/валидация: 2 passed.
- Relocation URL smoke: 1 passed после исправления сохранения legacy-параметра
  `item`.
- Warehouse security/report autocomplete subset: 4 passed.
- После независимой критики: 15 рисковых HTTP/security-тестов — успешно.
- Полный набор `apps/warehouse` — успешно, 4 PostgreSQL-only теста
  конкурентности пропущены на SQLite.
- `warehouse_acceptance_e2e` после чистого применения миграций — успешно.

## Остаточные риски

- Полный браузерный keyboard e2e для новых фильтров не запускался: в текущем
  окружении нет подготовленного авторизационного fixture. HTTP/security
  проверки и реальный render stock URL выполнены.
- Адрес назначения relocation имеет provider, но отдельный e2e сценарий
  с выбором клавиатурой остаётся частью общей UI-приёмки.
- В рабочем дереве есть параллельные изменения других агентов; коммит, merge,
  pull и push не выполнялись.
