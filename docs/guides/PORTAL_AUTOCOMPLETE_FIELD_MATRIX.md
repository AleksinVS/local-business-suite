# Матрица автодополнения пользовательских полей портала

- Статус: принятая исполнительная матрица, 2026-09-04
- Решение: ADR-0049
- Владелец актуализации: workflow `warehouse-ux-simplification`, пакеты 01, 07a, 07b и 08

Матрица охватывает основной пользовательский UI, а не резервный Django Admin.
Для `entity` клиент отправляет скрытый идентификатор, а сервер повторно проверяет
его через scoped queryset или доменную политику. Для `suggestion` новый текст
разрешён. Даты, числа, флаги, файлы, пароли и многострочный текст не являются
кандидатами на автодополнение; персональные данные не подсказываются.

## Общая основа

| Область | Поле | Режим | Поставщик / источник | Контекст и защита | Статус |
| --- | --- | --- | --- | --- | --- |
| `core.DepartmentForm` | родитель | entity | `core.departments` | область видимости пользователя; исключить себя и потомков | implemented 08 |
| любой модуль | подразделение | entity | доменный provider | actor scope + active; конкретные формы перечислены ниже | implemented by domain rollout |
| любой модуль | пользователь/исполнитель | entity | доменный provider | только назначаемые/видимые пользователи; конкретные формы перечислены ниже | implemented by domain rollout |
| любой модуль | короткий enum/status | fixed | model/contract choices | не заменять поиском | accepted exception |
| любой модуль | дата, количество, флаг, файл, пароль, textarea | specialized | специализированный виджет | autocomplete неприменим | accepted exception |

## Склад

| Экран | Поле | Режим | Зависимости / автозаполнение | Статус |
| --- | --- | --- | --- | --- |
| документ | подразделение | entity | `warehouse.department`, операционная область | implemented 04/08 |
| строка документа | позиция | entity | `warehouse.item`, активный каталог | implemented 04/08 |
| строка документа | серия | suggestion | `warehouse.series`, позиция + подразделение; отдельной таблицы серий нет | implemented 03/04 |
| строка расхода | доступный адрес/остаток | entity | позиция, подразделение, серия и источник; FEFO, только положительный `available` | implemented 04/08 |
| строка документа | источник финансирования | entity | `warehouse.source`, только активные | implemented 04/08 |
| строка документа | исходный/целевой адрес | entity | `warehouse.location`, операция + active purpose; POST повторяет проверку | implemented 04/08 |
| список остатков | подразделение, склад, адрес, позиция, категория, источник, серия | entity/suggestion | `warehouse.stock_*`, область просмотра; серия — текстовая подсказка; фильтры URL и страницы | implemented 05/06/08 |
| перемещение | склад/адрес назначения | entity | `warehouse.relocation_*`, операционная область выбранных строк; зависимый адрес | implemented 05/08 |
| склады/адреса | подразделение, склад, адрес приёмки | entity | `warehouse.manage_*`, область управления адресами | implemented 06/08 |
| номенклатура | категория, единица | entity | `warehouse.catalog_*`, глобальное право складского администратора; active-only suggestions | implemented 06/08 |
| отчёты и профили | подразделение | entity | раздельные `warehouse.report_department` и `warehouse.report_profile_department` | implemented 06/08 |
| отчёты | период/дата | specialized | date inputs | accepted exception |

Отдельный экран регистрации серии и provider на основе самостоятельной таблицы
серий запрещены ADR-0050.

## Медицинские изделия

| Форма | Поле | Режим | Источник / ограничение | Статус |
| --- | --- | --- | --- | --- |
| `MedicalDeviceForm` | подразделение | entity | `inventory.department`, visible departments | implemented 07a |
| `MedicalDeviceForm` | наименование | suggestion | видимые active изделия; новый текст допустим | implemented 07a |
| `MedicalDeviceForm` | производитель | suggestion | distinct по видимым active изделиям | implemented 07a |
| `MedicalDeviceForm` | страна производства | suggestion | distinct по видимым active изделиям | implemented 07a |
| `MedicalDeviceForm` | модель | suggestion | производитель + видимые active изделия | implemented 07a |
| `MedicalDeviceForm` | адрес/место | suggestion | подразделение + видимые active изделия | implemented 07a |
| `MedicalDeviceForm` | тип и рабочий статус | fixed | model choices | accepted exception |
| `MedicalDeviceForm` | серийный/инвентарный/регистрационный номер | specialized text | уникальный идентификатор, подсказки не нужны | accepted exception |

## Заявки

| Форма | Поле | Режим | Источник / ограничение | Статус |
| --- | --- | --- | --- | --- |
| создание заявки | подразделение | entity | `workorders.department`, creation scope | implemented 07a |
| создание заявки | изделие | entity | `workorders.device`, visible/creation scope + department | implemented 07a |
| создание/изменение | доска | entity | `workorders.board`, visible boards | implemented 07a |
| изменение | исполнитель | entity | `workorders.assignee`, active users for actors with assignment permission | implemented 07a |
| изменение | подразделение/изделие | entity | update providers, archived current device preserved | implemented 07a |
| создание/изменение | приоритет | fixed | небольшой enum | accepted exception |
| описание/комментарий | текст | specialized | textarea | accepted exception |

## Лист ожидания

| Форма | Поле | Режим | Причина | Статус |
| --- | --- | --- | --- | --- |
| запись | услуга | fixed или entity после роста справочника | сейчас `SERVICE_CHOICES`; повторно оценить размер | accepted exception 07a — компактный enum |
| запись | ФИО, телефон, дата рождения | excluded-sensitive | нельзя предлагать других пациентов | accepted exception |
| запись | даты | specialized | date input | accepted exception |
| запись | статус | fixed | небольшой enum | accepted exception |
| запись | комментарий | specialized | textarea | accepted exception |

## Доступ, пользователи и настройки

| Форма | Поле | Режим | Источник / ограничение | Статус |
| --- | --- | --- | --- | --- |
| пользователь | подразделение | entity | `accounts.department`; только активный superuser, серверная форма повторно проверяет `available_user_departments()` | implemented 07b |
| роль | пользователи | entity add-one + removable chips | `accounts.role_principal`; только активные управляемые principals, target-dependent privilege ceiling; полный список не рендерится | implemented 07b |
| пользователь | роли | fixed multi-select | `assignable_role_names_for_actor`; контрактный каталог ролей ограничен и весь видимый набор нужен для безопасного сравнения текущего состояния | accepted exception 07b — bounded contract list |
| технические группы памяти | группы | fixed multi-select | `memory_group_choices`; небольшой закрытый технический каталог, запись только через сервис памяти | accepted exception 07b — bounded contract list |
| AD link | provider/status | fixed | небольшой enum | accepted exception |
| AD link | subject/upn/dn/domain | excluded-sensitive | не предлагать внешние идентичности | accepted exception |
| пароль, JSON payload, secret/env value | значение | excluded-sensitive/specialized | никогда не включать в suggestions | accepted exception |
| capability scope | значение | fixed | contract choices | accepted exception |

## FileHub, память, аналитика и AI

Резервный Django Admin не входит в матрицу. Пользовательские страницы этих
модулей обследованы отдельно с учётом ACL и чувствительности данных.

| Область | Поле | Режим | Ограничение | Статус |
| --- | --- | --- | --- | --- |
| FileHub | файл в личном виртуальном размещении | entity | `filehub.file_object` + `visible_file_objects`; результат содержит только имя файла и код источника, без physical/raw path; POST повторяет ACL-проверку | implemented 07b |
| FileHub | источник, представление, владелец | n/a | в пользовательских формах выбора нет; источник и владелец выводятся из выбранного файла и текущего пользователя | accepted exception 07b — no selection field |
| Memory review | источник в фильтрах issue/index | entity | `memory.source` + `source_filter_options`; только enabled и доступные по memory ACL источники | implemented 07b |
| Memory review | назначенный эксперт | entity | `memory.issue_assignee` с контекстом доступной issue; `review_issue_queryset` + `assignees_for_issue`; без внешних идентичностей | implemented 07b |
| Memory review | объект и запуск | n/a | в пользовательском UI только безопасное чтение контекста, выбора нет | accepted exception 07b — no selection field |
| Analytics | источник/набор/метрика | n/a | dashboard только читает агрегаты; пользовательских форм редактирования и выбора нет | accepted exception 07b — read-only UI |
| AI user forms | модель/команда | fixed | ограниченные реестры конфигурации; не являются растущими предметными справочниками | accepted exception 07b — fixed registry |
| AI user forms | prompt, title, attachments | specialized | текст/многострочный текст/файл; автодополнение неприменимо, AG-UI wire и зависимости не менялись | accepted exception 07b |
| Notifications | пользовательское устройство | entity только если появится выбор | пользователь видит только свои устройства | accepted exception 07a — выбор отсутствует |

## Приёмочная проверка матрицы

Приёмка 08 не оставила статусов `planned` или `audit`. Реализованные entity-поля
повторно проверяют идентификатор через доменную форму, selector или сервис.
Клавиатурное поведение проверяется общим e2e компонента; HTTP/security-тесты
проверяют предметные области. Отдельные браузерные сценарии склада остаются в
постоянном e2e-наборе и запускаются в CI с авторизованным fixture.
