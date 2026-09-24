"""Admit one operator-pinned, completed P4 SEC run from private storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import ContractError, DataPacket
from .sec_contracts import validate_sec_packet


REGISTRY_CONTRACT = "quantagent.sec_approved_run.v1"
RAW_NAMES = (
    "sec-mara-submissions.json",
    "sec-mara-companyfacts.json",
    "sec-riot-submissions.json",
    "sec-riot-companyfacts.json",
)
_PACKET_NAMES = (
    "01-load-sec-facts.json",
    "02-summarize-sector.json",
    "03-compare-peers.json",
    "04-write-sec-report.json",
)
_STEPS = (
    ("load-sec-facts", "builtin.sec-edgar-source", "quantagent.sec_company_facts.v1"),
    ("summarize-sector", "builtin.sec-sector-overview", "quantagent.sec_sector_overview.v1"),
    ("compare-peers", "builtin.sec-peer-comparison", "quantagent.sec_peer_comparison.v1"),
    ("write-sec-report", "builtin.markdown-sec-research-report", "quantagent.report.v1"),
)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX = re.compile(r"^[a-f0-9]{64}$")
_MAX_STATE = 2 * 1024 * 1024
_MAX_PACKET = 2 * 1024 * 1024
_MAX_RAW = 8 * 1024 * 1024
_MAX_REPORT = 4 * 1024 * 1024


class ApprovedSourceError(ValueError):
    """Private approved source is missing, unsafe, or inconsistent."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ApprovedSourceError("approved JSON has duplicate keys")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ApprovedSourceError("approved JSON has a non-finite number")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ApprovedSourceError("approved JSON has a non-finite number")
    return parsed


def strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovedSourceError("approved JSON is not strict UTF-8") from exc
    if not isinstance(value, dict):
        raise ApprovedSourceError("approved JSON root must be an object")
    return value


def _signature(path: Path) -> tuple[int, int, int]:
    value = path.lstat()
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ApprovedSourceError("approved path contains a link or junction")
    return value.st_dev, value.st_ino, value.st_mode


def _path_signatures(path: Path) -> tuple[tuple[Path, tuple[int, int, int]], ...]:
    absolute = Path(os.path.abspath(path))
    pieces = tuple(reversed((absolute, *absolute.parents)))
    try:
        return tuple((piece, _signature(piece)) for piece in pieces)
    except (OSError, ValueError) as exc:
        raise ApprovedSourceError("approved path is missing or unsafe") from exc


def _windows_open_nofollow(path: Path) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 0x00000001, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot open approved file")

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD),
                    ("ReparseTag", wintypes.DWORD)]

    info = FileAttributeTagInfo()
    inspect = kernel32.GetFileInformationByHandleEx
    inspect.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    inspect.restype = wintypes.BOOL
    try:
        if not inspect(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "cannot inspect approved handle")
        if info.FileAttributes & 0x00000400:
            raise ApprovedSourceError("approved file is a reparse point")
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel32.CloseHandle(handle)
        raise


def bounded_regular_file(path: Path, limit: int) -> bytes:
    """Read one regular file by a no-follow handle and reject path replacement."""
    before = _path_signatures(path)
    fd = -1
    try:
        if os.name == "nt":
            fd = _windows_open_nofollow(path)
        else:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise ApprovedSourceError("approved file is not a bounded regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ApprovedSourceError("approved file exceeds size limit")
        after_handle = os.fstat(fd)
        after = _path_signatures(path)
        if before != after or (opened.st_dev, opened.st_ino) != (
            after_handle.st_dev, after_handle.st_ino
        ):
            raise ApprovedSourceError("approved file changed while reading")
        if (opened.st_dev, opened.st_ino) != (
            after[-1][1][0], after[-1][1][1]
        ):
            raise ApprovedSourceError("approved path changed while reading")
        return b"".join(chunks)
    except ApprovedSourceError:
        raise
    except OSError as exc:
        raise ApprovedSourceError("approved file cannot be read safely") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _validate_registry(value: dict[str, Any]) -> None:
    path = Path(__file__).resolve().parents[1] / "schemas" / "quantagent.sec_approved_run.v1.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(value))
    except (OSError, ValueError) as exc:
        raise ApprovedSourceError("approved registry schema cannot be loaded") from exc
    if errors:
        raise ApprovedSourceError("approved registry violates its v1 contract")
    ids = [row["approved_source_id"] for row in value["entries"]]
    if len(ids) != len(set(ids)):
        raise ApprovedSourceError("approved registry has duplicate source IDs")


def _safe_run_root(run_root: Path) -> Path:
    root = Path(os.path.abspath(run_root))
    _path_signatures(root)
    if not root.is_dir():
        raise ApprovedSourceError("approved run root is not a directory")
    return root


@dataclass(frozen=True)
class ApprovedRun:
    source_id: str
    run_id: str
    run_dir: Path
    registry_sha256: str
    packet_sha256: str
    report_sha256: str
    raw_sha256: dict[str, str]
    recipe_id: str
    recipe_version: str
    source_plugin_id: str
    source_plugin_version: str

    @classmethod
    def from_pins(cls, pins: dict[str, object], run_root: Path) -> "ApprovedRun":
        if not isinstance(pins, dict) or set(pins) != {
            "approved_source_id", "run_id", "recipe", "source_plugin",
            "packet_sha256", "report_sha256", "raw_sha256", "registry_sha256",
        }:
            raise ApprovedSourceError("approved handoff pins have invalid fields")
        entry = {key: value for key, value in pins.items() if key != "registry_sha256"}
        _validate_registry({"registry_version": REGISTRY_CONTRACT, "entries": [entry]})
        registry_sha = pins["registry_sha256"]
        if not isinstance(registry_sha, str) or not _HEX.fullmatch(registry_sha):
            raise ApprovedSourceError("approved registry hash is invalid")
        root = _safe_run_root(run_root)
        run_id = entry["run_id"]
        if not _RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
            raise ApprovedSourceError("approved run ID is unsafe")
        run_dir = root / run_id
        _path_signatures(run_dir)
        if not run_dir.is_dir() or run_dir.parent != root:
            raise ApprovedSourceError("approved run directory is unsafe")
        return cls(
            source_id=entry["approved_source_id"],
            run_id=run_id,
            run_dir=run_dir,
            registry_sha256=registry_sha,
            packet_sha256=entry["packet_sha256"],
            report_sha256=entry["report_sha256"],
            raw_sha256=dict(entry["raw_sha256"]),
            recipe_id=entry["recipe"]["id"],
            recipe_version=entry["recipe"]["version"],
            source_plugin_id=entry["source_plugin"]["id"],
            source_plugin_version=entry["source_plugin"]["version"],
        )

    def to_pins(self) -> dict[str, object]:
        return {
            "approved_source_id": self.source_id,
            "run_id": self.run_id,
            "recipe": {"id": self.recipe_id, "version": self.recipe_version},
            "source_plugin": {
                "id": self.source_plugin_id, "version": self.source_plugin_version
            },
            "packet_sha256": self.packet_sha256,
            "report_sha256": self.report_sha256,
            "raw_sha256": dict(self.raw_sha256),
            "registry_sha256": self.registry_sha256,
        }


class ApprovedRunRegistry:
    def __init__(self, entries: dict[str, ApprovedRun], sha256: str):
        self.entries = entries
        self.sha256 = sha256

    @classmethod
    def load(cls, path: Path, run_root: Path) -> "ApprovedRunRegistry":
        raw = bounded_regular_file(Path(path), 512 * 1024)
        value = strict_json(raw)
        _validate_registry(value)
        digest = _sha256(raw)
        entries: dict[str, ApprovedRun] = {}
        for entry in value["entries"]:
            source = ApprovedRun.from_pins(
                {**entry, "registry_sha256": digest}, run_root
            )
            entries[source.source_id] = source
        return cls(entries, digest)

    def resolve(self, source_id: str) -> ApprovedRun:
        try:
            return self.entries[source_id]
        except (KeyError, TypeError) as exc:
            raise ApprovedSourceError("approved source ID is not registered") from exc


@dataclass(frozen=True)
class SecEvidence:
    packet: DataPacket
    record_sha256: str
    packet_file_sha256: str
    sector_packet: DataPacket
    peer_packet: DataPacket
    report_packet: DataPacket
    report: bytes
    report_sha256: str
    raw: dict[str, bytes]
    raw_sha256: dict[str, str]


def read_approved_source(source: ApprovedRun) -> SecEvidence:
    try:
        _path_signatures(source.run_dir)
        if source.run_dir.name != source.run_id or not source.run_dir.is_dir():
            raise ApprovedSourceError("approved run path changed")
        state = strict_json(bounded_regular_file(source.run_dir / "run.json", _MAX_STATE))
        if (
            state.get("status") != "completed"
            or (state.get("recipe_id"), state.get("recipe_version"))
            != (source.recipe_id, source.recipe_version)
            or (source.recipe_id, source.recipe_version)
            != ("sec-industry-peers", "1.0.0")
        ):
            raise ApprovedSourceError("approved P4 run is not complete or pinned")
        steps = state.get("steps")
        if not isinstance(steps, list) or len(steps) != 4:
            raise ApprovedSourceError("approved P4 run has unexpected steps")
        packets: list[DataPacket] = []
        packet_bytes: list[bytes] = []
        for index, (step, expected, name) in enumerate(
            zip(steps, _STEPS, _PACKET_NAMES)
        ):
            step_id, plugin_id, contract = expected
            plugin_version = (
                source.source_plugin_version if index == 0 else "1.0.0"
            )
            if index == 0 and source.source_plugin_id != plugin_id:
                raise ApprovedSourceError("approved P4 source plugin changed")
            if (
                step.get("status") != "completed"
                or step.get("id") != step_id
                or step.get("plugin_id") != plugin_id
                or step.get("plugin_version") != plugin_version
                or step.get("output_contract") != contract
                or Path(str(step.get("packet_path", ""))).name != name
            ):
                raise ApprovedSourceError("approved P4 step identity changed")
            raw = bounded_regular_file(source.run_dir / name, _MAX_PACKET)
            packet = DataPacket.from_dict(strict_json(raw))
            if (
                packet.contract_version != contract
                or packet.source != plugin_id
                or packet.content_sha256 != step.get("output_sha256")
            ):
                raise ApprovedSourceError("approved P4 packet does not match its step")
            packet_bytes.append(raw)
            packets.append(packet)
        if _sha256(packet_bytes[0]) != source.packet_sha256:
            raise ApprovedSourceError("approved packet file hash mismatch")
        record = validate_sec_packet(packets[0])
        if state.get("final_contract") != "quantagent.report.v1" or (
            state.get("final_sha256") != packets[-1].content_sha256
        ):
            raise ApprovedSourceError("approved P4 final packet is inconsistent")
        sources = record["sources"]
        frozen: dict[str, bytes] = {}
        for name, row in zip(RAW_NAMES, sources):
            raw = bounded_regular_file(source.run_dir / name, _MAX_RAW)
            digest = _sha256(raw)
            if digest != source.raw_sha256[name] or digest != row["sha256"]:
                raise ApprovedSourceError("approved raw response hash mismatch")
            frozen[name] = raw
        report = bounded_regular_file(source.run_dir / "sec_industry_peers.md",
                                      _MAX_REPORT)
        report_sha = _sha256(report)
        if report_sha != source.report_sha256:
            raise ApprovedSourceError("approved report hash mismatch")
        final_records = packets[-1].records
        if len(final_records) != 1:
            raise ApprovedSourceError("approved report packet has wrong shape")
        final = final_records[0]
        if (
            final.get("format") != "markdown"
            or Path(str(final.get("path", ""))).name != "sec_industry_peers.md"
            or final.get("artifact_sha256") != report_sha
            or final.get("input_sha256") != packets[2].content_sha256
        ):
            raise ApprovedSourceError("approved report packet differs from artifact")
        return SecEvidence(
            packet=packets[0],
            record_sha256=steps[0]["output_sha256"],
            packet_file_sha256=source.packet_sha256,
            sector_packet=packets[1],
            peer_packet=packets[2],
            report_packet=packets[3],
            report=report,
            report_sha256=report_sha,
            raw=frozen,
            raw_sha256=dict(source.raw_sha256),
        )
    except ApprovedSourceError:
        raise
    except (OSError, ValueError, KeyError, TypeError, ContractError) as exc:
        raise ApprovedSourceError("approved P4 artifacts failed validation") from exc
