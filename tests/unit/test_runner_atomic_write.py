"""Atomic runner state keeps old bytes on denial and recovers bounded Windows sharing failures."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from quantagent_platform import runner


class RunnerAtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.json"
        self.previous = b'{"previous": true}\n'
        self.path.write_bytes(self.previous)
        self.payload = {"status": "completed", "text": "合成状态"}

    @staticmethod
    def denied(winerror):
        exc = PermissionError("synthetic replacement denied")
        exc.winerror = winerror
        return exc

    def test_transient_windows_denial_retries_then_replaces_complete_json(self):
        original_replace = os.replace
        for winerror in (5, 32):
            with self.subTest(winerror=winerror):
                self.path.write_bytes(self.previous)
                attempts = []

                def replace(source, target):
                    attempts.append((source, target))
                    if len(attempts) <= 2:
                        self.assertEqual(self.path.read_bytes(), self.previous)
                        raise self.denied(winerror)
                    return original_replace(source, target)

                failure = None
                with patch.object(runner.os, "name", "nt"), patch.object(runner.os, "replace", side_effect=replace), patch("time.sleep") as sleep:
                    try:
                        runner._atomic_json_write(self.path, self.payload)
                    except PermissionError as exc:
                        failure = exc
                self.assertIsNone(failure, "transient sharing denial must recover")
                self.assertEqual(len(attempts), 3)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.01, 0.02])
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.payload)
                self.assertFalse(self.path.with_name("run.json.tmp").exists())

    def test_permanent_windows_denial_is_bounded_and_preserves_original_bytes(self):
        with patch.object(runner.os, "name", "nt"), patch.object(runner.os, "replace", side_effect=self.denied(5)) as replace, patch("time.sleep") as sleep:
            with self.assertRaises(PermissionError):
                runner._atomic_json_write(self.path, self.payload)
        self.assertEqual(self.path.read_bytes(), self.previous)
        self.assertEqual(replace.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.01, 0.02, 0.03, 0.04])

    def test_other_errors_and_non_windows_preserve_original_failure_without_retry(self):
        for platform_name, winerror in (("nt", 1), ("posix", 5), ("posix", 32)):
            with self.subTest(platform=platform_name, winerror=winerror):
                with patch.object(runner.os, "name", platform_name), patch.object(runner.os, "replace", side_effect=self.denied(winerror)) as replace, patch("time.sleep") as sleep:
                    with self.assertRaises(PermissionError):
                        runner._atomic_json_write(self.path, self.payload)
                self.assertEqual(self.path.read_bytes(), self.previous)
                self.assertEqual(replace.call_count, 1)
                sleep.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "real Windows read-handle semantics")
    def test_real_windows_reader_releases_after_first_denial_and_write_recovers(self):
        original_replace = os.replace
        denial_seen = Event()
        reader_released = Event()
        original_sleep = time.sleep
        attempts = []
        reader = self.path.open("rb")

        def observe(source, target):
            attempts.append((source, target))
            try:
                return original_replace(source, target)
            except PermissionError:
                denial_seen.set()
                raise

        failure = None

        def wait_for_reader(delay):
            self.assertTrue(reader_released.wait(2), "reader must close before retry")
            original_sleep(delay)

        try:
            with patch.object(runner.os, "replace", side_effect=observe), patch.object(runner.time, "sleep", side_effect=wait_for_reader):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(runner._atomic_json_write, self.path, self.payload)
                    self.assertTrue(denial_seen.wait(2), "open Windows reader must block replacement")
                    self.assertEqual(self.path.read_bytes(), self.previous)
                    reader.close()
                    reader_released.set()
                    try:
                        future.result(timeout=3)
                    except PermissionError as exc:
                        failure = exc
        finally:
            reader.close()
            reader_released.set()
        self.assertIsNone(failure, "released real Windows reader must allow atomic replacement")
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.payload)


if __name__ == "__main__":
    unittest.main()
