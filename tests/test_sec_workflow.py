import copy
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from quantagent_platform.cli import build_parser, main as cli_main
from quantagent_platform.contracts import DataPacket
from quantagent_platform.plugins import PluginError
from quantagent_platform.result_api import ApiConfig, create_app
from quantagent_platform.runner import RecipeError, RecipeRunner, default_registry
from quantagent_platform.sec_contracts import SEC_FACTS_CONTRACT, normalize_sample
from tests.test_sec_contracts import ISSUERS, make_payloads, make_responses


ROOT = Path(__file__).resolve().parents[1]
RECIPE_PATH = ROOT / "recipes" / "sec_industry_peers.json"
CONTACT = "QuantAgent test-contact@example.invalid"


class SecWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.runs = self.root / "runs"
        self.packet_path = self.root / "sec_packet.json"
        self.packet_path.write_text(json.dumps(normalize_sample(make_responses()).to_dict()),
                                    encoding="utf-8")
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)
        self.runner = RecipeRunner(default_registry())

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_replay(self, run_id, *, packet_path=None, title="SEC sample"):
        return self.runner.run(
            self.recipe,
            params={"source_path": str(packet_path or self.packet_path),
                    "report_title": title},
            output_dir=self.runs,
            allowed_read_roots=[self.root],
            bindings={"source.sec_company_facts": "builtin.sec-replay-source"},
            run_id=run_id,
        )

    def test_catalog_recipe_and_preflight_permissions(self):
        catalog = {row["plugin_id"]: row for row in default_registry().catalog()}
        ids = {
            "builtin.sec-edgar-source", "builtin.sec-replay-source",
            "builtin.sec-sector-overview", "builtin.sec-peer-comparison",
            "builtin.markdown-sec-research-report",
        }
        self.assertTrue(ids.issubset(catalog))
        self.assertEqual(catalog["builtin.sec-edgar-source"]["permissions"],
                         ["filesystem:write", "network:https"])
        self.assertEqual(catalog["builtin.sec-edgar-source"]["status"], "experimental")
        self.assertFalse(catalog["builtin.sec-replay-source"]["network_access"])
        self.assertEqual([step["capability"] for step in self.recipe["steps"]], [
            "source.sec_company_facts", "research.sec_sector_overview",
            "research.sec_peer_comparison", "report.sec_research",
        ])
        self.runner._preflight(self.recipe,
                               {"source.sec_company_facts": "builtin.sec-replay-source"},
                               {"filesystem:read", "filesystem:write"}, offline=True)
        self.runner._preflight(self.recipe, {},
                               {"filesystem:read", "filesystem:write", "network:https"},
                               offline=False)
        with self.assertRaisesRegex(RecipeError, "network access in offline mode"):
            self.runner.run(self.recipe, params={"source_path": "", "report_title": "test"},
                            output_dir=self.runs, allowed_read_roots=[],
                            allowed_permissions={"filesystem:write", "network:https"},
                            offline=True, run_id="offline-blocked")
        with self.assertRaisesRegex(RecipeError, "denied permissions"):
            self.runner.run(self.recipe, params={"source_path": "", "report_title": "test"},
                            output_dir=self.runs, allowed_read_roots=[],
                            allowed_permissions={"filesystem:write"},
                            offline=False, run_id="permission-blocked")
        self.assertFalse((self.runs / "offline-blocked").exists())
        self.assertFalse((self.runs / "permission-blocked").exists())

    def test_replay_writes_source_traced_report_and_stable_markdown(self):
        first = self.run_replay("replay-one")
        second = self.run_replay("replay-two")
        self.assertEqual(first.final_packet.contract_version, "quantagent.report.v1")
        report = (first.run_dir / "sec_industry_peers.md").read_text(encoding="utf-8")
        self.assertEqual(report, (second.run_dir / "sec_industry_peers.md").read_text(encoding="utf-8"))
        self.assertIn("## Sector overview", report)
        self.assertIn("## Peer comparison", report)
        self.assertIn("2025-01-01", report)
        self.assertIn("2025-12-31", report)
        self.assertIn("1,554,528,000", report)
        self.assertIn("https://www.sec.gov/Archives/edgar/data/1507605/", report)
        self.assertIn("0001104659-26-022322", report)
        self.assertIn("not industry totals", report)
        self.assertIn("## Missing or excluded metrics", report)
        self.assertIn("NetIncomeLoss", report)
        record = first.final_packet.records[0]
        self.assertEqual(record["format"], "markdown")
        self.assertEqual(record["input_sha256"],
                         DataPacket.from_dict(json.loads((first.run_dir / "03-compare-peers.json").read_text()))
                         .content_sha256)
        self.assertEqual(record["artifact_sha256"],
                         hashlib.sha256((first.run_dir / "sec_industry_peers.md").read_bytes()).hexdigest())

    def test_missing_fact_and_untrusted_text_are_rendered_without_external_link(self):
        payloads = make_payloads()
        del payloads[("companyfacts", ISSUERS[0][0])]["facts"]["us-gaap"]["Revenues"]
        missing_path = self.root / "missing.json"
        missing_path.write_text(json.dumps(normalize_sample(make_responses(payloads)).to_dict()),
                                encoding="utf-8")
        report = (self.run_replay("missing", packet_path=missing_path,
                                  title="SEC ` | [evil](https://example.invalid) <tag>")
                  .run_dir / "sec_industry_peers.md").read_text(encoding="utf-8")
        self.assertIn("missing_approved_fact", report)
        self.assertIn("1/2", report)
        self.assertIn("\\[evil\\]", report)
        self.assertNotIn("](https://example.invalid)", report)
        self.assertNotIn("<tag>", report)

        original = DataPacket.from_dict(json.loads(self.packet_path.read_text()))
        poisoned = copy.deepcopy(original.records[0])
        poisoned["companies"][0]["facts"]["Revenues"]["filing_index_url"] = "https://example.invalid/fake"
        forged = DataPacket.create(contract_version=SEC_FACTS_CONTRACT,
                                   packet_type="sec_company_facts", source=original.source,
                                   records=[poisoned], created_at=original.created_at)
        poisoned_path = self.root / "poisoned.json"
        poisoned_path.write_text(json.dumps(forged.to_dict()), encoding="utf-8")
        with self.assertRaises(RecipeError):
            self.run_replay("poisoned", packet_path=poisoned_path)
        self.assertFalse((self.runs / "poisoned" / "sec_industry_peers.md").exists())

    def test_live_transport_failure_is_audited_without_contact(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": CONTACT}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       side_effect=PluginError("SEC request failed: HTTP 403")):
                with self.assertRaises(RecipeError):
                    self.runner.run(self.recipe,
                                    params={"source_path": "", "report_title": "SEC sample"},
                                    output_dir=self.runs, allowed_read_roots=[],
                                    allowed_permissions={"filesystem:write", "network:https"},
                                    offline=False, run_id="forbidden")
        state = json.loads((self.runs / "forbidden" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")
        self.assertFalse((self.runs / "forbidden" / "sec_industry_peers.md").exists())
        self.assertNotIn(CONTACT, json.dumps(state))

    def test_live_source_keeps_four_raw_snapshots_and_no_contact(self):
        responses = make_responses()
        with patch.dict(os.environ, {"SEC_USER_AGENT": CONTACT}):
            with patch("quantagent_platform.sec_plugins.fetch_sample", return_value=responses):
                result = self.runner.run(
                    self.recipe, params={"source_path": "", "report_title": "SEC sample"},
                    output_dir=self.runs, allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False, run_id="live-synthetic")
        raw_files = sorted(result.run_dir.glob("sec-*-*.json"))
        self.assertEqual(len(raw_files), 4)
        source_packet = DataPacket.from_dict(json.loads(
            (result.run_dir / "01-load-sec-facts.json").read_text(encoding="utf-8")))
        self.assertEqual(source_packet.contract_version, SEC_FACTS_CONTRACT)
        self.assertEqual({hashlib.sha256(path.read_bytes()).hexdigest() for path in raw_files},
                         {row.sha256 for row in responses})
        for path in result.run_dir.iterdir():
            if path.is_file():
                self.assertNotIn(CONTACT.encode(), path.read_bytes())

    def test_cli_source_input_rules_and_live_preflight(self):
        args = build_parser().parse_args([
            "run", str(RECIPE_PATH), "--source", "sec-edgar",
            "--online", "--allow-permission", "network:https",
        ])
        self.assertIsNone(args.input_path)
        cases = (
            (["--source", "json"], "--input is required"),
            (["--source", "sqlite"], "--input is required"),
            (["--source", "sec-replay"], "--input is required"),
            (["--source", "sec-edgar", "--input", str(self.packet_path)],
             "does not accept --input"),
            (["--source", "sec-edgar", "--allow-permission", "network:https"],
             "network access in offline mode"),
            (["--source", "sec-edgar", "--online"], "denied permissions"),
        )
        for flags, expected in cases:
            with self.subTest(flags=flags):
                error = StringIO()
                with redirect_stderr(error):
                    code = cli_main(["run", str(RECIPE_PATH), *flags,
                                     "--output-dir", str(self.runs)])
                self.assertEqual(code, 2)
                self.assertIn(expected, error.getvalue())
                self.assertFalse(self.runs.exists())

        out = StringIO()
        with redirect_stdout(out):
            code = cli_main(["validate-recipe", str(RECIPE_PATH),
                             "--source", "sec-edgar", "--online",
                             "--allow-permission", "network:https"])
        self.assertEqual(code, 0)
        self.assertIn("validation passed", out.getvalue().lower())

    def test_cli_replay_report_is_authenticated_integrity_checked_and_read_only(self):
        out, error = StringIO(), StringIO()
        with patch.dict(os.environ, {"SEC_USER_AGENT": CONTACT}):
            with redirect_stdout(out), redirect_stderr(error):
                code = cli_main([
                    "run", str(RECIPE_PATH), "--source", "sec-replay",
                    "--input", str(self.packet_path), "--output-dir", str(self.runs),
                ])
        self.assertEqual(code, 0, error.getvalue())
        run_id = json.loads(out.getvalue())["run_id"]
        run_dir = self.runs / run_id
        token = "p4-test-token-with-at-least-thirty-two-characters"
        client = TestClient(create_app(ApiConfig(run_root=self.runs,
                                                owner_subject="fixture-owner",
                                                bearer_token=token)))
        headers = {"Authorization": f"Bearer {token}"}
        snapshot = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in run_dir.iterdir() if path.is_file()}
        try:
            self.assertEqual(client.get(f"/api/v1/runs/{run_id}").status_code, 401)
            summary = client.get(f"/api/v1/runs/{run_id}", headers=headers)
            self.assertEqual(summary.status_code, 200)
            schema = json.loads((ROOT / "schemas" /
                                 "quantagent.read_api.run_summary.v1.schema.json")
                                .read_text(encoding="utf-8"))
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(
                summary.json())
            self.assertEqual(summary.json()["status"], "completed")
            report = client.get(f"/api/v1/runs/{run_id}/report", headers=headers)
            self.assertEqual(report.status_code, 200)
            self.assertIn("## Sector overview", report.text)
            digest = hashlib.sha256(report.content).hexdigest()
            self.assertEqual(report.headers["etag"], f'"{digest}"')
            self.assertEqual(client.get(f"/api/v1/runs/{run_id}/report",
                                        headers={**headers,
                                                 "If-None-Match": report.headers["etag"]})
                             .status_code, 304)
            self.assertEqual(snapshot, {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in run_dir.iterdir() if path.is_file()})
            (run_dir / "sec_industry_peers.md").write_bytes(report.content + b"tampered")
            self.assertEqual(client.get(f"/api/v1/runs/{run_id}/report",
                                        headers=headers).status_code, 409)
            self.assertNotIn(CONTACT, summary.text + report.text + error.getvalue())
            self.assertTrue(all(CONTACT.encode() not in path.read_bytes()
                                for path in run_dir.iterdir() if path.is_file()))
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
