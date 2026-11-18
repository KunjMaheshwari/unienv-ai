"""Unit tests for #37 (`unienv sandbox print` and `unienv sandbox install`)."""

import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class SandboxProfileTests(unittest.TestCase):
    def test_sandbox_print_claude(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = u.cmd_sandbox(argparse.Namespace(action="print", tool="claude"))
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertIn("permissions", data)
        self.assertIn("allow", data["permissions"])
        self.assertTrue(any("ue-py" in r for r in data["permissions"]["allow"]))
        self.assertIn(str(u.UNIENV_HOME), data["sandbox"]["readableRoots"])
        self.assertIn("/private/tmp", data["sandbox"]["writableRoots"])

    def test_sandbox_print_codex_is_valid_toml(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = u.cmd_sandbox(argparse.Namespace(action="print", tool="codex"))
        self.assertEqual(rc, 0)
        parsed = tomllib.loads(out.getvalue())
        self.assertEqual(parsed["sandbox_mode"], "workspace-write")
        self.assertIn("/private/tmp", parsed["sandbox_workspace_write"]["writable_roots"])
        self.assertIn(str(u.UNIENV_HOME), parsed["sandbox_workspace_write"]["readable_roots"])

    def test_sandbox_print_seatbelt_and_gemini(self):
        for tool in ("gemini", "seatbelt"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = u.cmd_sandbox(argparse.Namespace(action="print", tool=tool))
            self.assertEqual(rc, 0)
            text = out.getvalue()
            self.assertIn("(allow file-read* file-map-executable", text)
            self.assertIn(f'(subpath "{u.UNIENV_HOME}")', text)
            self.assertIn('(subpath "/private/tmp")', text)

    def test_sandbox_install_claude_merges_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            claude_dir = home / ".claude"
            claude_dir.mkdir(parents=True)
            settings = claude_dir / "settings.json"
            settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git *)"]}, "theme": "dark"}))
            with (
                patch.object(u, "HOME", home),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc = u.cmd_sandbox(argparse.Namespace(action="install", tool="claude"))
                self.assertEqual(rc, 0)
                # Second run is a no-op
                rc2 = u.cmd_sandbox(argparse.Namespace(action="install", tool="claude"))
                self.assertEqual(rc2, 0)
            merged = json.loads(settings.read_text())
            self.assertEqual(merged["theme"], "dark")
            self.assertIn("Bash(git *)", merged["permissions"]["allow"])
            self.assertTrue(any("ue-py" in r for r in merged["permissions"]["allow"]))
            self.assertTrue(list(claude_dir.glob("settings.json.unienv-backup-*")))

    def test_sandbox_install_codex_merges_block_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            codex_dir = home / ".codex"
            codex_dir.mkdir(parents=True)
            cfg = codex_dir / "config.toml"
            cfg.write_text('model = "gpt-5"\n')
            with (
                patch.object(u, "HOME", home),
                patch.dict(u.os.environ, {"CODEX_HOME": str(codex_dir)}, clear=False),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc = u.cmd_sandbox(argparse.Namespace(action="install", tool="codex"))
            self.assertEqual(rc, 0)
            text = cfg.read_text()
            self.assertIn('model = "gpt-5"', text)
            self.assertIn("sandbox_workspace_write", text)
            self.assertTrue(list(codex_dir.glob("config.toml.unienv-backup-*")))


if __name__ == "__main__":
    unittest.main()
