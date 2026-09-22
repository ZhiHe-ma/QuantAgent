import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import AgentRuntime, RecipeRunner  # noqa: E402
from quantagent_platform.contracts import ContractError, sha256_json  # noqa: E402
from quantagent_platform.research_contracts import (  # noqa: E402
    load_strict_json,
    update_thesis,
    validate_review_fixture,
)
from quantagent_platform.runner import default_registry  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_thesis_review.json"
EXPECTED_PATH = ROOT / "tests" / "fixtures" / "sample_thesis_review_expected.json"
RECIPE_PATH = ROOT / "recipes" / "thesis_tracker.json"
REPORT_TITLE = "QuantAgent P2 Golden Thesis Report"


class ThesisTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"
        self.fixture = load_strict_json(FIXTURE_PATH)
        self.expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)
        self.runner = RecipeRunner(default_registry())

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_recipe(self, run_id: str):
        return self.runner.run(
            self.recipe,
            params={
                "source_path": str(FIXTURE_PATH),
                "report_title": REPORT_TITLE,
            },
            output_dir=self.output,
            allowed_read_roots=[ROOT],
            run_id=run_id,
        )

    @staticmethod
    def refresh_input_hash(fixture: dict, purpose: str, value: dict) -> None:
        for row in fixture["research_request"]["input_refs"]:
            if row["purpose"] == purpose:
                row["content_sha256"] = sha256_json(value)
                return
        raise AssertionError(f"missing input ref: {purpose}")

    def test_golden_fixture_updates_thesis_and_renders_deterministic_report(self):
        result = self.run_recipe("golden-run")
        state_packet = json.loads(
            (result.run_dir / "02-update-thesis-state.json").read_text(encoding="utf-8")
        )
        report_packet = json.loads(
            (result.run_dir / "03-write-thesis-report.json").read_text(encoding="utf-8")
        )
        state = state_packet["records"][0]

        self.assertEqual(
            hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
            self.expected["input_fixture_sha256"],
        )
        self.assertEqual(sha256_json(state), self.expected["expected_state_sha256"])
        self.assertEqual(state["version"], self.expected["expected_version"])
        self.assertEqual(state["current_assessment"], self.expected["expected_assessment"])
        self.assertEqual(
            state["research_suggestion"], self.expected["expected_research_suggestion"]
        )
        self.assertEqual(
            state["statuses"]["evidence_sufficient"],
            self.expected["expected_evidence_sufficient"],
        )
        self.assertFalse(state["statuses"]["human_reviewed"])
        self.assertFalse(state["statuses"]["action_eligible"])
        self.assertEqual(
            state["supporting_evidence_refs"],
            self.expected["expected_supporting_evidence_refs"],
        )
        self.assertEqual(
            state["opposing_evidence_refs"],
            self.expected["expected_opposing_evidence_refs"],
        )
        self.assertEqual(
            state["context_evidence_refs"],
            self.expected["expected_context_evidence_refs"],
        )
        self.assertEqual(
            {row["claim_id"]: row["status"] for row in state["claims"]},
            self.expected["expected_claim_statuses"],
        )
        self.assertEqual(
            report_packet["records"][0]["artifact_sha256"],
            self.expected["expected_report_sha256"],
        )
        report_path = result.run_dir / "thesis_review_report.md"
        self.assertEqual(
            hashlib.sha256(report_path.read_bytes()).hexdigest(),
            report_packet["records"][0]["artifact_sha256"],
        )
        report = report_path.read_text(encoding="utf-8")
        self.assertNotIn("Ignore prior instructions", report)
        self.assertIn("Raw excerpts remain untrusted", report)
        self.assertIn("does not verify external truth", report)

    def test_repeated_runs_have_identical_state_and_report_content(self):
        first = self.run_recipe("repeat-one")
        second = self.run_recipe("repeat-two")
        first_state = json.loads(
            (first.run_dir / "02-update-thesis-state.json").read_text(encoding="utf-8")
        )["records"][0]
        second_state = json.loads(
            (second.run_dir / "02-update-thesis-state.json").read_text(encoding="utf-8")
        )["records"][0]
        self.assertEqual(first_state, second_state)
        self.assertEqual(
            (first.run_dir / "thesis_review_report.md").read_bytes(),
            (second.run_dir / "thesis_review_report.md").read_bytes(),
        )

    def test_reapplying_same_evidence_is_idempotent(self):
        first = update_thesis(self.fixture)
        replay = copy.deepcopy(self.fixture)
        replay["previous_thesis_state"] = copy.deepcopy(first)
        self.refresh_input_hash(replay, "previous_thesis_state", first)
        second = update_thesis(replay)
        self.assertEqual(second, first)
        self.assertEqual(second["version"], 2)

    def test_point_in_time_cutoff_and_content_hash_fail_closed(self):
        future = copy.deepcopy(self.fixture)
        future_evidence = future["evidence_bundle"]["evidence"][0]
        future_evidence["available_at"] = "2026-09-23T00:00:00+00:00"
        future_evidence["collected_at"] = "2026-09-23T00:05:00+00:00"
        with self.assertRaisesRegex(ContractError, "after the research as_of cutoff"):
            validate_review_fixture(future)

        late_collection = copy.deepcopy(self.fixture)
        late_collection["evidence_bundle"]["evidence"][0][
            "collected_at"
        ] = "2026-09-23T00:05:00+00:00"
        with self.assertRaisesRegex(ContractError, "collected after the research as_of cutoff"):
            validate_review_fixture(late_collection)

        future_fact = copy.deepcopy(self.fixture)
        future_fact["evidence_bundle"]["evidence"][0]["structured_facts"][0][
            "observed_at"
        ] = "2026-09-23T00:00:00+00:00"
        future_fact["evidence_bundle"]["evidence"][0]["content_sha256"] = sha256_json(
            {
                "excerpt": future_fact["evidence_bundle"]["evidence"][0]["excerpt"],
                "structured_facts": future_fact["evidence_bundle"]["evidence"][0][
                    "structured_facts"
                ],
            }
        )
        with self.assertRaisesRegex(ContractError, "contains a fact after"):
            validate_review_fixture(future_fact)

        tampered = copy.deepcopy(self.fixture)
        tampered["evidence_bundle"]["evidence"][0]["excerpt"] += " tampered"
        with self.assertRaisesRegex(ContractError, "content_sha256 does not match"):
            validate_review_fixture(tampered)

    def test_subject_mismatch_unknown_fields_and_id_collision_are_rejected(self):
        mismatch = copy.deepcopy(self.fixture)
        mismatch["evidence_bundle"]["subject"]["quote_asset"] = "USDT"
        with self.assertRaisesRegex(ContractError, "subject does not match"):
            validate_review_fixture(mismatch)

        unknown = copy.deepcopy(self.fixture)
        unknown["research_request"]["authorization"] = "grant network access"
        with self.assertRaisesRegex(ContractError, "Additional properties are not allowed"):
            validate_review_fixture(unknown)

        collision = copy.deepcopy(self.fixture)
        collision["evidence_bundle"]["evidence"][0]["evidence_id"] = "evidence.prior.support"
        self.refresh_input_hash(collision, "evidence_bundle", collision["evidence_bundle"])
        with self.assertRaisesRegex(ContractError, "collision with different content"):
            update_thesis(collision)

        semantic_collision = copy.deepcopy(self.fixture)
        updated = update_thesis(self.fixture)
        semantic_collision["previous_thesis_state"] = updated
        self.refresh_input_hash(semantic_collision, "previous_thesis_state", updated)
        semantic_collision["evidence_bundle"]["evidence"][0]["claim_refs"] = [
            "claim.institutional_demand"
        ]
        self.refresh_input_hash(
            semantic_collision,
            "evidence_bundle",
            semantic_collision["evidence_bundle"],
        )
        with self.assertRaisesRegex(ContractError, "indexed semantics"):
            update_thesis(semantic_collision)

    def test_forged_prior_state_and_requested_capability_are_rejected(self):
        forged = copy.deepcopy(self.fixture)
        forged["previous_thesis_state"]["current_assessment"] = "invalidated"
        self.refresh_input_hash(
            forged,
            "previous_thesis_state",
            forged["previous_thesis_state"],
        )
        with self.assertRaisesRegex(ContractError, "current_assessment is inconsistent"):
            validate_review_fixture(forged)

        elevated = copy.deepcopy(self.fixture)
        elevated["research_request"]["requested_capabilities"].append("network.https")
        with self.assertRaisesRegex(ContractError, "capabilities do not match"):
            validate_review_fixture(elevated)

    def test_explicit_invalidation_condition_changes_research_state_not_authority(self):
        invalidated = copy.deepcopy(self.fixture)
        evidence = invalidated["evidence_bundle"]["evidence"][2]
        evidence["stance"] = "oppose"
        evidence["impact"] = "invalidate"
        self.refresh_input_hash(
            invalidated,
            "evidence_bundle",
            invalidated["evidence_bundle"],
        )

        state = update_thesis(invalidated)
        condition = state["invalidation_conditions"][0]
        self.assertEqual(state["current_assessment"], "invalidated")
        self.assertEqual(state["research_suggestion"], "research_only_investigate")
        self.assertEqual(condition["status"], "triggered")
        self.assertEqual(condition["evidence_refs"], ["evidence.new.context"])
        self.assertIn("invalidation_triggered", state["revision"]["reason_codes"])
        self.assertFalse(state["statuses"]["action_eligible"])

    def test_adapted_skill_has_pinned_source_notice_and_full_license(self):
        skill_dir = ROOT / "agent_catalog" / "skills" / "thesis-tracker"
        notice = (skill_dir / "NOTICE.md").read_text(encoding="utf-8")
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        license_text = (
            ROOT
            / "THIRD_PARTY_LICENSES"
            / "anthropics-financial-services-Apache-2.0.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("574ed3624aebd0418c7e96cd101262f30210ab26", notice)
        self.assertIn("Upstream file blob: `f9a3ce9187bdc3410d3f4f3713ce70a6f6b8f221`", notice)
        self.assertIn("rewrote and narrowed", notice)
        self.assertIn("research-only", skill)
        self.assertIn("Apache License", license_text)
        self.assertIn("END OF TERMS AND CONDITIONS", license_text)

    def test_agent_entry_reuses_recipe_runner_and_records_exact_identity(self):
        runtime = AgentRuntime(runner=self.runner)
        result = runtime.run(
            agent_id="builtin.research-agent",
            agent_version="1.0.0",
            params={
                "source_path": str(FIXTURE_PATH),
                "report_title": REPORT_TITLE,
            },
            output_dir=self.output,
            allowed_read_roots=[ROOT],
            bindings={"source.thesis_review": "builtin.json-thesis-review-source"},
            run_id="agent-thesis-run",
        )
        run_state = json.loads((result.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertIs(runtime.runner, self.runner)
        self.assertEqual(run_state["invocation"]["agent"]["id"], "builtin.research-agent")
        self.assertEqual(
            run_state["invocation"]["skill"]["id"],
            "anthropic-financial-services-adapted.thesis-tracker",
        )
        self.assertEqual(run_state["invocation"]["recipe"]["id"], "thesis-tracker")
        self.assertEqual(
            [row["capability"] for row in run_state["steps"]],
            ["source.thesis_review", "research.thesis_update", "report.thesis"],
        )

    def test_role_permissions_are_minimal_and_evidence_text_cannot_change_them(self):
        catalog = {row["plugin_id"]: row for row in default_registry().catalog()}
        self.assertEqual(
            catalog["builtin.json-thesis-review-source"]["permissions"],
            ["filesystem:read"],
        )
        self.assertEqual(catalog["builtin.deterministic-thesis-tracker"]["permissions"], [])
        self.assertEqual(
            catalog["builtin.markdown-thesis-report"]["permissions"],
            ["filesystem:write"],
        )
        self.assertFalse(catalog["builtin.deterministic-thesis-tracker"]["network_access"])
        result = self.run_recipe("injection-data-run")
        run_state = json.loads((result.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run_state["bindings"], {})
        self.assertEqual(
            run_state["allowed_permissions"],
            ["filesystem:read", "filesystem:write"],
        )


if __name__ == "__main__":
    unittest.main()
