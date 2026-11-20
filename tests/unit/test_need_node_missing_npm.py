#!/usr/bin/env python3
"""Unit tests for Issue #59: `unienv need --node` fails and rolls back when npm is missing."""

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
import unienv  # noqa: E402


class NeedNodeMissingNpmTest(unittest.TestCase):
    def test_install_node_default_warns_without_raising_when_npm_missing(self):
        err = io.StringIO()
        with (
            mock.patch.object(unienv, "which", return_value=None),
            contextlib.redirect_stderr(err),
        ):
            unienv.install_node(["left-pad"])
        self.assertIn("npm not found; skipping Node batteries", err.getvalue())

    def test_install_node_require_npm_raises_runtime_error(self):
        with (
            mock.patch.object(unienv, "which", return_value=None),
            self.assertRaises(RuntimeError) as ctx,
        ):
            unienv.install_node(["left-pad"], require_npm=True)
        self.assertEqual(str(ctx.exception), "npm not found: install Node.js (`unienv need --bin node`)")

    def test_cmd_need_node_fails_and_rolls_back_when_npm_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state_file = home / "state.json"
            initial_state = {
                "version": unienv.VERSION,
                "batteries": ["data"],
                "extras": {"python": [], "node": [], "brew": [], "cask": [], "apt": []},
                "options": {"wire_homebrew": True, "exclude": []},
            }
            state_file.write_text(json.dumps(initial_state, indent=2) + "\n")
            before_bytes = state_file.read_bytes()

            args = argparse.Namespace(
                packages=["left-pad"],
                node=True,
                bin=False,
                cask=False,
                yes=False,
            )
            out = io.StringIO()
            err = io.StringIO()
            with (
                mock.patch.object(unienv, "UNIENV_HOME", home),
                mock.patch.object(unienv, "STATE_FILE", state_file),
                mock.patch.object(unienv, "BACKUP_DIR", home / "backups"),
                mock.patch.object(unienv, "LOG_FILE", home / "log" / "unienv.log"),
                mock.patch.object(unienv, "PY_DIR", home / "py"),
                mock.patch.object(unienv, "NODE_DIR", home / "node"),
                mock.patch.object(unienv, "which", return_value=None),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                rc = unienv.cmd_need(args)

            self.assertEqual(rc, 1)
            self.assertEqual(state_file.read_bytes(), before_bytes)
            self.assertNotIn("✓ installed", out.getvalue())
            self.assertIn("npm not found: install Node.js (`unienv need --bin node`)", err.getvalue())
            self.assertIn("rolling back", err.getvalue())


if __name__ == "__main__":
    unittest.main()
