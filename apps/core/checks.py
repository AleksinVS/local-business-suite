"""Django system checks приложения core.

Здесь живёт валидация бизнес-контрактов, которая раньше выполнялась на импорте
``config/settings.py``. Перенос в system check даёт три выигрыша:

* импорт настроек снова дешёвый и без побочек — его платят все ``manage.py``
  команды, а тяжёлую валидацию ~30 JSON теперь можно выключить штатным
  ``--skip-checks`` / ``SILENCED_SYSTEM_CHECKS``, не трогая код;
* проверка встроена в стандартный конвейер: её выполняет и обычный
  ``manage.py check`` (его зовёт ``make check``), и ``manage.py check --tag
  contracts``, и system-check-фаза перед ``migrate`` в
  ``docker/entrypoint.prod.sh`` — то есть fail-fast на битом контракте сохранён;
* валидаторы не дублируются: check переиспользует ровно ту же логику, что и
  команда ``validate_architecture_contracts`` (единый источник правды по набору
  контрактов и семантическим кросс-проверкам).
"""
from __future__ import annotations

from io import StringIO

from django.core.checks import Error, register


@register("contracts")
def check_architecture_contracts(app_configs, **kwargs):
    """Проверяет бизнес-контракты (``contracts`` tag) через штатную команду.

    Переиспользует ``validate_architecture_contracts`` целиком: инстанцирует
    команду и вызывает её ``handle()`` напрямую. ``handle()`` НЕ запускает
    system-check-фазу (её запускает ``execute()``), поэтому рекурсии
    «check -> команда -> check» не возникает. Любая ошибка контракта поднимается
    командой как исключение и превращается здесь в ``Error`` — тогда
    ``manage.py check`` завершается ненулевым кодом.
    """
    # Импорт внутри функции: модуль checks импортируется из AppConfig.ready до
    # полной готовности реестра приложений, а команда тянет apps.ai/services.
    from apps.core.management.commands.validate_architecture_contracts import Command

    command = Command(stdout=StringIO(), stderr=StringIO())
    try:
        command.handle()
    except Exception as exc:  # noqa: BLE001 — сюда попадают ValidationError/CommandError/OSError и пр.
        return [
            Error(
                f"Бизнес-контракты невалидны: {exc}",
                hint=(
                    "Запустите `python manage.py validate_architecture_contracts` "
                    "для подробностей. При отсутствии рабочих копий контрактов "
                    "выполните `python manage.py bootstrap_runtime`."
                ),
                id="core.E001",
            )
        ]
    return []
