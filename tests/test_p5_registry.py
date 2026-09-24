"""Private P4 snapshot admission and artifact integrity tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quantagent_platform.p5_registry as registry_module
from quantagent_platform.p5_registry import (
    ApprovedRunRegistry,
    ApprovedSourceError,
    read_approved_source,
    strict_json,
)
from quantagent_platform.runner import RecipeRunner, default_registry
from tests.test_sec_contracts import make_responses


ROOT = Path(__file__).resolve().parents[1]
RAW_NAMES = (
    "sec-mara-submissions.json",
    "sec-mara-companyfacts.json",
    "sec-riot-submissions.json",
    "sec-riot-companyfacts.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ApprovedRunRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        recipe = RecipeRunner.load_recipe(ROOT / "recipes" / "sec_industry_peers.json")
        runner = RecipeRunner(default_registry())
        with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       return_value=make_responses()):
                result = runner.run(
                    recipe,
                    params={"source_path": "", "report_title": "Synthetic SEC sample"},
                    output_dir=self.runs,
                    allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False,
                    run_id="synthetic-p4-run",
                )
        self.run_dir = result.run_dir
        self.registry_path = self.root / "approved.json"
        self.entry = {
            "approved_source_id": "synthetic-p4",
            "run_id": result.run_id,
            "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
            "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
            "packet_sha256": sha256(self.run_dir / "01-load-sec-facts.json"),
            "report_sha256": sha256(self.run_dir / "sec_industry_peers.md"),
            "raw_sha256": {name: sha256(self.run_dir / name) for name in RAW_NAMES},
        }
        self.write_registry()

    def write_registry(self) -> None:
        self.registry_path.write_text(
            json.dumps({
                "registry_version": "quantagent.sec_approved_run.v1",
                "entries": [self.entry],
            }),
            encoding="utf-8",
        )

    def approved(self):
        return ApprovedRunRegistry.load(self.registry_path, self.runs).resolve(
            "synthetic-p4"
        )

    def test_reads_pinned_live_shaped_p4_snapshot(self) -> None:
        source = self.approved()
        evidence = read_approved_source(source)
        self.assertEqual(evidence.packet.contract_version,
                         "quantagent.sec_company_facts.v1")
        self.assertEqual(evidence.packet.content_sha256, evidence.record_sha256)
        self.assertEqual(set(evidence.raw), set(RAW_NAMES))
        self.assertEqual(evidence.report_sha256, source.report_sha256)

    def test_nested_exponent_overflow_is_not_accepted_as_finite_json(self) -> None:
        for number in (b"1e999", b"-1e999"):
            with self.subTest(number=number):
                with self.assertRaises(ApprovedSourceError):
                    strict_json(b'{"unused":{"value":' + number + b'}}')

    def test_unknown_source_and_path_escape_fail_closed(self) -> None:
        registry = ApprovedRunRegistry.load(self.registry_path, self.runs)
        with self.assertRaises(ApprovedSourceError):
            registry.resolve("other")
        self.entry["run_id"] = "../outside"
        self.write_registry()
        with self.assertRaises(ApprovedSourceError):
            self.approved()

    def test_wrong_packet_hash_and_digest_fail_closed(self) -> None:
        self.entry["packet_sha256"] = "0" * 64
        self.write_registry()
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())

        self.entry["packet_sha256"] = sha256(self.run_dir / "01-load-sec-facts.json")
        packet_path = self.run_dir / "01-load-sec-facts.json"
        value = json.loads(packet_path.read_text(encoding="utf-8"))
        value["content_sha256"] = "0" * 64
        packet_path.write_text(json.dumps(value), encoding="utf-8")
        self.entry["packet_sha256"] = sha256(packet_path)
        self.write_registry()
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())

    def test_report_and_raw_changes_fail_closed(self) -> None:
        report_path = self.run_dir / "sec_industry_peers.md"
        report_path.write_bytes(report_path.read_bytes() + b" altered")
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())
        report_path.write_bytes(report_path.read_bytes()[:-8])

        raw_path = self.run_dir / RAW_NAMES[0]
        raw_path.write_bytes(raw_path.read_bytes() + b" altered")
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())

    def test_missing_and_oversized_packet_fail_closed(self) -> None:
        packet_path = self.run_dir / "01-load-sec-facts.json"
        packet_path.unlink()
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())
        packet_path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())

    def test_symlinked_packet_fails_even_if_bytes_match(self) -> None:
        packet_path = self.run_dir / "01-load-sec-facts.json"
        outside = self.root / "outside.json"
        outside.write_bytes(packet_path.read_bytes())
        packet_path.unlink()
        try:
            packet_path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("file symlink creation is unavailable")
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())

    def test_symlinked_run_directory_fails(self) -> None:
        outside = self.root / "outside-run"
        self.run_dir.rename(outside)
        try:
            self.run_dir.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlink creation is unavailable")
        with self.assertRaises(ApprovedSourceError):
            read_approved_source(self.approved())

    def test_swapped_file_identity_during_read_fails_closed(self) -> None:
        packet_path = self.run_dir / "01-load-sec-facts.json"
        actual_signatures = registry_module._path_signatures
        seen = 0

        def changed_after_open(path: Path):
            nonlocal seen
            signatures = actual_signatures(path)
            if Path(path) == packet_path:
                seen += 1
                if seen == 2:
                    final_path, (device, inode, mode) = signatures[-1]
                    return (*signatures[:-1],
                            (final_path, (device, inode + 1, mode)))
            return signatures

        with patch.object(registry_module, "_path_signatures",
                          side_effect=changed_after_open):
            with self.assertRaises(ApprovedSourceError):
                registry_module.bounded_regular_file(packet_path, 2 * 1024 * 1024)

    @unittest.skipUnless(os.name == "nt", "junctions are a Windows feature")
    def test_junctioned_run_directory_fails(self) -> None:
        outside = self.root / "outside-run"
        self.run_dir.rename(outside)
        environment = {**os.environ, "P5_JUNCTION_PATH": str(self.run_dir),
                       "P5_JUNCTION_TARGET": str(outside)}
        command = (
            "New-Item -ItemType Junction -Path $env:P5_JUNCTION_PATH "
            "-Target $env:P5_JUNCTION_TARGET | Out-Null"
        )
        created = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            env=environment, capture_output=True, text=True, check=False,
        )
        if created.returncode != 0:
            self.skipTest("junction creation is unavailable")
        try:
            with self.assertRaises(ApprovedSourceError):
                read_approved_source(self.approved())
        finally:
            self.run_dir.rmdir()
            outside.rename(self.run_dir)

    @unittest.skipUnless(os.name == "nt", "junctions are a Windows feature")
    def test_junction_swap_between_validation_and_open_fails_closed(self) -> None:
        packet_path = self.run_dir / "01-load-sec-facts.json"
        outside = self.root / "race-outside-run"
        original_open = registry_module._windows_open_nofollow

        def swap_then_open(path: Path) -> int:
            self.run_dir.rename(outside)
            environment = {**os.environ, "P5_JUNCTION_PATH": str(self.run_dir),
                           "P5_JUNCTION_TARGET": str(outside)}
            created = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "New-Item -ItemType Junction -Path $env:P5_JUNCTION_PATH "
                 "-Target $env:P5_JUNCTION_TARGET | Out-Null"],
                env=environment, capture_output=True, text=True, check=False,
            )
            if created.returncode != 0:
                self.skipTest("junction creation is unavailable")
            return original_open(path)

        try:
            with patch.object(registry_module, "_windows_open_nofollow",
                              side_effect=swap_then_open):
                with self.assertRaises(ApprovedSourceError):
                    registry_module.bounded_regular_file(packet_path, 2 * 1024 * 1024)
        finally:
            if self.run_dir.is_junction():
                self.run_dir.rmdir()
            if outside.exists():
                outside.rename(self.run_dir)


if __name__ == "__main__":
    unittest.main()
