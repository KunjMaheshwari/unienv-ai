"""Unit tests for write_pyproject() TOML generation and escaping."""

import importlib.util
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class WritePyprojectTests(unittest.TestCase):
    def test_round_trips_markers_quotes_and_backslashes(self):
        pkgs = [
            "pandas>=2.0",
            'pywin32; sys_platform == "win32"',
            r"local-pkg @ file:///C:\tmp\wheel.whl",
            'weird"pkg\\name',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            py_dir = Path(tmp) / "py"
            with patch.object(u, "PY_DIR", py_dir):
                u.write_pyproject(pkgs)
            parsed = tomllib.loads((py_dir / "pyproject.toml").read_text())
        self.assertEqual(parsed["project"]["dependencies"], pkgs)


if __name__ == "__main__":
    unittest.main()
