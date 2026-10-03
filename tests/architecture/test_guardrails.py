"""Real source and document fixtures; no business imports or network calls."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
try:
    policy = importlib.import_module("tools.architecture.policy")
    documentation = importlib.import_module("tools.architecture.documentation")
except ModuleNotFoundError:
    policy = documentation = None

README_SECTIONS = (
    "职责与边界", "文件导航", "对外接口", "依赖规则", "数据与权限", "测试与验收", "已知限制",
)
FEATURE_SECTIONS = (
    "目标与非目标", "涉及模块", "接口或数据变化", "新增依赖", "测试证据", "回滚方式", "遗留问题",
)


def component(name, modules, kind="module", allows=()):
    return {
        "id": name, "modules": modules, "kind": kind,
        "public_modules": list(modules), "allows": list(allows),
        "readme": "docs/README.md", "data_owner": "QuantAgent",
        "assets": [],
    }


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(policy, "architecture checker has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("qa/__init__.py", "")
        self.write("qa/contracts.py", "class Evidence: pass\n")
        self.write("qa/domain.py", "from .contracts import Evidence\n")
        self.write("qa/adapters.py", "from .contracts import Evidence\n")
        self.write("qa/entry.py", "from .contracts import Evidence\n")
        self.write("docs/README.md", "# Capability\n" + "\n".join(
            f"## {title}\nCurrent verified capability and limitations.\n" for title in README_SECTIONS
        ))
        self.registry = {"version": 1, "components": [
            component("facade", ["qa"], "facade", ["contracts"]),
            component("contracts", ["qa.contracts"], "contract"),
            component("domain", ["qa.domain"], "module", ["contracts"]),
            component("adapters", ["qa.adapters"], "adapter", ["contracts", "domain"]),
            component("entry", ["qa.entry"], "entry", ["contracts"]),
        ]}

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def inspect(self):
        return policy.inspect(self.root, self.registry)

    def rules(self):
        return {v["rule"] for v in self.inspect()["violations"]}

    def feature(self, branch="feature/demo", components=None, reasons=None):
        meta = {"branch": branch, "components": components or ["domain"],
                "readme_unchanged": reasons or {}, "base_commit": "a" * 40}
        body = "# Change\n\n```json\n" + json.dumps(meta) + "\n```\n\n"
        body += "\n".join(f"## {title}\nVerified scope; 未运行：this is a synthetic fixture.\n" for title in FEATURE_SECTIONS)
        self.write("docs/features/demo.md", body)

    def doc_errors(self, changed=None, mode="branch", branch="feature/demo"):
        return documentation.check(self.root, self.registry, branch,
                                   changed or ["qa/domain.py"], mode)

    def test_valid_layers_pass_without_executing_sources(self):
        self.write("qa/domain.py", "from .contracts import Evidence\nraise RuntimeError('must not execute')\n")
        self.assertEqual([], self.inspect()["violations"])

    def test_reverse_reference_is_rejected(self):
        self.write("qa/contracts.py", "from .domain import Evidence\n")
        self.assertIn("dependency", self.rules())
        self.assertIn("cycle", self.rules())

    def test_cross_business_module_import_is_rejected_even_when_allowlisted(self):
        self.registry["components"].append(component("other", ["qa.other"], "module", ["domain"]))
        self.write("qa/other.py", "from .domain import Evidence\n")
        self.assertIn("dependency", self.rules())

    def test_private_cross_boundary_import_is_rejected(self):
        self.write("qa/domain.py", "from .contracts import _hidden\n")
        self.assertIn("private-import", self.rules())

    def test_private_alias_attribute_is_rejected(self):
        self.write("qa/domain.py", "import qa.contracts as c\nx = c._hidden\n")
        self.assertIn("private-import", self.rules())

    def test_local_and_type_checking_imports_still_form_cycles(self):
        self.write("qa/contracts.py", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .domain import Evidence\n")
        self.write("qa/domain.py", "def work():\n    from .contracts import Evidence\n")
        self.assertIn("cycle", self.rules())

    def test_importing_package_facade_does_not_bypass_boundaries(self):
        self.write("qa/domain.py", "from qa import Evidence\n")
        self.assertIn("facade-import", self.rules())

    def test_registered_startup_facade_can_inject_bootstrap(self):
        self.registry["components"].append(component("bootstrap", ["qa.bootstrap"], "bootstrap", ["domain"]))
        self.registry["components"][0]["allows"].append("bootstrap")
        self.write("qa/bootstrap.py", "from .domain import Evidence\ndef configure(): pass\n")
        self.write("qa/__init__.py", "from .bootstrap import configure\nconfigure()\n")
        self.assertEqual([], self.inspect()["violations"])

    def test_core_cannot_import_bootstrap_even_when_allowlisted(self):
        self.registry["components"].append(component("bootstrap", ["qa.bootstrap"], "bootstrap", ["domain"]))
        self.registry["components"][2]["allows"].append("bootstrap")
        self.write("qa/bootstrap.py", "from .domain import Evidence\n")
        self.write("qa/domain.py", "from .bootstrap import Evidence\n")
        for kind in ("workflow", "module", "contract"):
            self.registry["components"][2]["kind"] = kind
            with self.subTest(kind=kind):
                self.assertIn("dependency", self.rules())
                self.assertIn("cycle", self.rules())

    def test_business_cannot_obtain_bootstrap_through_package_facade(self):
        self.registry["components"].append(component("bootstrap", ["qa.bootstrap"], "bootstrap"))
        self.registry["components"][0]["allows"].append("bootstrap")
        self.write("qa/bootstrap.py", "def configure(): pass\n")
        self.write("qa/__init__.py", "from .bootstrap import configure\n")
        self.write("qa/domain.py", "from qa import configure\n")
        self.assertIn("facade-import", self.rules())

    def test_startup_rule_does_not_legalize_original_capability_dependencies(self):
        registry = json.loads((ROOT / "docs/architecture/components.json").read_text(encoding="utf-8"))
        # Freeze the 42 capabilities present before D001 startup composition.
        # Future registered capabilities must not change this historical matrix.
        original_ids = frozenset("""
            packet-contracts research-contracts sec-contracts plugin-ports daily-domain sec-domain
            quality-adapter daily-adapter outcome-adapter thesis-adapter isolated-runtime qlib-adapter
            bt-adapter sec-adapter p5-storage p5-domain p5-adapter runner agent-runtime p5-workflow
            http-api cli-composition startup compatibility-exports legacy-engine signal-audit architecture
            recipes plugin-catalog agent-catalog schemas policies acceptance-tests
            skill-sec-evidence-independent-review skill-sec-evidence-preparation skill-signal-data-health
            skill-thesis-tracker agent-data-health-agent agent-research-agent
            agent-sec-evidence-producer-agent agent-sec-evidence-review-agent agent-definitions
        """.split())
        original = [c for c in registry["components"] if c["id"] in original_ids]
        self.assertEqual(original_ids, {c["id"] for c in original})
        self.assertEqual(42, len(original))
        before_kinds = {
            "entry": {"workflow", "contract", "bootstrap"},
            "workflow": {"workflow", "module", "contract"},
            "module": {"contract"}, "adapter": {"module", "contract"},
            "contract": {"contract"},
            "bootstrap": {"entry", "workflow", "module", "adapter", "contract", "facade"},
            "facade": {"workflow", "module", "contract"}, "governance": {"governance"},
        }
        for source in original:
            for target in original:
                expected = source["id"] == target["id"] or (
                    target["id"] in source["allows"] and target["kind"] in before_kinds[source["kind"]]
                )
                with self.subTest(source=source["id"], target=target["id"]):
                    self.assertEqual(expected, policy.allowed(source, target))

    def test_dynamic_import_alias_is_rejected(self):
        self.write("qa/domain.py", "from importlib import import_module as load\nload('qa.adapters')\n")
        self.assertIn("dynamic-import", self.rules())

    def test_unrelated_local_alias_cannot_hide_global_dynamic_import(self):
        self.write("qa/domain.py", "import importlib as loader\ndef load():\n    return loader.import_module('qa.adapters')\ndef unrelated():\n    import json as loader\n    return loader.dumps({})\n")
        self.assertIn("dynamic-import", self.rules())

    def test_unrelated_local_alias_cannot_hide_private_attribute(self):
        self.write("qa/domain.py", "import qa.contracts as c\ndef read():\n    return c._hidden\ndef unrelated():\n    import json as c\n    return c.dumps({})\n")
        self.assertIn("private-import", self.rules())

    def test_dotted_import_cannot_expose_package_facade(self):
        self.write("qa/domain.py", "import qa.contracts\nvalue = qa.Runner\n")
        self.assertIn("facade-import", self.rules())

    def test_dotted_import_can_access_allowed_submodule(self):
        self.write("qa/domain.py", "import qa.contracts\nvalue = qa.contracts.Evidence\n")
        self.assertEqual([], self.inspect()["violations"])

    def test_nested_runtime_sources_are_registered_and_inspected(self):
        self.write("qa/runtime/__init__.py", "")
        self.write("qa/runtime/hidden.py", "def run(): pass\n")
        self.write("qa/domain.py", "from qa.runtime.hidden import run\n")
        self.assertIn("unregistered", self.rules())

    def test_unregistered_local_import_target_cannot_be_hidden(self):
        result = policy.inspect(self.root, self.registry, {"qa/domain.py": "from qa.unknown import run\n"})
        self.assertIn("unregistered-import", {v["rule"] for v in result["violations"]})

    def test_unlisted_third_party_sdk_requires_explicit_declaration(self):
        self.write("qa/domain.py", "import sqlalchemy\n")
        self.assertIn("external-dependency", self.rules())

    def test_declared_pure_external_dependency_is_allowed(self):
        self.registry["components"][2]["external_dependencies"] = ["pydantic"]
        self.write("qa/domain.py", "import pydantic\n")
        self.assertEqual([], self.inspect()["violations"])

    def test_new_external_dependency_requires_review_and_documentation(self):
        changed = copy.deepcopy(self.registry)
        changed["components"][2]["external_dependencies"] = ["sqlalchemy"]
        self.assertTrue(policy.check_registry_change(self.registry, changed))

    def test_unknown_dynamic_target_is_rejected(self):
        self.write("qa/domain.py", "__import__(input())\n")
        self.assertIn("dynamic-import", self.rules())

    def test_new_unregistered_package_is_rejected(self):
        self.write("surprise/__init__.py", "")
        self.assertIn("unregistered", self.rules())

    def test_domain_cannot_import_database_or_model_sdk(self):
        self.write("qa/domain.py", "import sqlite3\nimport requests\n")
        self.assertEqual(2, sum(v["rule"] == "external-io" for v in self.inspect()["violations"]))

    def test_registered_internal_module_is_not_public(self):
        self.registry["components"][1]["modules"].append("qa.contract_internal")
        self.write("qa/contract_internal.py", "")
        self.write("qa/domain.py", "import qa.contract_internal\n")
        self.assertIn("nonpublic-import", self.rules())

    def debt(self, rule="dependency", source="qa.contracts", target="qa.domain"):
        return {"rule": rule, "source": source, "target": target, "member": "",
                "reason": "Legacy reference scheduled for extraction.", "task": "D001"}

    def test_unchanged_approved_debt_is_reported_but_passes(self):
        debt = self.debt()
        self.assertEqual([], policy.check_baseline([debt], [debt], [debt]))

    def test_exception_expansion_is_rejected(self):
        old, new = self.debt(), self.debt(source="qa.entry")
        self.assertTrue(policy.check_baseline([old, new], [old, new], [old]))

    def test_removal_requires_baseline_shrink(self):
        old = self.debt()
        self.assertTrue(policy.check_baseline([], [old], [old]))
        self.assertEqual([], policy.check_baseline([], [], [old]))

    def test_removed_violation_cannot_be_restored(self):
        old = self.debt()
        self.assertTrue(policy.check_baseline([old], [old], []))

    def test_cycle_expansion_is_rejected(self):
        old = self.debt("cycle")
        new = self.debt("cycle", source="qa.entry")
        self.assertTrue(policy.check_baseline([old, new], [old], [old]))

    def test_wildcard_and_blank_reason_are_rejected(self):
        for key, value in [("target", "qa.*"), ("reason", ""), ("task", "")]:
            with self.subTest(key=key):
                debt = self.debt(); debt[key] = value
                self.assertTrue(policy.check_baseline([debt], [debt], [debt]))

    def test_bootstrap_debt_must_come_from_target_revision(self):
        debt = self.debt()
        self.assertTrue(policy.check_baseline([debt], [debt], None, []))
        self.assertEqual([], policy.check_baseline([debt], [debt], None, [debt]))

    def test_registry_reclassification_cannot_weaken_existing_policy(self):
        weakened = copy.deepcopy(self.registry)
        weakened["components"][2]["kind"] = "bootstrap"
        self.assertTrue(policy.check_registry_change(self.registry, weakened))

    def test_missing_readme_fails_even_with_unchanged_reason(self):
        self.feature(reasons={"domain": "No public interface or behavior changes in this refactor."})
        (self.root / "docs/README.md").unlink()
        self.assertTrue(self.doc_errors())

    def test_missing_branch_note_is_rejected(self):
        self.assertTrue(self.doc_errors())

    def test_readme_update_satisfies_document_sync(self):
        self.feature()
        self.assertEqual([], self.doc_errors(["qa/domain.py", "docs/README.md"]))

    def test_explicit_readme_reason_is_accepted(self):
        self.feature(reasons={"domain": "Internal refactor preserves interface, behavior, dependencies and ownership."})
        self.assertEqual([], self.doc_errors())

    def test_other_component_reason_cannot_exempt_changed_module(self):
        self.feature(reasons={"entry": "Internal entry implementation only; no changes to public behavior."})
        self.assertTrue(self.doc_errors())

    def test_wrong_source_branch_is_rejected(self):
        self.feature(branch="feature/wrong")
        self.assertTrue(self.doc_errors(["qa/domain.py", "docs/README.md"]))

    def test_merge_push_validates_original_branch_document(self):
        self.feature()
        self.assertEqual([], self.doc_errors(["qa/domain.py", "docs/README.md", "docs/features/demo.md"], mode="merged", branch="main"))

    def test_missing_section_or_placeholder_is_rejected(self):
        self.feature()
        target = self.root / "docs/features/demo.md"
        content = target.read_text(encoding="utf-8")
        target.write_text(content.replace("## 回滚方式\nVerified scope; 未运行：this is a synthetic fixture.", "## 回滚方式\nTODO"), encoding="utf-8")
        self.assertTrue(self.doc_errors(["qa/domain.py", "docs/README.md"]))

    def test_broken_local_document_link_is_rejected(self):
        self.feature(reasons={"domain": "No change to any externally visible interface or data semantics."})
        with (self.root / "docs/README.md").open("a", encoding="utf-8") as stream:
            stream.write("\n[missing](missing.md)\n")
        self.assertTrue(self.doc_errors())

    def test_independent_skill_readme_cannot_be_omitted(self):
        self.registry["additional_readmes"] = ["qa/skill/README.md"]
        self.feature(reasons={"domain": "No change to externally visible behavior or ownership."})
        self.assertTrue(self.doc_errors())

    def register_skill(self):
        self.registry["directory_roots"] = ["qa/skills/"]
        skill = component("skill", [], "contract")
        skill["assets"] = ["qa/skills/demo/"]
        skill["readme"] = "qa/skills/demo/README.md"
        self.registry["components"].append(skill)
        self.write(skill["readme"], (self.root / "docs/README.md").read_text(encoding="utf-8"))
        self.write("qa/skills/demo/SKILL.md", "Current skill instructions.\n")

    def test_independent_skill_requires_own_readme_sync(self):
        self.register_skill()
        self.feature(components=["skill"])
        self.assertTrue(self.doc_errors(["qa/skills/demo/SKILL.md", "docs/README.md"]))
        self.assertEqual([], self.doc_errors(["qa/skills/demo/SKILL.md", "qa/skills/demo/README.md"]))

    def test_new_independent_skill_requires_registration(self):
        self.register_skill()
        self.feature(components=["skill"], reasons={"skill": "No changes to skill interfaces, dependencies or behavior."})
        self.write("qa/skills/new/SKILL.md", "New independent skill.\n")
        self.assertTrue(self.doc_errors(["qa/skills/new/SKILL.md"]))

    def test_removed_component_cannot_avoid_change_document(self):
        previous = copy.deepcopy(self.registry)
        self.registry["components"].pop(2)
        self.registry["components"][2]["allows"].remove("domain")
        self.feature(components=["entry"], reasons={"entry": "No entry interface, behavior or ownership changes."})
        errors = documentation.check(self.root, self.registry, "feature/demo", ["qa/domain.py"], "branch", previous)
        self.assertTrue(any("affected component" in error for error in errors))

    def test_removed_asset_cannot_avoid_change_document(self):
        previous = copy.deepcopy(self.registry)
        previous['components'][2]['assets'] = ['rules.json']
        self.feature(components=['entry'], reasons={'entry': 'Entry has no changed behavior or public interface.'})
        errors = documentation.check(self.root, self.registry, 'feature/demo', ['rules.json'], 'branch', previous)
        self.assertTrue(any('affected component' in error for error in errors))

    def test_import_linter_checks_actual_fixture_without_importing_it(self):
        from tools.architecture.linter import run
        self.write("qa/__init__.py", "raise RuntimeError('must not import')\n")
        self.assertEqual(0, run(self.root, self.registry, [])["exit_code"])
        self.write("qa/contracts.py", "from .domain import Evidence\n")
        self.assertNotEqual(0, run(self.root, self.registry, [])["exit_code"])

    def test_internal_business_files_can_depend_on_each_other(self):
        from tools.architecture.linter import run
        self.registry["components"][2]["modules"].append("qa.domain_helper")
        self.write("qa/domain_helper.py", "def helper(): pass\n")
        self.write("qa/domain.py", "from .domain_helper import helper\n")
        self.assertEqual([], self.inspect()["violations"])
        self.assertEqual(0, run(self.root, self.registry, [])["exit_code"])

    def test_allowlisted_contract_can_depend_on_another_contract(self):
        from tools.architecture.linter import run
        self.registry["components"].append(component("inner-contract", ["qa.inner"], "contract"))
        self.registry["components"][1]["allows"].append("inner-contract")
        self.write("qa/inner.py", "class Evidence: pass\n")
        self.write("qa/contracts.py", "from .inner import Evidence\n")
        self.assertEqual([], self.inspect()["violations"])
        self.assertEqual(0, run(self.root, self.registry, [])["exit_code"])


class CliTests(unittest.TestCase):
    def test_inventory_cli_exists_and_never_imports_business(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "qa").mkdir()
            (root / "qa/__init__.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")
            registry = {"version": 1, "components": [component("qa", ["qa"], "facade")]}
            (root / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "tools.architecture", "--root", str(root),
                                     "--registry", "registry.json", "--inventory"], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual([], json.loads(result.stdout)["violations"])


if __name__ == "__main__":
    unittest.main()
