"""Tests for agent-runtime contract path resolution and reread-without-restart
caching (ADR-0031 п.3 шаг 1: "Доставка контрактов в agent-runtime").

Covers:
  - services.agent_runtime.config._resolve_contract / _contract_path:
    runtime-copy preferred when present, default fallback otherwise, env
    override always wins.
  - services.agent_runtime.contract_cache: content cached by
    (st_mtime_ns, st_size, st_ino), invalidated when the file changes,
    including atomic os.replace with an unchanged size/mtime (inode change).
  - end-to-end: a runtime copy that appears *after* the first read is
    picked up without any restart, and path selection is never cached
    permanently.
  - services.agent_runtime.app._log_contract_sources_at_startup: WARNING
    on fallback to default, no warning when a runtime/override copy is used.

Run with: python -m pytest services/agent_runtime/tests/test_contracts.py -v
Or: python -m unittest services.agent_runtime.tests.test_contracts -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ENV_VAR = "LOCAL_BUSINESS_AI_TOOLS_FILE_TEST"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_atomic(path: Path, payload: dict) -> None:
    """Write via the same tmp-file + os.replace pattern Settings Center
    uses for contract writes (ADR-0031/AGENTS.md "atomic write" rule).
    This changes the file's inode even when size/mtime happen to match."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp_path, path)


class ContractResolverTestCase(unittest.TestCase):
    """Tests for config._resolve_contract / config._contract_path."""

    def setUp(self):
        from services.agent_runtime import config, contract_cache

        self.config = config
        contract_cache.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runtime_dir = Path(self._tmp.name) / "data" / "contracts"
        self.default_dir = Path(self._tmp.name) / "contracts"
        self._patchers = [
            patch.object(config, "RUNTIME_CONTRACTS_DIR", self.runtime_dir),
            patch.object(config, "DEFAULT_CONTRACTS_DIR", self.default_dir),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)
        # Make sure no stray env override from the real environment leaks in.
        env_patch = patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop(ENV_VAR, None)

    def test_returns_runtime_copy_when_present(self):
        runtime_file = self.runtime_dir / "ai" / "tools.json"
        default_file = self.default_dir / "ai" / "tools.json"
        _write(runtime_file, {"tools": ["runtime"]})
        _write(default_file, {"tools": ["default"]})

        path, source = self.config._resolve_contract("tools.json", ENV_VAR)

        self.assertEqual(path, runtime_file)
        self.assertEqual(source, self.config.CONTRACT_SOURCE_RUNTIME)
        self.assertEqual(self.config._contract_path("tools.json", ENV_VAR), runtime_file)

    def test_falls_back_to_default_when_runtime_copy_missing(self):
        default_file = self.default_dir / "ai" / "tools.json"
        _write(default_file, {"tools": ["default"]})

        path, source = self.config._resolve_contract("tools.json", ENV_VAR)

        self.assertEqual(path, default_file)
        self.assertEqual(source, self.config.CONTRACT_SOURCE_DEFAULT)

    def test_env_override_wins_even_if_it_does_not_exist(self):
        runtime_file = self.runtime_dir / "ai" / "tools.json"
        _write(runtime_file, {"tools": ["runtime"]})
        override_path = Path(self._tmp.name) / "somewhere-else" / "tools.json"
        os.environ[ENV_VAR] = str(override_path)
        self.addCleanup(os.environ.pop, ENV_VAR, None)

        path, source = self.config._resolve_contract("tools.json", ENV_VAR)

        self.assertEqual(path, override_path)
        self.assertEqual(source, self.config.CONTRACT_SOURCE_OVERRIDE)

    def test_resolution_is_not_memoized_across_calls(self):
        """A runtime copy created after the first resolution must be picked
        up by the very next call — path selection itself must never be
        cached (only the parsed content behind a resolved path is)."""
        default_file = self.default_dir / "ai" / "tools.json"
        _write(default_file, {"tools": ["default"]})

        _, first_source = self.config._resolve_contract("tools.json", ENV_VAR)
        self.assertEqual(first_source, self.config.CONTRACT_SOURCE_DEFAULT)

        runtime_file = self.runtime_dir / "ai" / "tools.json"
        _write(runtime_file, {"tools": ["runtime"]})

        second_path, second_source = self.config._resolve_contract("tools.json", ENV_VAR)
        self.assertEqual(second_source, self.config.CONTRACT_SOURCE_RUNTIME)
        self.assertEqual(second_path, runtime_file)


class ContractCacheTestCase(unittest.TestCase):
    """Tests for contract_cache.load_json_cached()."""

    def setUp(self):
        from services.agent_runtime import contract_cache

        self.contract_cache = contract_cache
        contract_cache.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "tools.json"

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.contract_cache.load_json_cached(self.path)

    def test_second_read_is_served_from_cache(self):
        _write(self.path, {"tools": ["v1"]})

        with patch.object(Path, "read_text", wraps=Path.read_text, autospec=True) as spy:
            first = self.contract_cache.load_json_cached(self.path)
            second = self.contract_cache.load_json_cached(self.path)

        self.assertEqual(first, {"tools": ["v1"]})
        self.assertEqual(second, {"tools": ["v1"]})
        self.assertEqual(spy.call_count, 1, "second read should be served from cache, not disk")

    def test_content_change_invalidates_cache(self):
        _write(self.path, {"tools": ["v1"]})
        first = self.contract_cache.load_json_cached(self.path)
        self.assertEqual(first, {"tools": ["v1"]})

        _write(self.path, {"tools": ["v2", "extra-to-change-size"]})
        second = self.contract_cache.load_json_cached(self.path)

        self.assertEqual(second, {"tools": ["v2", "extra-to-change-size"]})

    def test_atomic_replace_invalidates_cache_even_with_same_mtime_and_size(self):
        """Regression guard for the ADR-0031 rationale: cache key must be
        (st_mtime_ns, st_size, st_ino), not mtime/size alone, because an
        atomic os.replace can leave mtime and size unchanged (same content
        length, coarse filesystem mtime resolution) while still writing to
        a new inode."""
        payload_v1 = {"tools": ["aa"]}
        payload_v2 = {"tools": ["bb"]}  # same JSON length as v1
        self.assertEqual(
            len(json.dumps(payload_v1)), len(json.dumps(payload_v2)),
            "test setup requires equal-length payloads",
        )
        _write(self.path, payload_v1)
        before_stat = self.path.stat()
        first = self.contract_cache.load_json_cached(self.path)
        self.assertEqual(first, payload_v1)

        _write_atomic(self.path, payload_v2)
        # Force mtime_ns to match exactly, isolating inode as the only
        # differing element of the cache key.
        os.utime(self.path, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
        after_stat = self.path.stat()
        self.assertEqual(before_stat.st_mtime_ns, after_stat.st_mtime_ns)
        self.assertEqual(before_stat.st_size, after_stat.st_size)
        self.assertNotEqual(before_stat.st_ino, after_stat.st_ino)

        second = self.contract_cache.load_json_cached(self.path)
        self.assertEqual(second, payload_v2)


class ContractRereadWithoutRestartTestCase(unittest.TestCase):
    """End-to-end: a runtime copy appearing or changing after the agent
    process already read the default (or an earlier runtime version) must
    be picked up on the next request, without restarting the process —
    the scenario described in ADR-0031 п.3 (first-start race with Django,
    and later Settings Center edits)."""

    def setUp(self):
        from services.agent_runtime import config, contract_cache

        self.config = config
        contract_cache.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runtime_dir = Path(self._tmp.name) / "data" / "contracts"
        self.default_dir = Path(self._tmp.name) / "contracts"
        self._patchers = [
            patch.object(config, "RUNTIME_CONTRACTS_DIR", self.runtime_dir),
            patch.object(config, "DEFAULT_CONTRACTS_DIR", self.default_dir),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)
        env_patch = patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop(ENV_VAR, None)

    def _read(self):
        path = self.config._contract_path("tools.json", ENV_VAR)
        return self.config.load_json(path)

    def test_runtime_copy_appearing_after_first_read_is_picked_up(self):
        default_file = self.default_dir / "ai" / "tools.json"
        _write(default_file, {"tools": ["default"]})

        first = self._read()
        self.assertEqual(first, {"tools": ["default"]})

        runtime_file = self.runtime_dir / "ai" / "tools.json"
        _write(runtime_file, {"tools": ["runtime-v1"]})

        second = self._read()
        self.assertEqual(second, {"tools": ["runtime-v1"]})

    def test_runtime_copy_edit_is_picked_up_without_restart(self):
        runtime_file = self.runtime_dir / "ai" / "tools.json"
        _write(runtime_file, {"tools": ["runtime-v1"]})

        first = self._read()
        self.assertEqual(first, {"tools": ["runtime-v1"]})

        _write_atomic(runtime_file, {"tools": ["runtime-v2-edited-via-settings-center"]})

        second = self._read()
        self.assertEqual(second, {"tools": ["runtime-v2-edited-via-settings-center"]})


class StartupContractLoggingTestCase(unittest.TestCase):
    """Tests for app._log_contract_sources_at_startup()."""

    def _get_target(self):
        from services.agent_runtime.app import _log_contract_sources_at_startup
        return _log_contract_sources_at_startup

    def test_warns_when_a_contract_falls_back_to_default(self):
        log_fn = self._get_target()
        fake_sources = [
            {"name": "ai_tools", "path": "/app/data/contracts/ai/tools.json", "source": "runtime"},
            {"name": "ai_task_types", "path": "/app/contracts/ai/task_types.json", "source": "default"},
            {"name": "ai_models", "path": "/app/data/contracts/ai/models.json", "source": "runtime"},
        ]
        with patch("services.agent_runtime.app.describe_contract_sources", return_value=fake_sources):
            with self.assertLogs("services.agent_runtime.startup", level="INFO") as captured:
                log_fn()

        levels = [record.split(":", 1)[0] for record in captured.output]
        self.assertIn("WARNING", levels)
        warning_lines = [line for line in captured.output if line.startswith("WARNING")]
        self.assertTrue(any("ai_task_types" in line for line in warning_lines))

    def test_no_warning_when_all_contracts_resolve_from_runtime(self):
        log_fn = self._get_target()
        fake_sources = [
            {"name": "ai_tools", "path": "/app/data/contracts/ai/tools.json", "source": "runtime"},
            {"name": "ai_task_types", "path": "/app/data/contracts/ai/task_types.json", "source": "runtime"},
            {"name": "ai_models", "path": "/app/data/contracts/ai/models.json", "source": "runtime"},
        ]
        with patch("services.agent_runtime.app.describe_contract_sources", return_value=fake_sources):
            with self.assertLogs("services.agent_runtime.startup", level="INFO") as captured:
                log_fn()

        levels = [record.split(":", 1)[0] for record in captured.output]
        self.assertNotIn("WARNING", levels)
        self.assertTrue(all(level == "INFO" for level in levels))


if __name__ == "__main__":
    unittest.main()
