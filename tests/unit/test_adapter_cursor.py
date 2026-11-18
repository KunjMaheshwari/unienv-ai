"""Unit tests for the Cursor agent adapter (#4)."""

import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class CursorAdapterTests(unittest.TestCase):
    def _manifest(self):
        return {
            "batteries": ["core"],
            "bins": {"jq": "/usr/bin/jq"},
            "python": {"packages": {"pandas": "2.2.3"}},
            "node": {"packages": {}},
        }

    def test_cursor_detected_by_dir_or_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.object(u, "HOME", home), patch.object(u, "which", return_value=None):
                target = next(a for a in u.agent_targets() if a["id"] == "cursor")
                self.assertFalse(u.detected(target))
                (home / ".cursor").mkdir()
                self.assertTrue(u.detected(target))

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with (
                patch.object(u, "HOME", home),
                patch.object(
                    u, "which", side_effect=lambda name: "/usr/local/bin/cursor" if name == "cursor" else None
                ),
            ):
                target = next(a for a in u.agent_targets() if a["id"] == "cursor")
                self.assertTrue(u.detected(target))

    def test_sync_writes_mdc_with_frontmatter_and_uninstall_removes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unienv_home = home / ".unienv"
            unienv_home.mkdir()
            (home / ".cursor").mkdir()
            manifest = self._manifest()

            with (
                patch.object(u, "HOME", home),
                patch.object(u, "UNIENV_HOME", unienv_home),
                patch.object(u, "AGENTS_COPY", unienv_home / "AGENTS.md"),
                patch.object(u, "which", return_value=None),
            ):
                done = u.sync_agents(manifest, [])
                self.assertEqual(done, ["Cursor"])
                mdc = home / ".cursor/rules/unienv.mdc"
                self.assertTrue(mdc.exists())
                text = mdc.read_text()
                self.assertTrue(text.startswith("---\n"))
                self.assertIn("alwaysApply: true", text)
                self.assertEqual(u.read_block(mdc, u.MD_BEGIN, u.MD_END), u.render_agent_block(manifest).rstrip())

                # Re-syncing is idempotent and does not duplicate frontmatter
                u.sync_agents(manifest, [])
                self.assertEqual(mdc.read_text(), text)

                # Uninstall removes the block and cleans up the frontmatter-only file
                with (
                    patch.object(u, "SHELL_FILES", []),
                    patch.object(u, "LAUNCH_AGENT", home / "none.plist"),
                    patch.object(u, "mcp_clients", return_value={}),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    u.cmd_uninstall(argparse.Namespace(purge=False))
                self.assertFalse(mdc.exists())

    def test_doctor_reports_cursor_agent_status(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            home = Path(tmp)
            (home / ".cursor").mkdir()
            manifest_path = home / "manifest.json"
            manifest = self._manifest()
            manifest_path.write_text(json.dumps(manifest))

            for name, value in {
                "HOME": home,
                "UNIENV_HOME": home,
                "PY_DIR": home / "py",
                "MANIFEST_FILE": manifest_path,
                "AGENTS_COPY": home / "AGENTS.md",
                "IS_MAC": False,
            }.items():
                stack.enter_context(patch.object(u, name, value))
            for name, value in {
                "load_recipes": {},
                "load_state": {"options": {"exclude": []}},
                "active_recipes": [],
                "wanted": {"node": [], "bins": [], "skipped_bins": []},
                "node_packages": {},
                "mcp_clients": {},
                "brew_prefix": None,
                "_clean_shell_probe": str(u.BIN / "ue-py"),
                "which": None,
            }.items():
                stack.enter_context(patch.object(u, name, return_value=value))

            # Before sync: fail
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                u.cmd_doctor(argparse.Namespace(json=True, fix=False, quiet_ok=False))
            checks = {c["id"]: c for c in json.loads(out.getvalue())["checks"]}
            self.assertEqual(checks["agent:cursor"]["status"], "fail")

            # After sync: ok
            u.sync_agents(manifest, [])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                u.cmd_doctor(argparse.Namespace(json=True, fix=False, quiet_ok=False))
            checks = {c["id"]: c for c in json.loads(out.getvalue())["checks"]}
            self.assertEqual(checks["agent:cursor"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
