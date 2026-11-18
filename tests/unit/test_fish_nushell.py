"""Unit tests for fish and nushell support (#29)."""

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


class FishNushellTests(unittest.TestCase):
    def test_wire_and_uninstall_fish_and_nushell_when_config_dirs_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unienv_home = home / ".unienv"
            (home / ".config/fish").mkdir(parents=True)
            (home / ".config/nushell").mkdir(parents=True)
            (home / ".config/nushell/env.nu").write_text("# user nushell config\n")

            with (
                patch.object(u, "HOME", home),
                patch.object(u, "UNIENV_HOME", unienv_home),
                patch.object(u, "ENV_SH", unienv_home / "env.sh"),
                patch.object(u, "SHELL_FILES", [home / ".zshenv", home / ".profile", home / ".bashrc"]),
                patch.object(u, "IS_MAC", True),
                patch.object(u, "which", return_value=None),
            ):
                changed = u.wire_shells({"options": {"wire_homebrew": False}})
                self.assertIn("~/.config/fish/conf.d/unienv.fish", changed)
                self.assertIn("~/.config/nushell/env.nu", changed)
                self.assertIn("~/.config/nushell/autoload/unienv.nu", changed)

                fish_conf = home / ".config/fish/conf.d/unienv.fish"
                self.assertTrue(fish_conf.exists())
                fish_text = fish_conf.read_text()
                self.assertIn('fish_add_path -g "$UNIENV_HOME/bin"', fish_text)
                self.assertIn("/private", fish_text)

                nu_env = home / ".config/nushell/env.nu"
                nu_autoload = home / ".config/nushell/autoload/unienv.nu"
                self.assertIsNotNone(u.read_block(nu_env, u.SHELL_BEGIN, u.SHELL_END))
                self.assertIsNotNone(u.read_block(nu_autoload, u.SHELL_BEGIN, u.SHELL_END))

                # Re-running wire_shells is idempotent
                self.assertEqual(u.wire_shells({"options": {"wire_homebrew": False}}), [])

                # Uninstall removes unienv.fish, autoload/unienv.nu, and the block in env.nu
                with (
                    patch.object(u, "agent_targets", return_value=[]),
                    patch.object(u, "mcp_clients", return_value={}),
                    patch.object(u, "LAUNCH_AGENT", home / "none.plist"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    u.cmd_uninstall(argparse.Namespace(purge=False))

                self.assertFalse(fish_conf.exists())
                self.assertFalse(nu_autoload.exists())
                self.assertIsNone(u.read_block(nu_env, u.SHELL_BEGIN, u.SHELL_END))
                self.assertEqual(nu_env.read_text(), "# user nushell config\n")

    def test_doctor_probes_fish_when_installed(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            home = Path(tmp)
            fake_fish = home / "fake-fish"
            fake_fish.write_text("#!/bin/sh\nexit 0\n")
            fake_fish.chmod(0o755)
            manifest = home / "manifest.json"
            manifest.write_text("{}")

            for name, value in {
                "HOME": home,
                "UNIENV_HOME": home,
                "PY_DIR": home / "py",
                "MANIFEST_FILE": manifest,
                "IS_MAC": False,
            }.items():
                stack.enter_context(patch.object(u, name, value))
            for name, value in {
                "load_recipes": {},
                "load_state": {"options": {"exclude": []}},
                "active_recipes": [],
                "wanted": {"node": [], "bins": [], "skipped_bins": []},
                "node_packages": {},
                "agent_targets": [],
                "mcp_clients": {},
                "brew_prefix": None,
                "render_agent_block": "",
                "_clean_shell_probe": str(u.BIN / "ue-py"),
            }.items():
                stack.enter_context(patch.object(u, name, return_value=value))
            stack.enter_context(
                patch.object(u, "which", side_effect=lambda name: str(fake_fish) if name == "fish" else None)
            )

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                u.cmd_doctor(argparse.Namespace(json=True, fix=False, quiet_ok=False))

            checks = {c["id"]: c for c in json.loads(out.getvalue())["checks"]}
            self.assertIn("shell:fish -c", checks)
            self.assertEqual(checks["shell:fish -c"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
