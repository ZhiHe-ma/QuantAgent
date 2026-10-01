"""Locate test resources independently of directory depth and current cwd."""

from pathlib import Path


def repository_root(start: Path) -> Path:
    directory = start.resolve().parent
    for candidate in (directory, *directory.parents):
        if (candidate / "agent_engine.py").is_file() and all(
            (candidate / name).is_dir()
            for name in ("quantagent_platform", "recipes", "tests")
        ):
            return candidate
    raise FileNotFoundError(f"No QuantAgent repository markers above {start}")


ROOT: Path = repository_root(Path(__file__))
