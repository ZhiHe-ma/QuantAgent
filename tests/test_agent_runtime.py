import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import (  # noqa: E402
    AgentCatalog,
    AgentError,
    AgentRuntime,
    ManifestError,
    RecipeError,
    RecipeRunner,
)
from quantagent_platform.manifests import load_agent_manifest  # noqa: E402
from quantagent_platform.runner import default_registry  # noqa: E402


AGENT_ID = "builtin.data-health-research-agent"
AGENT_VERSION = "1.0.0"
CATALOG_PATH = ROOT / "agent_catalog" / "catalog.json"
RECIPE_PATH = ROOT / "recipes" / "historical_data_health.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_signals.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"

    def tearDown(self):
        self.temp_dir.cleanup()

    def runtime(self) -> AgentRuntime:
        return AgentRuntime(runner=RecipeRunner(default_registry()))

    def run_agent(self, runtime: AgentRuntime, run_id: str):
        return runtime.run(
            agent_id=AGENT_ID,
            agent_version=AGENT_VERSION,
            params={
                "source_path": str(FIXTURE_PATH),
                "report_title": "Agent fixture report",
            },
            output_dir=self.output,
            allowed_read_roots=[ROOT],
            bindings={"source.signal_history": "builtin.json-signal-source"},
            run_id=run_id,
        )

    def copy_catalog(self) -> tuple[Path, Path]:
        shutil.copytree(ROOT / "agent_catalog", self.root / "agent_catalog")
        shutil.copytree(ROOT / "recipes", self.root / "recipes")
        return self.root / "agent_catalog" / "catalog.json", self.root

    @staticmethod
    def set_catalog_sha(catalog_path: Path, kind: str, artifact_path: Path) -> None:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        plural = f"{kind}s"
        catalog[plural][0]["sha256"] = sha256_file(artifact_path)
        catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_catalog_resolves_exact_verified_agent_skill_and_recipe(self):
        plan = self.runtime().resolve(
            agent_id=AGENT_ID,
            agent_version=AGENT_VERSION,
            bindings={"source.signal_history": "builtin.json-signal-source"},
        )

        self.assertEqual(plan.agent_entry.status, "verified")
        self.assertEqual(plan.skill_entry.identifier, "builtin.signal-data-health")
        self.assertEqual(plan.recipe_entry.identifier, "historical-data-health")
        self.assertEqual(len(plan.resolved_plugins), 3)
        self.assertEqual(
            [step[0]["capability"] for step in plan.resolved_plugins],
            plan.agent["required_capabilities"],
        )

    def test_agent_and_direct_recipe_share_runner_and_execution_semantics(self):
        runner = RecipeRunner(default_registry())
        runtime = AgentRuntime(runner=runner)
        agent_result = self.run_agent(runtime, "agent-run")
        direct_result = runner.run(
            RecipeRunner.load_recipe(RECIPE_PATH),
            params={
                "source_path": str(FIXTURE_PATH),
                "report_title": "Agent fixture report",
            },
            output_dir=self.output,
            allowed_read_roots=[ROOT],
            bindings={"source.signal_history": "builtin.json-signal-source"},
            run_id="direct-run",
        )

        self.assertIs(runtime.runner, runner)
        self.assertEqual(
            [step["capability"] for step in agent_result.steps],
            [step["capability"] for step in direct_result.steps],
        )
        agent_quality = json.loads(
            (agent_result.run_dir / "02-inspect-data-quality.json").read_text(encoding="utf-8")
        )
        direct_quality = json.loads(
            (direct_result.run_dir / "02-inspect-data-quality.json").read_text(encoding="utf-8")
        )
        self.assertEqual(agent_quality["records"], direct_quality["records"])
        self.assertEqual(agent_quality["metadata"], direct_quality["metadata"])

        agent_state = json.loads(
            (agent_result.run_dir / "run.json").read_text(encoding="utf-8")
        )
        direct_state = json.loads(
            (direct_result.run_dir / "run.json").read_text(encoding="utf-8")
        )
        self.assertEqual(agent_state["invocation"]["type"], "agent")
        self.assertEqual(agent_state["invocation"]["agent"]["id"], AGENT_ID)
        self.assertEqual(agent_state["invocation"]["recipe"]["sha256"], sha256_file(RECIPE_PATH))
        self.assertNotIn("invocation", direct_state)

    def test_unknown_agent_version_fails_before_creating_run_directory(self):
        with self.assertRaisesRegex(AgentError, "not installed or allow-listed"):
            self.runtime().run(
                agent_id=AGENT_ID,
                agent_version="9.9.9",
                params={"source_path": str(FIXTURE_PATH), "report_title": "Rejected"},
                output_dir=self.output,
                allowed_read_roots=[ROOT],
                run_id="unknown-agent",
            )
        self.assertFalse((self.output / "unknown-agent").exists())

    def test_unapproved_recipe_and_unknown_binding_fail_before_run(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(AgentError, "does not allow Recipe"):
            runtime.resolve(
                agent_id=AGENT_ID,
                agent_version=AGENT_VERSION,
                recipe_id="offline-daily-research",
                recipe_version="1.0.0",
            )
        with self.assertRaisesRegex(AgentError, "unknown Recipe capabilities"):
            runtime.run(
                agent_id=AGENT_ID,
                agent_version=AGENT_VERSION,
                params={"source_path": str(FIXTURE_PATH), "report_title": "Rejected"},
                output_dir=self.output,
                allowed_read_roots=[ROOT],
                bindings={"network.external": "external.plugin"},
                run_id="unknown-binding",
            )
        self.assertFalse((self.output / "unknown-binding").exists())

    def test_catalog_rejects_tampered_manifest_and_skill_content(self):
        catalog_path, catalog_root = self.copy_catalog()
        agent_path = catalog_root / "agent_catalog" / "agents" / "data-health-agent" / "agent.yaml"
        agent_path.write_text(agent_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "catalog SHA-256 mismatch"):
            AgentCatalog.load(catalog_path, root=catalog_root)

        catalog_path, catalog_root = self.copy_catalog_again()
        skill_path = catalog_root / "agent_catalog" / "skills" / "signal-data-health" / "SKILL.md"
        skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "Skill content SHA-256 mismatch"):
            AgentCatalog.load(catalog_path, root=catalog_root)

    def copy_catalog_again(self) -> tuple[Path, Path]:
        second_root = self.root / "second"
        shutil.copytree(ROOT / "agent_catalog", second_root / "agent_catalog")
        shutil.copytree(ROOT / "recipes", second_root / "recipes")
        return second_root / "agent_catalog" / "catalog.json", second_root

    def test_extra_agent_capability_and_experimental_status_fail_closed(self):
        catalog_path, catalog_root = self.copy_catalog()
        agent_path = catalog_root / "agent_catalog" / "agents" / "data-health-agent" / "agent.yaml"
        text = agent_path.read_text(encoding="utf-8").replace(
            "  - report.data_quality\nreview_gates:",
            "  - report.data_quality\n  - network.external\nreview_gates:",
        )
        agent_path.write_text(text, encoding="utf-8")
        self.set_catalog_sha(catalog_path, "agent", agent_path)
        runtime = AgentRuntime(
            catalog=AgentCatalog.load(catalog_path, root=catalog_root),
            runner=RecipeRunner(default_registry()),
        )
        with self.assertRaisesRegex(AgentError, "exactly match"):
            runtime.resolve(agent_id=AGENT_ID, agent_version=AGENT_VERSION)

        second_catalog_path, second_root = self.copy_catalog_again()
        catalog = json.loads(second_catalog_path.read_text(encoding="utf-8"))
        catalog["agents"][0]["status"] = "experimental"
        second_catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        runtime = AgentRuntime(
            catalog=AgentCatalog.load(second_catalog_path, root=second_root),
            runner=RecipeRunner(default_registry()),
        )
        with self.assertRaisesRegex(AgentError, "requires a verified agent"):
            runtime.resolve(agent_id=AGENT_ID, agent_version=AGENT_VERSION)

    def test_catalog_duplicate_keys_are_rejected(self):
        catalog_path, catalog_root = self.copy_catalog()
        content = catalog_path.read_text(encoding="utf-8").replace(
            "{\n",
            '{\n  "catalog_version": "9.9.9",\n',
            1,
        )
        catalog_path.write_text(content, encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "duplicate key"):
            AgentCatalog.load(catalog_path, root=catalog_root)

    def test_unverified_skill_and_model_requiring_agent_are_rejected(self):
        catalog_path, catalog_root = self.copy_catalog()
        skill_path = catalog_root / "agent_catalog" / "skills" / "signal-data-health" / "skill.yaml"
        skill_path.write_text(
            skill_path.read_text(encoding="utf-8").replace(
                "state: fixture_verified",
                "state: static_checked",
            ),
            encoding="utf-8",
        )
        self.set_catalog_sha(catalog_path, "skill", skill_path)
        runtime = AgentRuntime(
            catalog=AgentCatalog.load(catalog_path, root=catalog_root),
            runner=RecipeRunner(default_registry()),
        )
        with self.assertRaisesRegex(AgentError, "fixture_verified Skill"):
            runtime.resolve(agent_id=AGENT_ID, agent_version=AGENT_VERSION)

        second_catalog_path, second_root = self.copy_catalog_again()
        agent_path = second_root / "agent_catalog" / "agents" / "data-health-agent" / "agent.yaml"
        agent_path.write_text(
            agent_path.read_text(encoding="utf-8").replace(
                "text_generation: false",
                "text_generation: true",
            ),
            encoding="utf-8",
        )
        self.set_catalog_sha(second_catalog_path, "agent", agent_path)
        runtime = AgentRuntime(
            catalog=AgentCatalog.load(second_catalog_path, root=second_root),
            runner=RecipeRunner(default_registry()),
        )
        with self.assertRaisesRegex(AgentError, "do not require a model"):
            runtime.resolve(agent_id=AGENT_ID, agent_version=AGENT_VERSION)

    def test_strict_yaml_rejects_hidden_or_ambiguous_structure(self):
        valid = (ROOT / "agent_catalog" / "agents" / "data-health-agent" / "agent.yaml").read_text(
            encoding="utf-8"
        )
        variants = {
            "anchor": valid.replace("version: 1.0.0", "version: &release 1.0.0", 1),
            "explicit-tag": valid.replace("version: 1.0.0", "version: !!str 1.0.0", 1),
            "merge-key": valid + "\nmetadata:\n  <<: {deterministic: true}\n",
            "duplicate-key": valid + "\nagent_id: duplicate.agent\n",
            "implicit-date": valid.replace(
                "metadata:\n",
                "metadata:\n  release_date: 2026-09-22\n",
                1,
            ),
            "non-json-number": valid.replace(
                "metadata:\n",
                "metadata:\n  score: .nan\n",
                1,
            ),
        }
        for name, content in variants.items():
            with self.subTest(name=name):
                path = self.root / f"{name}.yaml"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ManifestError):
                    load_agent_manifest(path)

    def test_invalid_invocation_audit_is_rejected_before_run_directory(self):
        runner = RecipeRunner(default_registry())
        recipe = RecipeRunner.load_recipe(RECIPE_PATH)
        for run_id, invocation in (
            ("not-object", ["agent"]),
            ("not-json", {"cost": float("nan")}),
        ):
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(RecipeError, "invocation audit context"):
                    runner.run(
                        recipe,
                        params={
                            "source_path": str(FIXTURE_PATH),
                            "report_title": "Rejected",
                        },
                        output_dir=self.output,
                        allowed_read_roots=[ROOT],
                        bindings={"source.signal_history": "builtin.json-signal-source"},
                        run_id=run_id,
                        invocation=invocation,  # type: ignore[arg-type]
                    )
                self.assertFalse((self.output / run_id).exists())


if __name__ == "__main__":
    unittest.main()
