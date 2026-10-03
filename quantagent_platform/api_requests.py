"""Operator-registered input admission and bounded HTTP request parsing."""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from fastapi import Request
from pydantic import ValidationError
from .contracts import ContractError
from .research_contracts import validate_review_fixture
from .api_contracts import (
    RegisteredFixture, SubmitRunRequest, ArtifactIntegrityError, InvalidSubmission, SubmissionTooLarge,
)
from .api_storage import read_bounded as _read_bounded

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{15,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_BODY_BYTES = 4096
_MAX_FIXTURE_BYTES = 2 * 1024 * 1024
_SELECTION = {
    "agent_id": "builtin.research-agent",
    "agent_version": "1.0.0",
    "skill_id": "anthropic-financial-services-adapted.thesis-tracker",
    "skill_version": "1.0.0",
    "recipe_id": "thesis-tracker",
    "recipe_version": "1.0.0",
}
_BINDINGS = {"source.thesis_review": "builtin.json-thesis-review-source"}
_PERMISSIONS = {"filesystem:read", "filesystem:write"}


@dataclass(frozen=True)
class SubmissionConfig:
    """The operator, not an HTTP client, chooses the readable fixture files."""

    fixtures: dict[str, str | Path]
    registered: dict[str, RegisteredFixture] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.fixtures:
            raise ValueError("at least one registered fixture is required")
        registered: dict[str, RegisteredFixture] = {}
        for fixture_id, value in self.fixtures.items():
            if not isinstance(fixture_id, str) or not _ID.fullmatch(fixture_id):
                raise ValueError("fixture ids must use 1-64 safe characters")
            path = Path(value).expanduser()
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"registered fixture is not a regular file: {fixture_id}")
            path = path.resolve(strict=True)
            try:
                content = _read_bounded(path, _MAX_FIXTURE_BYTES)
                fixture = _decode_fixture(content)
                validate_review_fixture(fixture)
            except (ArtifactIntegrityError, ContractError, ValueError) as exc:
                raise ValueError(f"registered fixture failed validation: {fixture_id}") from exc
            registered[fixture_id] = RegisteredFixture(
                path=path,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        object.__setattr__(self, "registered", registered)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON number")


def _decode_fixture(content: bytes) -> dict[str, Any]:
    value = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("fixture must be a JSON object")
    return value


async def _request_value(request: Request) -> SubmitRunRequest:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise InvalidSubmission()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY_BYTES:
            raise SubmissionTooLarge()
        chunks.append(chunk)
    try:
        value = _decode_fixture(b"".join(chunks))
        parsed = SubmitRunRequest.model_validate(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise InvalidSubmission() from exc
    if (
        not _ID.fullmatch(parsed.fixture_id)
        or not _ID.fullmatch(parsed.request_id)
        or not _SHA256.fullmatch(parsed.fixture_sha256)
    ):
        raise InvalidSubmission()
    return parsed


def decode_fixture(content: bytes) -> dict[str, Any]:
    """Public strict fixture/task JSON decoding with original rejection rules."""
    return _decode_fixture(content)


async def parse_submission_request(request: Request) -> SubmitRunRequest:
    """Public streamed request admission; retains content type, size and field checks."""
    return await _request_value(request)


KEY_PATTERN = _KEY
MAX_FIXTURE_BYTES = _MAX_FIXTURE_BYTES
RESEARCH_SELECTION = _SELECTION
RESEARCH_BINDINGS = _BINDINGS
RESEARCH_PERMISSIONS = _PERMISSIONS
