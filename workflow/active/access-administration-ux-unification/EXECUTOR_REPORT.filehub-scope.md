# Executor report: filehub scope boundary (17b-C)

## Result

Закрыт контур автоупорядочивания файлов `apps.filehub`:

- добавлены scoped-селекторы для полной области источника и для объектного доступа к файлу;
- экран обзора, размещения пользователя, предложения и задания теперь не показывают данные вне области текущего пользователя;
- доступ к одному объекту через adapter-check не открывает метаданные всего источника;
- решение по предложению и создание заданий выполняются одной actor-aware транзакционной командой с повторной проверкой активного пользователя, технической группы, продуктового права и source scope;
- физический перенос принимает только точный непустой стабильный список `file_ids`, проверяет наличие, принадлежность источнику, текущий доступ и целостность всей партии; частичные задания не создаются;
- worker атомарно захватывает `APPROVED` job условным обновлением до `COPY_STAGED`; повторный worker или прямой незахваченный запуск отклоняется.
- публичный bootstrap-метод создает только `PLANNED`; `APPROVED` создается только внутренним batch-путем после actor-aware решения;
- повторное построение не переоткрывает финальное предложение: создается новая версия с новым membership fingerprint;
- физический перенос после атомарного создания набора выполняется независимо по заданиям. Частичный физический успех не маскируется как all-or-nothing: состояние каждого job (`FAILED`, `NEEDS_REVIEW`, `MANAGED_ACTIVE`, `SOURCE_QUARANTINED`) является явной точкой восстановления и повторного ревью.

## Измененные файлы

- `apps/filehub/selectors.py`
- `apps/filehub/admin.py`
- `apps/filehub/views.py`
- `apps/filehub/file_organization_stats.py`
- `apps/filehub/file_organization_move.py`
- `apps/filehub/file_organization.py`
- `apps/filehub/management/commands/memory_file_auto_organization_e2e.py`
- `apps/filehub/tests.py` — 27 тестовых методов, включая регрессионную матрицу actor/access-lock, duplicate jobs, stale source chain/path, canonical backend, recovery/purge, actorless usage, terminal proposal, foreign dashboard relations, readonly Admin, все статусы source, snapshot tamper и lock-order проверки.

## Проверки

- `.venv/bin/python -m compileall -q apps/filehub` — успешно.
- Ранее целевой набор из 13 тестов проходил. После добавления регрессионной матрицы тесты не запускались по условию текущего окна; перед приемкой требуется последовательный запуск расширенного набора (21 метод).

## Остаточный риск

Транзакционное условное обновление claim и token ownership проверены на уровне БД; отдельная многопоточность worker должна быть дополнительно покрыта интеграционным запуском на целевой PostgreSQL. Публичного low-level API для произвольного `APPROVED` больше нет: bootstrap создает только `PLANNED`, а batch-команда и HTTP-решение выполняют полную проверку полномочий.

## Correction 17b-C

После независимого ревью устранены дополнительные обходы:

- удален caller-controlled `_locked`; публичная batch-команда всегда перечитывает и блокирует proposal;
- `APPROVED` создается только внутренним batch-helper, bootstrap API создает только `PLANNED`;
- идемпотентный job не сбрасывает активное или конечное состояние;
- proposal rebuild не переоткрывает финальные решения;
- membership хранит точный список и fingerprint, включая файлы из валидных placement/usage-event связей;
- source-wide доступ требует полного текущего покрытия связанных файлов;
- пользовательское размещение выполняется actor-aware транзакционной командой;
- claim token и execution marker защищают от повторного выполнения одного задания;
- stale `COPY_STAGED` переводится в `NEEDS_REVIEW`: обычный claim получает `stale_copy_staged_claim`, а оставшийся execution marker — `stale_execution_started_manual_reconciliation`; автоматический повтор физического ввода-вывода не выполняется;
- перед файловым вводом-выводом повторно проверяются связи, версия, активное размещение, корень источника, символические ссылки, размер и хеш;
- профиль обязан принадлежать тому же источнику.
- все actor-aware записи получают общий межпроцессный lock до транзакции; nested decision/jobs и personal placement/usage используют locked-helper без повторного file-lock;
- worker не принимает профиль от вызывающего кода, использует canonical profile источника и переводит stale claim/config/backend/path ошибки в `NEEDS_REVIEW`;
- claim проверяет отсутствие другого нерешенного задания для того же stable file identity;
- purge подтверждает containment managed root и успешное фактическое отсутствие quarantine-файла.
- Django Admin разделен на резервные справочники (изменение только active superuser) и operational/audit-модели (полностью readonly, включая superuser); физическое решение доступно только actor-aware сервису.
- Канонический lock protocol зафиксирован как `actor -> source -> proposal -> files(id) -> jobs(id) -> placements`; предварительное чтение внешнего ключа proposal/job выполняется без блокировки, затем relation перечитывается после блокировки source. Worker/recovery используют `select_for_update` и conditional state transition.
- decision хранит immutable `approved_snapshot` с source, bucket, точным membership fingerprint и хешами/размерами версий; создание jobs сверяет snapshot с текущими данными.
- stale recovery охватывает `COPY_STAGED`, `VERIFIED`, `MANAGED_ACTIVE`, сохраняет execution/phase markers и переводит промежуточный side-effect state в `NEEDS_REVIEW`.
- dashboard отбрасывает пустые, неполные и foreign membership proposals; source-wide операции fail closed для пустых и disabled sources.
- source-wide доступ и профиль требуют `MemorySource.Status.ENABLED`; `DISABLED`, `MISSING_ADAPTER` и `ERROR` закрыты даже для superuser.
- claim, full execution и stale recovery проходят под единым межпроцессным lock с execution lease; purge имеет отдельную recoverable `PURGE_STARTED` фазу и token-conditional finalize.
- usage events перечитывают и блокируют fresh source/file/view rows после access lock; fallback source object допускает только текущий `SOURCE_FS/SOURCE_CURRENT/ACTIVE` placement.

После последнего correction тесты намеренно не запускались: ожидается отдельное последовательное тестовое окно приемки. Добавлены проверки readonly Admin, всех статусов source, empty/disabled source, snapshot tamper, recovery всех промежуточных фаз и сохранения execution marker. Выполнены только `compileall` и `git diff --check`.

## Финальная коррекция и проверка

- повторное обнаружение исходного файла больше не возвращает объект из
  `MANAGED_ACTIVE` в исходное состояние;
- частичный сбой с уже активным managed placement восстанавливает указатель
  объекта на managed placement и понижает исходное размещение до истории;
- операции sync/baseline/incoming/stats блокируют свежую строку источника;
- физический worker не удерживает транзакцию во время файлового ввода-вывода,
  но повторно проверяет включённость источника до и после копирования и
  карантина;
- добавлены регрессии отключения источника во время обеих физических фаз.

После двух дополнительных циклов независимой критики:

- все штатные переходы `MemorySource.status` сериализованы тем же lock, что и
  FileHub worker; envelope и ИИ-память не включают отключённый источник;
- incoming использует canonical containment, запрет follow-symlink, снимок
  файлового дескриптора и повторную проверку пути; secret scan читает тот же
  безопасный снимок;
- карантин проверяет хеш/размер до и после перемещения, а purge — до удаления;
- purge фиксирует committed-фазу `PURGE_IO` до unlink и восстанавливает
  `placement/job/lifecycle`, если процесс упал после удаления файла;
- прямая execution-команда проверяет enabled source до первой записи manifest;
- индекс ИИ-памяти держит одну блокировку источника на всю операцию без
  повторного захвата.

`make verify-fast TEST_SCOPE=apps/filehub/tests.py`: 42 теста и 24 вложенных
сценария успешно. `make verify-profile PROFILE=memory`: 153 теста и 61
вложенный сценарий успешно, архитектурные контракты валидны. Сквозная команда
`memory_file_auto_organization_e2e` успешно завершила сценарий и очистила
временные данные.

Финальная проверка жизненного цикла закрыла прямые маршруты discovery,
ingestion, bootstrap, reindex, external landing/queue/tombstone и read fallback:
отключенный источник не читается и не изменяется даже резервным
суперпользователем, а чтение не создает поисковые документы. Независимый
критик подтвердил отсутствие незакрытых S1/S2.
