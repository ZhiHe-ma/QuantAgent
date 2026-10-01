import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.support.paths import repository_root


@contextmanager
def marked_root() -> Iterator[tuple[Path, Path]]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "agent_engine.py").touch()
        for name in ("quantagent_platform", "recipes", "tests"):
            (root / name).mkdir()
        nested = root / "tests" / "unit" / "research" / "test_example.py"
        nested.parent.mkdir(parents=True)
        nested.touch()
        yield root, nested


class RepositoryPathTests(unittest.TestCase):
    def test_resolves_nested_test_file(self):
        with marked_root() as (root, nested_file):
            self.assertEqual(repository_root(nested_file), root.resolve())

    def test_missing_repository_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.touch()
            with self.assertRaises(FileNotFoundError):
                repository_root(probe)

    def test_cwd_does_not_change_repository(self):
        expected = Path(__file__).resolve().parents[1]
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(repository_root(Path(__file__)), expected)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
