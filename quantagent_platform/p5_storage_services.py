"""Concrete P5 local storage and filesystem control, behind owned public ports."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

from .p5_ledger import HandoffLedger
from .p5_ports import ApprovedRun, HandoffError
from .p5_registry import (
    ApprovedRunRegistry, approved_source_from_pins, bounded_regular_file,
    path_signatures, read_approved_source,
)

@contextmanager
def exclusive_controller(root: Path):
    """One P5 controller at a time, including crash recovery and dispatch."""
    lock_path = root / ".p5_controller.lock"
    if lock_path.is_symlink() or lock_path.is_junction():
        raise HandoffError("P5 controller lock path is a link")
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            until = time.monotonic() + 130
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= until:
                        raise HandoffError("P5 controller lock is busy") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_bytes(path: Path, raw: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class LocalP5Services:
    def read_file(self, path: Path, limit: int) -> bytes:
        return bounded_regular_file(path, limit)

    def path_signatures(self, path: Path):
        return path_signatures(path)

    def same_directory(self, left: Path, right: Path) -> bool:
        return left.samefile(right)

    def approved_registry(self, path: Path, run_root: Path):
        return ApprovedRunRegistry.load(path, run_root)

    def source_from_pins(self, pins: dict[str, object], run_root: Path,
                         source_type: type[ApprovedRun] = ApprovedRun) -> ApprovedRun:
        return approved_source_from_pins(pins, run_root, source_type)

    def read_approved_source(self, source: ApprovedRun):
        return read_approved_source(source)

    def new_ledger(self, root: Path):
        return HandoffLedger(root)

    def handoff_schema(self) -> dict:
        schema = Path(__file__).resolve().parents[1] / "schemas" / "quantagent.agent_handoff.v1.schema.json"
        return json.loads(schema.read_text(encoding="utf-8"))

    def prepare_run_root(self, path: Path) -> Path:
        root = path.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def prepare_broker_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=False)

    def controller_lock(self, root: Path):
        return exclusive_controller(root)

    def atomic_bytes(self, path: Path, raw: bytes) -> None:
        atomic_bytes(path, raw)
