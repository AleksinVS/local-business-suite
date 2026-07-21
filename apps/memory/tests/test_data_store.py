"""Тесты заглушки data store памяти."""
from apps.memory.tests._common import *  # noqa: F401,F403


class MemoryDataStoreStubTests(TestCase):
    """Data-store interface is pinned as deferred debt (ADR-0030 P07).

    The stubs must exist and raise NotImplementedError, and must not be wired
    into any runtime path yet (stages 5a/5b are managed debt).
    """

    def test_capture_and_query_are_deferred_stubs(self):
        from apps.memory import data_store

        with self.assertRaises(NotImplementedError):
            data_store.capture("fx_rates", {"date": "2026-07-04", "pair": "USD/RUB", "value": "105"})
        with self.assertRaises(NotImplementedError):
            data_store.query_dataset("fx_rates", "latest", {"pair": "USD/RUB"})

    def test_debt_markers_present(self):
        import pathlib

        import apps.memory

        # Корень приложения памяти берём из самого пакета, а не из
        # ``__file__.parent``: после разбиения tests.py на пакет ``tests/`` файл
        # теста лежит на уровень глубже, и относительный расчёт пути сломался бы.
        memory_dir = pathlib.Path(apps.memory.__file__).resolve().parent
        text = "\n".join(
            p.read_text(encoding="utf-8")
            for p in memory_dir.rglob("*.py")
            if "migrations" not in p.parts and "tests" not in p.parts
        )
        # Two 5a markers (remember routing + reconcile registry) and one 5b (reflection).
        self.assertEqual(text.count("DEBT(ADR-0030-5a)"), 2)
        self.assertEqual(text.count("DEBT(ADR-0030-5b)"), 1)
