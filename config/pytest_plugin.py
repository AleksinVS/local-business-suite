"""Проектные проверки структуры набора pytest."""

from collections.abc import Iterable

import pytest


PRIMARY_MARKERS = frozenset({"unit", "integration"})


def primary_marker_errors(items: Iterable[pytest.Item]) -> list[str]:
    """Возвращает ошибки для тестов без единственного основного маркера."""

    errors: list[str] = []
    for item in items:
        markers = {marker.name for marker in item.iter_markers()}
        primary = sorted(PRIMARY_MARKERS.intersection(markers))
        if len(primary) == 1:
            continue
        if not primary:
            errors.append(f"{item.nodeid}: отсутствует marker unit/integration")
        else:
            errors.append(f"{item.nodeid}: одновременно заданы {', '.join(primary)}")
    return errors


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    errors = primary_marker_errors(items)
    if errors:
        details = "\n".join(f"  - {error}" for error in errors[:25])
        remaining = len(errors) - 25
        if remaining > 0:
            details += f"\n  - ... и еще {remaining}"
        raise pytest.UsageError(
            "Каждый тест должен иметь ровно один основной marker "
            f"unit/integration:\n{details}"
        )
