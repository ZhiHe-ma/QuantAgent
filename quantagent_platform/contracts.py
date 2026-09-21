from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class ContractError(ValueError):
    """A packet does not satisfy the declared QuantAgent data contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_aware_timestamp(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty ISO 8601 timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ContractError(f"{field_name} is not a valid ISO 8601 timestamp: {value}") from exc
    if parsed.utcoffset() is None:
        raise ContractError(f"{field_name} must include a timezone offset")
    return parsed


@dataclass(frozen=True)
class DataPacket:
    """Versioned, hash-addressed payload exchanged between plugins."""

    contract_version: str
    packet_type: str
    source: str
    created_at: str
    records: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    content_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        contract_version: str,
        packet_type: str,
        source: str,
        records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> "DataPacket":
        record_tuple = tuple(records)
        digest = sha256_json(record_tuple)
        packet = cls(
            contract_version=contract_version,
            packet_type=packet_type,
            source=source,
            created_at=created_at or utc_now(),
            records=record_tuple,
            metadata=dict(metadata or {}),
            content_sha256=digest,
        )
        packet.validate()
        return packet

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DataPacket":
        packet = cls(
            contract_version=value.get("contract_version", ""),
            packet_type=value.get("packet_type", ""),
            source=value.get("source", ""),
            created_at=value.get("created_at", ""),
            records=tuple(value.get("records", [])),
            metadata=dict(value.get("metadata", {})),
            content_sha256=value.get("content_sha256", ""),
        )
        packet.validate()
        return packet

    def validate(self) -> None:
        for field_name in ("contract_version", "packet_type", "source"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"{field_name} must be a non-empty string")
        parse_aware_timestamp(self.created_at, "created_at")
        if not isinstance(self.records, tuple) or any(not isinstance(row, dict) for row in self.records):
            raise ContractError("records must contain only objects")
        if not isinstance(self.metadata, dict):
            raise ContractError("metadata must be an object")
        expected = sha256_json(self.records)
        if self.content_sha256 != expected:
            raise ContractError("content_sha256 does not match packet records")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "packet_type": self.packet_type,
            "source": self.source,
            "created_at": self.created_at,
            "records": list(self.records),
            "metadata": self.metadata,
            "content_sha256": self.content_sha256,
        }
