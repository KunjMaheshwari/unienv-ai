import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP_PATH = ROOT / "src" / "unienv_mcp.py"
spec = importlib.util.spec_from_file_location("unienv_mcp", MCP_PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class WorkdirResolutionTests(unittest.TestCase):
    def test_unset_env_defaults_to_home_unienv(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with patch.dict(os.environ, {"HOME": str(home)}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), (home / "UniEnv").resolve())

    def test_empty_string_defaults_to_home_unienv(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with patch.dict(os.environ, {"HOME": str(home), "UNIENV_WORKDIR": ""}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), (home / "UniEnv").resolve())

    def test_whitespace_only_defaults_to_home_unienv(self):
        """Whitespace-only UNIENV_WORKDIR is treated as empty and falls back to HOME/UniEnv."""
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with patch.dict(os.environ, {"HOME": str(home), "UNIENV_WORKDIR": "   \t\n "}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), (home / "UniEnv").resolve())

    def test_absolute_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / "home"
            target = pathlib.Path(tmp) / "custom_abs" / "work"
            with patch.dict(os.environ, {"HOME": str(home), "UNIENV_WORKDIR": str(target)}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), target.resolve())

    def test_relative_path_resolves_against_home_not_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / "home"
            home.mkdir()
            with patch.dict(os.environ, {"HOME": str(home), "UNIENV_WORKDIR": "projects/scratch"}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), (home / "projects" / "scratch").resolve())

    def test_tilde_expansion_uses_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with patch.dict(os.environ, {"HOME": str(home), "UNIENV_WORKDIR": "~/my-work"}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), (home / "my-work").resolve())
            with patch.dict(os.environ, {"HOME": str(home), "UNIENV_WORKDIR": "~"}, clear=True):
                self.assertEqual(mcp.resolve_workdir(home=home), home.resolve())

    def test_workdir_helper_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp) / "work"
            with patch.object(mcp, "WORKDIR", base):
                created = mcp.workdir(None)
                self.assertEqual(created, base)
                self.assertTrue(created.is_dir())

    def test_mcp_launch_from_root_cwd_with_empty_or_relative_workdir(self):
        for raw_value, expected_subpath in [
            ("", "UniEnv"),
            ("relative-out", "relative-out"),
        ]:
            with self.subTest(UNIENV_WORKDIR=raw_value):
                with tempfile.TemporaryDirectory() as tmp:
                    home = pathlib.Path(tmp)
                    env = {
                        "HOME": str(home),
                        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                        "UNIENV_HOME": str(home / ".unienv"),
                        "UNIENV_WORKDIR": raw_value,
                    }
                    init_msg = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    }
                    proc = subprocess.run(
                        [sys.executable, str(MCP_PATH)],
                        input=json.dumps(init_msg) + "\n",
                        cwd="/",
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    expected_dir = (home / expected_subpath).resolve()
                    self.assertFalse(expected_dir.exists())
                    self.assertIn(f"working folder {expected_dir}", proc.stderr)
                    reply = json.loads(proc.stdout.strip())
                    self.assertIn(str(expected_dir), reply["result"]["instructions"])

    def test_mcp_starts_when_workdir_parent_is_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            blocker = home / "blocker"
            blocker.write_text("not a directory\n")
            uncreatable = blocker / "child"
            env = {
                "HOME": str(home),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "UNIENV_HOME": str(home / ".unienv"),
                "UNIENV_WORKDIR": str(uncreatable),
            }
            msgs = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
            proc = subprocess.run(
                [sys.executable, str(MCP_PATH)],
                input="\n".join(map(json.dumps, msgs)) + "\n",
                cwd="/",
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = {m["id"]: m for m in map(json.loads, proc.stdout.splitlines())}
            self.assertEqual(replies[2]["result"], {})
            self.assertIn(str(uncreatable.resolve()), replies[1]["result"]["instructions"])


if __name__ == "__main__":
    unittest.main()
