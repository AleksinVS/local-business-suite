# Retrospective: memory file content search

## Что важно для следующего этапа

- Фрагментный поиск лучше делать через отдельный `MemorySearchSegment` без хранения полного текста.
- Runtime `data/contracts` может быть создан до обновления дефолтных контрактов; операторам нужно синхронизировать или пересоздать runtime contract copy после обновления.
- Production embedding profile нужно включать только после проверки железа и локального model cache.
- Старые индексы должны пересобираться через `memory_reindex --force`, если меняется parser/schema/model version.
