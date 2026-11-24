"""Unit tests for the Windsurf agent adapter (#5)."""

import argparse
import contextlib
import importlib.util
import io
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _isolation import isolated_home  # noqa: E402

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class WindsurfAdapterTests(unittest.TestCase):
    def _manifest(self):
        return {
            "batteries": ["core"],
            "bins": {"jq": "/usr/bin/jq"},
            "python": {"packages": {"pandas": "2.2.3"}},
            "node": {"packages": {}},
        }

    def test_windsurf_detected_by_dir_or_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.object(u, "HOME", home), patch.object(u, "which", return_value=None):
                target = next(a for a in u.agent_targets() if a["id"] == "windsurf")
                self.assertFalse(u.detected(target))
                (home / ".codeium/windsurf").mkdir(parents=True)
                self.assertTrue(u.detected(target))

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with (
                patch.object(u, "HOME", home),
                patch.object(
                    u, "which", side_effect=lambda name: "/usr/local/bin/windsurf" if name == "windsurf" else None
                ),
            ):
                target = next(a for a in u.agent_targets() if a["id"] == "windsurf")
                self.assertTrue(u.detected(target))

    def test_sync_agents_and_uninstall_preserve_existing_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unienv_home = home / ".unienv"
            unienv_home.mkdir()
            rules_path = home / ".codeium/windsurf/memories/global_rules.md"
            rules_path.parent.mkdir(parents=True)
            rules_path.write_text("# My Windsurf Rules\nAlways write tests.\n")
            manifest = self._manifest()

            with isolated_home(u, home, unienv_home=unienv_home, shell_files=[]):
                done = u.sync_agents(manifest, [])
                self.assertEqual(done, ["Windsurf"])
                self.assertEqual(
                    u.read_block(rules_path, u.MD_BEGIN, u.MD_END),
                    u.render_agent_block(manifest).rstrip(),
                )
                self.assertTrue(rules_path.read_text().startswith("# My Windsurf Rules\nAlways write tests.\n"))

                with (
                    patch.object(u, "SHELL_FILES", []),
                    patch.object(u, "LAUNCH_AGENT", home / "none.plist"),
                    patch.object(u, "mcp_clients", return_value={}),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    u.cmd_uninstall(argparse.Namespace(purge=False))

                self.assertIsNone(u.read_block(rules_path, u.MD_BEGIN, u.MD_END))
                self.assertEqual(rules_path.read_text(), "# My Windsurf Rules\nAlways write tests.\n")


if __name__ == "__main__":
    unittest.main()
