# Матрица автодополнения пользовательских полей

- Статус: начальная исполнительная матрица
- Дата: 2026-09-02
- Решение: ADR-0049
- Владелец актуализации: workflow `warehouse-ux-simplification`, пакеты 01, 07a, 07b и 08

## Правила классификации

- `entity` — обязательно выбрать доступный объект; отправляется его id.
- `suggestion` — допускается новый текст, существующие значения предлагаются.
- `fixed` — небольшой закрытый список; autocomplete не нужен.
- `specialized` — дата, число, флаг, файл, пароль или многострочный текст.
- `excluded-sensitive` — подсказки могли бы раскрыть персональные данные,
  секреты или внешнюю идентичность.

Матрица охватывает основной пользовательский UI, а не резервный Django Admin.
Перед реализацией исполнитель сверяет её с актуальными views/forms/templates и
добавляет пропущенные поля. Пустая строка или отсутствие формы не считается
доказательством отсутствия значимого поля.

## Общая основа

| Область | Поле | Режим | Поставщик / источник | Контекст и защита | Статус |
| --- | --- | --- | --- | --- | --- |
| `core.DepartmentForm` | родитель | entity | `core.departments` | исключить себя и потомков | planned |
| любой модуль | подразделение | entity | доменный provider, не один глобальный queryset | actor scope + active | planned |
| любой модуль | пользователь/исполнитель | entity | доменный provider | только назначаемые/видимые пользователи | planned |
| любой модуль | короткий enum/status | fixed | model/contract choices | не заменять поиском | accepted exception |
| любой модуль | дата, количество, флаг, файл, пароль, textarea | specialized | специализированный виджет | autocomplete неприменим | accepted exception |

## Склад

| Экран | Поле | Режим | Зависимости / автозаполнение | Статус |
| --- | --- | --- | --- | --- |
| документ | подразделение | entity | scope; скрыть/заполнить при одном варианте | planned 04 |
| строка документа | позиция | entity | active catalog; поиск по коду, полному и краткому названию, производителю | planned 04 |
| строка документа | серия | suggestion | выбранная позиция; selection заполняет срок | planned 03/04 |
| строка расхода | доступный остаток | entity | позиция, подразделение, дата; FEFO, available only | planned 04 |
| строка документа | источник финансирования | entity | active; при расходе заполняется из остатка | planned 04 |
| строка документа | исходный/целевой адрес | entity | подразделение, операция, active purpose | planned 04 |
| список остатков | склад, адрес, позиция, категория, источник, серия | entity/suggestion | URL filters + scope | planned 05/06 |
| перемещение | склад назначения | entity | то же подразделение, active, подходящий адрес | planned 05 |
| перемещение | адрес назначения | entity | показывать только при неоднозначности | planned 05 |
| склады/адреса | подразделение, склад | entity | manage-locations scope | planned 06 |
| номенклатура | категория, единица | entity | active catalog | planned 06 |
| отчёты | подразделение | entity | warehouse view scope | planned 06 |
| отчёты | период/дата | specialized | date inputs | accepted exception |

Отдельный экран регистрации серии и provider на основе самостоятельной таблицы
серий запрещены ADR-0050.

## Медицинские изделия

| Форма | Поле | Режим | Источник / ограничение | Статус |
| --- | --- | --- | --- | --- |
| `MedicalDeviceForm` | подразделение | entity | creation/visible department selectors | planned 07a |
| `MedicalDeviceForm` | наименование | suggestion | видимые существующие названия; новый текст допустим | audit in 07a |
| `MedicalDeviceForm` | производитель | suggestion | distinct по видимым изделиям | planned 07a |
| `MedicalDeviceForm` | страна производства | suggestion | distinct по видимым изделиям | planned 07a |
| `MedicalDeviceForm` | модель | suggestion | производитель + видимые изделия | planned 07a |
| `MedicalDeviceForm` | адрес/место | suggestion | подразделение + видимые изделия | planned 07a |
| `MedicalDeviceForm` | тип и рабочий статус | fixed | model choices | accepted exception |
| `MedicalDeviceForm` | серийный/инвентарный номер | specialized text | уникальный идентификатор, подсказки не нужны | accepted exception |

## Заявки

| Форма | Поле | Режим | Источник / ограничение | Статус |
| --- | --- | --- | --- | --- |
| создание заявки | подразделение | entity | visible departments | implemented locally; migrate 01 |
| создание заявки | изделие | entity | visible devices; name/inventory/serial search | implemented locally; migrate 01 |
| создание/изменение | доска | entity или fixed при малом наборе | visible boards; скрыть при одном | planned 07a audit |
| изменение | исполнитель | entity | assignable users for board/department | planned 07a |
| изменение | подразделение/изделие | entity | те же providers и согласованность пары | planned 07a |
| создание/изменение | приоритет | fixed | небольшой enum | accepted exception |
| описание/комментарий | текст | specialized | textarea | accepted exception |

## Лист ожидания

| Форма | Поле | Режим | Причина | Статус |
| --- | --- | --- | --- | --- |
| запись | услуга | fixed или entity после роста справочника | сейчас `SERVICE_CHOICES`; повторно оценить размер | audit 07a |
| запись | ФИО, телефон, дата рождения | excluded-sensitive | нельзя предлагать других пациентов | accepted exception |
| запись | даты | specialized | date input | accepted exception |
| запись | статус | fixed | небольшой enum | accepted exception |
| запись | комментарий | specialized | textarea | accepted exception |

## Доступ, пользователи и настройки

| Форма | Поле | Режим | Источник / ограничение | Статус |
| --- | --- | --- | --- | --- |
| пользователь | подразделение | entity | `available_user_departments(actor/target)` | planned 07b |
| роль | пользователи | entity multi-select | только управляемые principals, privilege ceiling | planned 07b |
| пользователь | роли | entity multi-select | `assignable_role_names_for_actor` | planned 07b |
| технические группы памяти | группы | entity multi-select или текущий компактный список | только разрешённые memory groups | audit 07b |
| AD link | provider/status | fixed | небольшой enum | accepted exception |
| AD link | subject/upn/dn/domain | excluded-sensitive | не предлагать внешние идентичности | accepted exception |
| пароль, JSON payload, secret/env value | значение | excluded-sensitive/specialized | никогда не включать в suggestions | accepted exception |
| capability scope | значение | fixed | contract choices | accepted exception |

## FileHub, память, аналитика и AI

Эти модули имеют много резервных Django Admin autocomplete, но пакет 07b должен
отдельно обследовать пользовательские страницы. Начальные обязательные кандидаты:

| Область | Поле | Режим | Ограничение | Статус |
| --- | --- | --- | --- | --- |
| FileHub | источник, представление, файл, владелец | entity | domain selectors + source scope | audit 07b |
| Memory review | источник, объект, запуск, назначенный эксперт | entity | memory ACL; без raw path/PII | audit 07b |
| Analytics | источник/набор/метрика, если редактируются в UI | entity | analytics authority | audit 07b |
| AI user forms | модель/профиль | fixed/entity по реестру | не менять AG-UI contract | audit 07b |
| Notifications | пользовательское устройство | entity только если появится выбор | пользователь видит только свои устройства | audit 07a |

## Приёмочная проверка матрицы

Для каждой строки со статусом `planned` или `audit` пакет 08 требует:

1. ссылку на форму/шаблон;
2. provider code или окончательное обоснование исключения;
3. selector/policy и правила active/archive;
4. поисковые поля и индексы;
5. unit/security тест;
6. хотя бы один представительный keyboard e2e на модульную группу.

Завершённая матрица не должна содержать статусы `planned` или `audit`.

