# Доводка памяти после ревью целевой архитектуры (memory-alignment-hardening)

## Статус

Active planning. Готов к исполнению. Создан 2026-07-06.

- Основание: дополнение 2026-07-06 в `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` (раздел «Требуемые действия», «Дополнение 2026-07-06») и остаточные риски из `workflow/archive/2026/memory-hybrid-knowledge-v05-alignment/RETROSPECTIVE.md`.
- Workflow-блок: `workflow/active/memory-alignment-hardening/` (3 task packets).
- Блок выравнивания ADR-0030 уже исполнен и заархивирован; этот блок закрывает найденные после исполнения пробелы и не меняет принятую архитектуру.

## Цель

Закрыть семь пробелов, найденных ревью целевой архитектуры после исполнения блока выравнивания:

1. LF-нормализация канона (`.gitattributes`, запись с LF, хэши по LF-содержимому) — без нее git-autocrlf на Windows дает ложные hash mismatch.
2. Гарантия отсутствия петли `needs-reconcile` (пометка страницы reconciler'ом не должна выглядеть новым изменением).
3. Синглтон `memory_reconcile` (advisory lock на PostgreSQL, lock-файл на dev SQLite).
4. Инструкция эмиссии `relations:` для семантического прохода — сейчас словарь и материализатор есть, а производителя рёбер нет.
5. Golden set `MemoryEvalCase` (не менее 20 кейсов) + периодический `memory_eval` — иначе критерии возврата профилей и графа никогда не сработают.
6. Матрица восстановления в `docs/deployment/MEMORY_DEPLOYMENT.md` (что резервируется, что пересобирается).
7. Остатки ретроспективы: чистка `ranking_profiles` в `contracts/ai/memory_profiles.json`, фильтр очереди в review-UI.

## Не цели

- Не менять архитектуру ADR-0030 и формат frontmatter.
- Не реализовывать data store (5а/5б), graph runtime search, профили ранжирования, фрагментный поиск.
- Не выполнять массовую перезапись существующих файлов знаний (LF-нормализация применяется при следующей записи каждой страницы).
- Не менять права доступа, trust-гейты, secret handles.

## Пакеты

| Packet | Содержание |
|---|---|
| `01-canon-line-endings-and-reconciler-guards` | `.gitattributes`, LF-нормализация записи и хэшей, тест отсутствия петли `needs-reconcile` (+фикс через git-автора `memory-reconciler`, если тест падает), синглтон `memory_reconcile`, тест обеих платформенных веток блокировки |
| `02-eval-golden-set-and-recovery-matrix` | Команда `memory_eval_seed`, черновой golden set (>=20 кейсов) на реальном корпусе, прогон `memory_eval` с отчетом, матрица восстановления в `MEMORY_DEPLOYMENT.md` |
| `03-edge-emission-and-retro-leftovers` | Инструкция эмиссии `relations:` в конфигурации семантического прохода (`knowledge_reflection_worker`), чистка `ranking_profiles` до одного `balanced`, фикс фильтра очереди review-UI |

Порядок: 01 -> 02 -> 03. Пакеты 02 и 03 независимы и могут идти параллельно после 01.

## Проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reconcile --dry-run
python manage.py memory_verify_knowledge_files
python manage.py memory_eval --dry-run
python manage.py memory_alignment_acceptance_e2e
```

## Definition of Done блока

- Все три пакета приняты; полный набор проверок зеленый на SQLite и PostgreSQL.
- Файл знания, записанный из тела с CRLF, содержит только LF и дает тот же content-hash, что LF-вариант.
- Повторный `memory_reconcile` после пометки страницы сообщает ноль изменений; параллельный второй запуск завершается без работы.
- В `MemoryEvalCase` не менее 20 активных кейсов; отчет `memory_eval` приложен к приемке.
- `MEMORY_DEPLOYMENT.md` содержит матрицу восстановления; `MEMORY_MVP_CURRENT_STATE.md` актуализирован.
- Backlog: блок удален после приемки; записи `Later` (профили, graph runtime search) ссылаются на golden set как выполненное предусловие.
