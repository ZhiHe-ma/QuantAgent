"""Real UTF-8 documents and CLI fixtures for bounded, read-only context plans."""
from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.support.paths import ROOT


def capability(name, readme):
    return {"id": name, "kind": "module", "modules": [], "public_modules": [],
            "allows": [], "assets": [], "readme": readme, "data_owner": "synthetic"}


class DocumentFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="doc budget ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo with spaces"
        self.root.mkdir()
        for path in ("AGENTS.md", "README.md", "docs/ARCHITECTURE.md", "docs/DEVELOPMENT_TESTING.md"):
            self.write(path, "规\n")
        self.write("qa/README.md", "中\n文\n")
        self.registry = {"version": 1, "components": [capability("alpha", "qa/README.md")]}
        self.policy = {"version": 1, "document": {"max_lines": 160, "max_characters": 9000},
                       "context": {"max_lines": 300, "max_characters": 15000}}

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    def save_policy(self, policy=None):
        self.write("docs/architecture/documentation-budget.json", json.dumps(policy or self.policy))


class DocumentationBudgetTests(DocumentFixture):
    def setUp(self):
        super().setUp()
        spec = importlib.util.find_spec("tools.architecture.budget")
        self.assertIsNotNone(spec, "document/context budget checker is not implemented")
        self.budget = importlib.import_module("tools.architecture.budget")

    def bundle(self, names=("alpha",)):
        return self.budget.reading_bundle(self.root, self.registry, list(names), self.policy)

    def test_utf8_bom_and_crlf_have_platform_independent_counts(self):
        self.root.joinpath("qa/README.md").write_bytes(b"\xef\xbb\xbf" + "中\r\n文\r\n".encode("utf-8"))
        result = self.bundle()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["totals"], {"lines": 5, "characters": 10})
        self.assertEqual([d["path"] for d in result["documents"]],
                         ["AGENTS.md", "docs/ARCHITECTURE.md", "docs/DEVELOPMENT_TESTING.md", "qa/README.md"])
        self.assertEqual(result["documents"][-1]["characters"], 4)

    def test_shared_readmes_and_repeated_capabilities_are_counted_once(self):
        self.registry["components"].append(capability("beta", "qa/./README.md"))
        result = self.bundle(("alpha", "beta", "alpha"))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["components"], ["alpha", "beta"])
        self.assertEqual(len(result["documents"]), 4)
        self.assertEqual(result["totals"], {"lines": 5, "characters": 10})

    def test_document_limits_accept_exact_boundary_and_reject_growth(self):
        self.policy["document"] = {"max_lines": 2, "max_characters": 4}
        self.assertEqual(self.bundle()["status"], "PASS")
        for text, dimension in (("中\n文\n字\n", "lines"), ("中文文字\n", "characters")):
            with self.subTest(dimension=dimension):
                self.write("qa/README.md", text)
                result = self.bundle()
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(any("qa/README.md" in e and dimension in e for e in result["errors"]))

    def test_aggregate_context_overflow_reports_full_plan_without_rewriting(self):
        self.policy["context"] = {"max_lines": 5, "max_characters": 10}
        self.assertEqual(self.bundle()["status"], "PASS")
        self.write("qb/README.md", "甲\n乙\n")
        self.registry["components"].append(capability("beta", "qb/README.md"))
        before = {p: (self.root / p).read_bytes() for p in ("qa/README.md", "qb/README.md")}
        result = self.bundle(("alpha", "beta"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["totals"], {"lines": 7, "characters": 14})
        self.assertEqual(len(result["documents"]), 5)
        self.assertTrue(any("context" in e and "lines" in e for e in result["errors"]))
        self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})

    def test_unknown_capability_missing_document_and_escape_fail_closed(self):
        result = self.bundle(("typo",))
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("unknown" in e and "typo" in e for e in result["errors"]))
        self.root.joinpath("docs/ARCHITECTURE.md").unlink()
        self.assertEqual(self.bundle()["status"], "FAIL")
        self.write("docs/ARCHITECTURE.md", "规\n")
        outside = self.root.parent / "outside.md"
        outside.write_bytes(b"\xff")
        self.registry["components"][0]["readme"] = "../outside.md"
        result = self.bundle()
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("out-of-repository" in e for e in result["errors"]))

    def test_all_registered_and_additional_readmes_are_checked(self):
        self.registry["components"].append(capability("beta", "qb/README.md"))
        self.registry["additional_readmes"] = ["docs/extra/README.md"]
        self.write("qb/README.md", "规\n")
        self.write("docs/extra/README.md", "规\n")
        for path in ("qb/README.md", "docs/extra/README.md", "README.md"):
            with self.subTest(path=path):
                self.write(path, "x\n" * 161)
                result = self.budget.check(self.root, self.registry, self.policy)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(any(path in e and "lines" in e for e in result["errors"]))
                self.write(path, "规\n")

    def test_unregistered_history_is_preserved_and_not_in_default_context(self):
        history = "old evidence\n" * 20000
        self.write("docs/features/old.md", history)
        self.write("docs/superpowers/plans/old.md", history)
        result = self.budget.check(self.root, self.registry, self.policy)
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("docs/features/old.md", [d["path"] for d in result["documents"]])
        self.assertEqual((self.root / "docs/features/old.md").read_text(encoding="utf-8"), history)

    def test_registered_readme_cannot_hide_in_history_directory(self):
        self.write("docs/features/old.md", "x\n" * 161)
        self.registry["components"][0]["readme"] = "docs/features/old.md"
        result = self.budget.check(self.root, self.registry, self.policy)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("docs/features/old.md" in e for e in result["errors"]))

    def test_policy_is_strict_and_target_limits_cannot_expand(self):
        for key in ("document", "context"):
            for dimension in ("max_lines", "max_characters"):
                with self.subTest(key=key, dimension=dimension):
                    expanded = copy.deepcopy(self.policy)
                    expanded[key][dimension] += 1
                    self.save_policy(expanded)
                    with self.assertRaises(ValueError):
                        self.budget.load_policy(self.root, previous=self.policy)
        reduced = copy.deepcopy(self.policy)
        reduced["document"]["max_lines"] -= 1
        self.save_policy(reduced)
        self.assertEqual(self.budget.load_policy(self.root, previous=self.policy), reduced)
        invalid = []
        for value in (True, 0, -1, 1.5, "160"):
            p = copy.deepcopy(self.policy);p["document"]["max_lines"] = value;invalid.append(p)
        p = copy.deepcopy(self.policy);p["version"] = True;invalid.append(p)
        p = copy.deepcopy(self.policy);p["version"] = 2;invalid.append(p)
        p = copy.deepcopy(self.policy);p.pop("context");invalid.append(p)
        p = copy.deepcopy(self.policy);p["document"]["ignore"] = ["*"];invalid.append(p)
        for p in invalid:
            with self.subTest(policy=p):
                self.save_policy(p)
                with self.assertRaises(ValueError): self.budget.load_policy(self.root)
        self.write("docs/architecture/documentation-budget.json", '{"version":1,"version":1}')
        with self.assertRaises(ValueError): self.budget.load_policy(self.root)


class DocumentationBudgetCliTests(DocumentFixture):
    def cli(self, *args, without_git=False):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if without_git:
            env["PATH"] = ""
        return subprocess.run([sys.executable, "-m", "tools.architecture", "--root", str(self.root), *args],
                              cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=30)

    def prepare_cli(self):
        self.save_policy()
        self.write("docs/architecture/components.json", json.dumps(self.registry))
        self.write("qa/domain.py", "raise RuntimeError('business must not execute')\n")

    def test_context_cli_works_without_git_and_writes_only_requested_report(self):
        self.prepare_cli()
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        proc = self.cli("--context-for", "alpha", "--report", "context.json", without_git=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(data["totals"], {"lines": 5, "characters": 10})
        self.assertEqual(json.loads((self.root / "context.json").read_text(encoding="utf-8")), data)
        after = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        after.pop("context.json")
        self.assertEqual(before, after)

    def test_context_cli_rejects_unknown_scope_and_overflow(self):
        self.prepare_cli()
        proc = self.cli("--context-for", "missing", without_git=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "FAIL")
        self.write("qa/README.md", "x\n" * 161)
        proc = self.cli("--context-for", "alpha", without_git=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(any("qa/README.md" in e for e in json.loads(proc.stdout)["errors"]))

    def test_missing_policy_cannot_disable_context_check(self):
        self.prepare_cli()
        self.root.joinpath("docs/architecture/documentation-budget.json").unlink()
        proc = self.cli("--context-for", "alpha", without_git=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("documentation-budget.json", proc.stderr)

    def test_existing_gate_automatically_rejects_oversized_readme(self):
        self.prepare_cli()
        self.registry["components"][0].update(modules=["qa", "qa.domain"], public_modules=["qa", "qa.domain"], assets=["qa/"])
        self.write("qa/__init__.py", "")
        self.write("docs/architecture/components.json", json.dumps(self.registry))
        self.write("qa/README.md", "# fixture\n" + "\n".join(
            f"## {s}\nSynthetic documented behavior.\n" for s in
            ("职责与边界", "文件导航", "对外接口", "依赖规则", "数据与权限", "测试与验收", "已知限制")))
        baseline = {"version": 1, "origin_commit": "a" * 40, "exceptions": [], "tasks": {}}
        self.write("docs/architecture/legacy-baseline.json", json.dumps(baseline))
        meta = {"branch": "feature/demo", "base_commit": "a" * 40, "components": ["alpha"], "readme_unchanged": {}}
        self.write("docs/features/demo.md", "```json\n" + json.dumps(meta) + "\n```\n" + "\n".join(
            f"## {s}\nSynthetic acceptance evidence.\n" for s in
            ("目标与非目标", "涉及模块", "接口或数据变化", "新增依赖", "测试证据", "回滚方式", "遗留问题")))
        git = ["git", "-c", "safe.directory=" + self.root.as_posix(), "-C", str(self.root)]
        for args in (("init",), ("add", "."), ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")):
            result = subprocess.run(git + list(args), capture_output=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with self.root.joinpath("qa/README.md").open("a", encoding="utf-8") as file:
            file.write("x\n" * 200)
        proc = self.cli("--base-ref", "HEAD", "--branch", "feature/demo", "--report", "gate.json")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        report = json.loads((self.root / "gate.json").read_text(encoding="utf-8"))
        self.assertTrue(any("qa/README.md" in e and "lines" in e for e in report["documentation_budget"]["errors"]))
        self.assertIn("document", proc.stderr)
