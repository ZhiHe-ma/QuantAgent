import copy
import json
import re
import unittest
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker, ValidationError
except ImportError:  # CI and the P1 Agent runtime install requirements-test.txt/requirements.txt.
    Draft202012Validator = None
    FormatChecker = None
    ValidationError = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_PATHS = (
    SCHEMA_DIR / "quantagent.agent_manifest.v1.schema.json",
    SCHEMA_DIR / "quantagent.skill_manifest.v1.schema.json",
)
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
EXAMPLES = {
    SCHEMA_PATHS[0]: ROOT / "examples" / "manifests" / "research-agent.example.json",
    SCHEMA_PATHS[1]: ROOT / "examples" / "manifests" / "thesis-tracker.example.json",
}


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def walk(value: Any):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


class ManifestSpecTests(unittest.TestCase):
    def test_schemas_are_parseable_strict_draft_2020_12_documents(self):
        for path in SCHEMA_PATHS:
            schema = load_schema(path)
            self.assertEqual(schema["$schema"], DRAFT_2020_12)
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(schema["required"])
            self.assertTrue(schema["$id"].endswith(path.name))

    def test_local_references_resolve_and_patterns_compile(self):
        for path in SCHEMA_PATHS:
            schema = load_schema(path)
            definitions = schema.get("$defs", {})
            for node in walk(schema):
                if not isinstance(node, dict):
                    continue
                reference = node.get("$ref")
                if isinstance(reference, str) and reference.startswith("#/$defs/"):
                    self.assertIn(reference.removeprefix("#/$defs/"), definitions)
                pattern = node.get("pattern")
                if isinstance(pattern, str):
                    re.compile(pattern)

    def test_control_objects_reject_unknown_fields(self):
        for path in SCHEMA_PATHS:
            schema = load_schema(path)
            for node in walk(schema):
                if not isinstance(node, dict) or "properties" not in node:
                    continue
                if set(node.get("properties", {})) == {"metadata"}:
                    continue
                self.assertIs(
                    node.get("additionalProperties"),
                    False,
                    f"control object must be strict in {path.name}: {node}",
                )

    @unittest.skipIf(Draft202012Validator is None, "install requirements-test.txt for Schema conformance tests")
    def test_schemas_and_examples_pass_pinned_draft_2020_12_validator(self):
        for schema_path, example_path in EXAMPLES.items():
            schema = load_schema(schema_path)
            example = json.loads(example_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            validator.validate(example)

            unknown = copy.deepcopy(example)
            unknown["unexpected_control_field"] = True
            with self.assertRaises(ValidationError):
                validator.validate(unknown)

            ranged = copy.deepcopy(example)
            ranged["version"] = ">=1.0.0"
            with self.assertRaises(ValidationError):
                validator.validate(ranged)

        agent_schema = load_schema(SCHEMA_PATHS[0])
        agent = json.loads(EXAMPLES[SCHEMA_PATHS[0]].read_text(encoding="utf-8"))
        agent["callable_agents"] = [{"id": "writer-agent", "version": "1.0.0"}]
        with self.assertRaises(ValidationError):
            Draft202012Validator(agent_schema).validate(agent)

        skill_schema = load_schema(SCHEMA_PATHS[1])
        skill = json.loads(EXAMPLES[SCHEMA_PATHS[1]].read_text(encoding="utf-8"))
        for unsafe_path in ("../SKILL.md", "..\\SKILL.md", "C:/SKILL.md", "https://example.com/SKILL.md"):
            unsafe = copy.deepcopy(skill)
            unsafe["content"]["files"][0]["path"] = unsafe_path
            with self.subTest(unsafe_path=unsafe_path), self.assertRaises(ValidationError):
                Draft202012Validator(skill_schema).validate(unsafe)

    def test_spec_reports_p1_runtime_and_remaining_boundaries(self):
        spec = (ROOT / "docs" / "QUANTAGENT_AGENT_SKILL_SPEC.md").read_text(encoding="utf-8")
        self.assertIn("P1 最小运行入口已实现", spec)
        self.assertIn("max_wall_seconds", spec)
        self.assertIn("尚未动态计量", spec)
        self.assertIn("quantagent.agent_manifest.v1.schema.json", spec)
        self.assertIn("quantagent.skill_manifest.v1.schema.json", spec)


if __name__ == "__main__":
    unittest.main()
