"""Unit tests for diagrams battery Puppeteer cache propagation (#2)."""

import argparse
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]

spec_u = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec_u)
spec_u.loader.exec_module(u)

spec_m = importlib.util.spec_from_file_location("unienv_mcp", ROOT / "src" / "unienv_mcp.py")
m = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(m)


class DiagramsPuppeteerTests(unittest.TestCase):
    def test_env_sh_exports_puppeteer_cache_for_battery_extra_or_existing_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ue_home = root / ".unienv"
            ue_home.mkdir()
            env_sh = ue_home / "env.sh"
            with (
                patch.object(u, "UNIENV_HOME", ue_home),
                patch.object(u, "ENV_SH", env_sh),
                patch.object(u, "brew_prefix", return_value=None),
            ):
                u.write_env_sh({"batteries": ["office"], "extras": {"node": []}, "options": {}})
                self.assertNotIn("PUPPETEER_CACHE_DIR", env_sh.read_text())

                u.write_env_sh({"batteries": ["diagrams"], "extras": {"node": []}, "options": {}})
                self.assertIn("PUPPETEER_CACHE_DIR", env_sh.read_text())

                u.write_env_sh(
                    {"batteries": ["office"], "extras": {"node": ["@mermaid-js/mermaid-cli"]}, "options": {}}
                )
                self.assertIn("PUPPETEER_CACHE_DIR", env_sh.read_text())

                (ue_home / "cache" / "puppeteer").mkdir(parents=True)
                u.write_env_sh({"batteries": ["office"], "extras": {"node": []}, "options": {}})
                self.assertIn("PUPPETEER_CACHE_DIR", env_sh.read_text())

    def test_mcp_tool_env_propagates_puppeteer_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ue_home = Path(tmp) / ".unienv"
            cache_dir = ue_home / "cache" / "puppeteer"
            with (
                patch.object(m, "UNIENV_HOME", ue_home),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertNotIn("PUPPETEER_CACHE_DIR", m.tool_env())
                cache_dir.mkdir(parents=True)
                self.assertEqual(m.tool_env().get("PUPPETEER_CACHE_DIR"), str(cache_dir))

            with (
                patch.object(m, "UNIENV_HOME", ue_home),
                patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": "/custom/puppeteer"}, clear=True),
            ):
                self.assertEqual(m.tool_env().get("PUPPETEER_CACHE_DIR"), "/custom/puppeteer")

    def test_cmd_upgrade_passes_puppeteer_cache_env_to_npm_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ue_home = root / ".unienv"
            node_dir = ue_home / "node"
            node_dir.mkdir(parents=True)
            (node_dir / "package.json").write_text('{"dependencies": {"@mermaid-js/mermaid-cli": "latest"}}\n')
            captured = []

            def fake_run(cmd, **kw):
                captured.append((cmd, kw.get("env")))

            with (
                patch.object(u, "UNIENV_HOME", ue_home),
                patch.object(u, "STATE_FILE", ue_home / "state.json"),
                patch.object(u, "BACKUP_DIR", ue_home / "backups"),
                patch.object(u, "PY_DIR", ue_home / "py"),
                patch.object(u, "NODE_DIR", node_dir),
                patch.object(u, "LOG_FILE", ue_home / "log" / "events.jsonl"),
                patch.object(u, "which", side_effect=lambda b: "/usr/bin/npm" if b == "npm" else None),
                patch.object(u, "run", side_effect=fake_run),
                patch.object(u, "do_sync", return_value={}),
                patch.dict(os.environ, {}, clear=False),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                os.environ.pop("PUPPETEER_CACHE_DIR", None)
                state = u.default_state(u.load_recipes())
                state["extras"]["node"] = ["@mermaid-js/mermaid-cli"]
                u.save_state(state)
                rc = u.cmd_upgrade(argparse.Namespace(packages=[], node=True, dry_run=False))
            self.assertEqual(rc, 0)
            self.assertTrue(captured)
            self.assertEqual(captured[0][1], {"PUPPETEER_CACHE_DIR": str(ue_home / "cache" / "puppeteer")})


if __name__ == "__main__":
    unittest.main()
