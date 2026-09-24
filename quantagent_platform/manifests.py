from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, ScalarToken, TagToken

from .contracts import canonical_json
from .runner import RecipeError, RecipeRunner


_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_CATALOG_BYTES = 512 * 1024
_MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CATALOG_STATUSES = {"verified", "experimental", "disabled"}


class ManifestError(ValueError):
    """A curated Agent, Skill, or Recipe artifact failed closed validation."""


class _StrictSafeLoader(yaml.SafeLoader):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ManifestError(f"Agent catalog contains duplicate key: {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ManifestError(f"Agent catalog contains non-JSON number: {value}")


def _assert_json_data(value: Any, location: str = "<root>") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ManifestError(f"manifest mapping key must be a string at {location}")
            _assert_json_data(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_data(item, f"{location}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ManifestError(f"manifest contains a non-JSON number at {location}")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ManifestError(
            f"manifest contains non-JSON value {type(value).__name__} at {location}"
        )


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ManifestError(f"cannot inspect {label} {path}: {exc}") from exc
    if size > limit:
        raise ManifestError(f"{label} exceeds {limit} bytes: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"cannot read {label} {path}: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _resolve_relative(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} must be a non-empty relative path")
    if "\\" in value or "://" in value:
        raise ManifestError(f"{label} must use a repository-relative '/' path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f"{label} escapes its allowed root: {value}") from exc
    return candidate


def _load_strict_yaml(path: Path) -> dict[str, Any]:
    raw = _read_bounded(path, _MAX_MANIFEST_BYTES, "manifest")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError(f"manifest must be UTF-8: {path}") from exc
    try:
        for token in yaml.scan(text, Loader=yaml.SafeLoader):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise ManifestError(
                    f"manifest aliases, anchors, and explicit tags are forbidden: {path}"
                )
            if isinstance(token, ScalarToken) and token.value == "<<":
                raise ManifestError(f"manifest merge keys are forbidden: {path}")
        documents = list(yaml.load_all(text, Loader=_StrictSafeLoader))
    except ManifestError:
        raise
    except yaml.YAMLError as exc:
        raise ManifestError(f"cannot parse manifest {path}: {exc}") from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise ManifestError(f"manifest must contain exactly one object document: {path}")
    _assert_json_data(documents[0])
    return documents[0]


def _format_validation_error(exc: ValidationError) -> str:
    location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
    return f"{location}: {exc.message}"


def _validate_schema(value: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        schema = json.loads(_read_bounded(schema_path, _MAX_MANIFEST_BYTES, "schema"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    except (json.JSONDecodeError, SchemaError) as exc:
        raise ManifestError(f"invalid repository schema {schema_path}: {exc}") from exc
    if errors:
        detail = "; ".join(_format_validation_error(item) for item in errors[:10])
        raise ManifestError(f"{label} does not satisfy {schema_path.name}: {detail}")


@dataclass(frozen=True)
class LoadedManifest:
    path: Path
    sha256: str
    data: dict[str, Any]


def load_agent_manifest(path: str | Path) -> LoadedManifest:
    manifest_path = Path(path).resolve()
    raw = _read_bounded(manifest_path, _MAX_MANIFEST_BYTES, "AgentManifest")
    data = _load_strict_yaml(manifest_path)
    schema_names = {
        "quantagent.agent_manifest.v1": "quantagent.agent_manifest.v1.schema.json",
        "quantagent.agent_manifest.v2": "quantagent.agent_manifest.v2.schema.json",
    }
    schema_name = schema_names.get(data.get("manifest_type"))
    if schema_name is None:
        raise ManifestError("unsupported AgentManifest version")
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / schema_name
    _validate_schema(data, schema_path, "AgentManifest")
    return LoadedManifest(path=manifest_path, sha256=_sha256_bytes(raw), data=data)


def _verify_skill_content(manifest_path: Path, data: dict[str, Any]) -> None:
    content = data["content"]
    declared_rows = content["files"]
    seen: set[str] = set()
    actual_rows: list[dict[str, str]] = []
    for row in declared_rows:
        relative_path = row["path"]
        if relative_path in seen:
            raise ManifestError(f"SkillManifest contains duplicate content path: {relative_path}")
        seen.add(relative_path)
        file_path = _resolve_relative(manifest_path.parent, relative_path, "Skill content path")
        if not file_path.is_file():
            raise ManifestError(f"Skill content file does not exist: {file_path}")
        raw = _read_bounded(file_path, _MAX_SKILL_FILE_BYTES, "Skill content file")
        actual = _sha256_bytes(raw)
        if actual != row["sha256"]:
            raise ManifestError(
                f"Skill content SHA-256 mismatch for {relative_path}: {actual} != {row['sha256']}"
            )
        actual_rows.append({"path": relative_path, "sha256": actual})
    if content["entrypoint"] not in seen:
        raise ManifestError("SkillManifest entrypoint must be listed in content.files")
    package_sha256 = hashlib.sha256(
        canonical_json(sorted(actual_rows, key=lambda item: item["path"])).encode("utf-8")
    ).hexdigest()
    if package_sha256 != content["package_sha256"]:
        raise ManifestError(
            f"Skill package SHA-256 mismatch: {package_sha256} != {content['package_sha256']}"
        )


def load_skill_manifest(path: str | Path) -> LoadedManifest:
    manifest_path = Path(path).resolve()
    raw = _read_bounded(manifest_path, _MAX_MANIFEST_BYTES, "SkillManifest")
    data = _load_strict_yaml(manifest_path)
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "quantagent.skill_manifest.v1.schema.json"
    _validate_schema(data, schema_path, "SkillManifest")
    _verify_skill_content(manifest_path, data)
    return LoadedManifest(path=manifest_path, sha256=_sha256_bytes(raw), data=data)


@dataclass(frozen=True)
class CatalogEntry:
    kind: str
    identifier: str
    version: str
    status: str
    path: Path
    sha256: str
    artifact: LoadedManifest | dict[str, Any]


class AgentCatalog:
    def __init__(
        self,
        *,
        path: Path,
        sha256: str,
        version: str,
        entries: Iterable[CatalogEntry],
    ) -> None:
        self.path = path
        self.sha256 = sha256
        self.version = version
        self._entries: dict[tuple[str, str, str], CatalogEntry] = {}
        for entry in entries:
            key = (entry.kind, entry.identifier, entry.version)
            if key in self._entries:
                raise ManifestError(f"duplicate catalog entry: {key}")
            self._entries[key] = entry

    @classmethod
    def load(cls, path: str | Path, *, root: str | Path | None = None) -> "AgentCatalog":
        catalog_path = Path(path).resolve()
        repository_root = Path(root).resolve() if root is not None else catalog_path.parent.parent.resolve()
        raw = _read_bounded(catalog_path, _MAX_CATALOG_BYTES, "Agent catalog")
        try:
            value = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManifestError(f"cannot parse Agent catalog {catalog_path}: {exc}") from exc
        if not isinstance(value, dict) or set(value) != {"catalog_version", "agents", "skills", "recipes"}:
            raise ManifestError("Agent catalog must contain only catalog_version, agents, skills, and recipes")
        version = value["catalog_version"]
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise ManifestError("Agent catalog_version must be an exact SemVer")

        entries: list[CatalogEntry] = []
        for plural, kind in (("agents", "agent"), ("skills", "skill"), ("recipes", "recipe")):
            rows = value[plural]
            if not isinstance(rows, list) or not rows:
                raise ManifestError(f"Agent catalog {plural} must be a non-empty array")
            for row in rows:
                entries.append(cls._load_entry(repository_root, kind, row))
        return cls(
            path=catalog_path,
            sha256=_sha256_bytes(raw),
            version=version,
            entries=entries,
        )

    @staticmethod
    def _load_entry(root: Path, kind: str, row: Any) -> CatalogEntry:
        if not isinstance(row, dict) or set(row) != {"id", "version", "status", "path", "sha256"}:
            raise ManifestError(f"{kind} catalog entry has unknown or missing fields")
        identifier = row["id"]
        version = row["version"]
        status = row["status"]
        expected_sha256 = row["sha256"]
        if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
            raise ManifestError(f"invalid {kind} catalog id: {identifier!r}")
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise ManifestError(f"invalid {kind} catalog version: {version!r}")
        if status not in _CATALOG_STATUSES:
            raise ManifestError(f"invalid {kind} catalog status: {status!r}")
        if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
            raise ManifestError(f"invalid {kind} catalog SHA-256")
        artifact_path = _resolve_relative(root, row["path"], f"{kind} catalog path")
        raw = _read_bounded(artifact_path, _MAX_CATALOG_BYTES, f"{kind} catalog artifact")
        actual_sha256 = _sha256_bytes(raw)
        if actual_sha256 != expected_sha256:
            raise ManifestError(
                f"{kind} catalog SHA-256 mismatch for {artifact_path}: "
                f"{actual_sha256} != {expected_sha256}"
            )

        if kind == "agent":
            artifact: LoadedManifest | dict[str, Any] = load_agent_manifest(artifact_path)
            actual_id = artifact.data["agent_id"]
            actual_version = artifact.data["version"]
        elif kind == "skill":
            artifact = load_skill_manifest(artifact_path)
            actual_id = artifact.data["skill_id"]
            actual_version = artifact.data["version"]
        else:
            try:
                artifact = RecipeRunner.load_recipe(artifact_path)
            except RecipeError as exc:
                raise ManifestError(f"invalid catalog Recipe {artifact_path}: {exc}") from exc
            actual_id = artifact["recipe_id"]
            actual_version = artifact["recipe_version"]
        if (actual_id, actual_version) != (identifier, version):
            raise ManifestError(
                f"{kind} catalog identity mismatch: {(identifier, version)} != "
                f"{(actual_id, actual_version)}"
            )
        return CatalogEntry(
            kind=kind,
            identifier=identifier,
            version=version,
            status=status,
            path=artifact_path,
            sha256=actual_sha256,
            artifact=artifact,
        )

    def get(self, kind: str, identifier: str, version: str) -> CatalogEntry:
        try:
            entry = self._entries[(kind, identifier, version)]
        except KeyError as exc:
            raise ManifestError(
                f"{kind} is not installed or allow-listed at the exact version: "
                f"{identifier}@{version}"
            ) from exc
        if entry.status == "disabled":
            raise ManifestError(f"{kind} is disabled: {identifier}@{version}")
        return entry

    def rows(self) -> list[dict[str, str]]:
        return [
            {
                "kind": entry.kind,
                "id": entry.identifier,
                "version": entry.version,
                "status": entry.status,
                "path": str(entry.path),
                "sha256": entry.sha256,
            }
            for entry in sorted(
                self._entries.values(),
                key=lambda item: (item.kind, item.identifier, item.version),
            )
        ]
