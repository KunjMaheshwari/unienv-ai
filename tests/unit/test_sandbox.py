"""Sandbox settings merge and ownership tests."""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import tomllib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _isolation import isolated_home  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class SandboxProfileTests(unittest.TestCase):
    def test_profiles_only_grant_the_unienv_directory(self):
        claude = json.loads(u.sandbox_profile("claude"))
        self.assertFalse(any(rule.startswith("Bash(") for rule in claude["permissions"]["allow"]))
        self.assertEqual(claude["sandbox"]["filesystem"]["allowWrite"], [str(u.UNIENV_HOME)])
        codex = tomllib.loads(u.sandbox_profile("codex"))
        self.assertNotIn("sandbox_mode", codex)
        self.assertNotIn("readable_roots", codex["sandbox_workspace_write"])
        self.assertEqual(codex["sandbox_workspace_write"]["writable_roots"], [str(u.UNIENV_HOME)])

    def test_codex_merge_preserves_tables_mode_and_existing_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            config = root / "config.toml"
            original = {
                "sandbox_mode": "read-only",
                "model": "test-model",
                "sandbox_workspace_write": {"network_access": False, "writable_roots": ["/existing"]},
                "profiles": {"work": {"model": "other", "approval_policy": "on-request"}},
            }
            config.write_text(u._toml_text(original))
            with patch.object(u, "UNIENV_HOME", root / "unienv"):
                self.assertTrue(u._install_codex_sandbox(config))
                self.assertFalse(u._install_codex_sandbox(config))
                current = tomllib.loads(config.read_text())
                self.assertEqual(current["sandbox_mode"], "read-only")
                self.assertEqual(current["profiles"], original["profiles"])
                self.assertEqual(
                    current["sandbox_workspace_write"]["writable_roots"], ["/existing", str(u.UNIENV_HOME)]
                )
                current["model"] = "user-changed-after-install"
                config.write_text(u._toml_text(current))
                u._uninstall_sandbox()
            restored = tomllib.loads(config.read_text())
            self.assertEqual(restored["sandbox_workspace_write"], original["sandbox_workspace_write"])
            self.assertEqual(restored["model"], "user-changed-after-install")
            self.assertEqual(restored["profiles"], original["profiles"])
            self.assertTrue(list(root.glob("config.toml.unienv-backup-*")))

    def test_claude_preserves_existing_rules_and_removes_only_owned_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "settings.json"
            cfg.write_text(json.dumps({"permissions": {"allow": ["Bash(git status)"]}, "theme": "dark"}))
            with patch.object(u, "UNIENV_HOME", root / "unienv"):
                self.assertTrue(u._install_claude_sandbox(cfg))
                self.assertFalse(u._install_claude_sandbox(cfg))
                current = json.loads(cfg.read_text())
                current["permissions"]["allow"].append("Read(/user-added)")
                cfg.write_text(json.dumps(current))
                u._uninstall_sandbox()
            restored = json.loads(cfg.read_text())
            self.assertEqual(
                restored, {"permissions": {"allow": ["Bash(git status)", "Read(/user-added)"]}, "theme": "dark"}
            )

    def test_preexisting_unienv_root_is_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "config.toml"
            with patch.object(u, "UNIENV_HOME", root / "unienv"):
                cfg.write_text(u.sandbox_profile("codex"))
                self.assertFalse(u._install_codex_sandbox(cfg))
                u._uninstall_sandbox()
                self.assertEqual(
                    tomllib.loads(cfg.read_text())["sandbox_workspace_write"]["writable_roots"], [str(u.UNIENV_HOME)]
                )

    def test_uninstall_command_removes_new_config_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with (
                isolated_home(
                    u,
                    home,
                    unienv_home=home / "unienv",
                    shell_files=[],
                    extra_env={"CODEX_HOME": str(home / "codex")},
                ),
                patch.object(u, "agent_targets", return_value=[]),
                patch.object(u, "mcp_clients", return_value={}),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(u.cmd_sandbox(argparse.Namespace(action="install", tool="all")), 0)
                self.assertEqual(u.cmd_uninstall(argparse.Namespace(purge=False)), 0)
                self.assertFalse((home / "codex/config.toml").exists())
                self.assertFalse((home / ".claude/settings.json").exists())

    def test_invalid_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / "config.toml"
            cfg.write_text("[broken")
            with patch.object(u, "UNIENV_HOME", root / "unienv"), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    u._install_codex_sandbox(cfg)
            self.assertEqual(cfg.read_text(), "[broken")

    def test_seatbelt_profile_includes_write_access_to_unienv(self):
        text = u.sandbox_profile("seatbelt")
        self.assertIn("file-write*", text)
        self.assertIn(json.dumps(str(u.UNIENV_HOME)), text)

    def test_codex_surgical_toml_edit_preserves_comments_tables_arrays_and_emojis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            config = root / "config.toml"
            handwritten = (
                "# Top-level comment with emoji 😀\n"
                'model = "o3-mini"\n'
                'greeting = "hello 😀"\n\n'
                "[mcp_servers.unienv]\n"
                'command = "/Users/me/.unienv/bin/unienv"\n'
                'args = ["mcp"]\n\n'
                "[[notify]]\n"
                'command = "say"\n\n'
                "[sandbox_workspace_write]\n"
                "# Keep network off\n"
                "network_access = false\n"
                'writable_roots = ["/tmp/work"]\n'
            )
            config.write_text(handwritten, encoding="utf-8")
            with patch.object(u, "UNIENV_HOME", root / "unienv"):
                self.assertTrue(u._install_codex_sandbox(config))
                updated_text = config.read_text(encoding="utf-8")
                self.assertIn("# Top-level comment with emoji 😀", updated_text)
                self.assertIn("[mcp_servers.unienv]", updated_text)
                self.assertIn("[[notify]]", updated_text)
                self.assertIn("# Keep network off", updated_text)
                self.assertEqual(
                    tomllib.loads(updated_text)["sandbox_workspace_write"]["writable_roots"],
                    ["/tmp/work", str(root / "unienv")],
                )
                u._uninstall_sandbox()
                restored_text = config.read_text(encoding="utf-8")
                self.assertIn("[mcp_servers.unienv]", restored_text)
                self.assertIn("[[notify]]", restored_text)
                self.assertEqual(tomllib.loads(restored_text), tomllib.loads(handwritten))

    def test_symlink_and_permissions_preserved_and_corrupt_state_does_not_abort_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            real_cfg = root / "dotfiles_config.toml"
            real_cfg.write_text('model = "gpt-5"\n', encoding="utf-8")
            real_cfg.chmod(0o600)
            link_cfg = root / "config.toml"
            link_cfg.symlink_to(real_cfg)

            with patch.object(u, "UNIENV_HOME", root / "unienv"):
                self.assertTrue(u._install_codex_sandbox(link_cfg))
                self.assertTrue(link_cfg.is_symlink())
                self.assertEqual(real_cfg.stat().st_mode & 0o777, 0o600)
                self.assertIn("[sandbox_workspace_write]", real_cfg.read_text(encoding="utf-8"))

                # Corrupt sandbox-settings.json: cmd_uninstall must warn and still finish
                (root / "unienv/sandbox-settings.json").write_text("{corrupt", encoding="utf-8")
                with (
                    isolated_home(u, root, unienv_home=root / "unienv", shell_files=[]),
                    patch.object(u, "agent_targets", return_value=[]),
                    patch.object(u, "mcp_clients", return_value={}),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()) as err,
                ):
                    rc = u.cmd_uninstall(argparse.Namespace(purge=False))
                self.assertEqual(rc, 0)
                self.assertIn("could not read sandbox state", err.getvalue())

    def test_dotted_key_codex_config_is_refused_and_left_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / ".codex/config.toml"
            cfg.parent.mkdir(parents=True)
            original = b'sandbox_workspace_write.writable_roots = ["/tmp/work"]\n'
            cfg.write_bytes(original)
            with (
                patch.object(u, "HOME", root),
                patch.object(u, "UNIENV_HOME", root / ".unienv"),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as cm:
                    u._install_codex_sandbox(cfg)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(cfg.read_bytes(), original)

    def test_codex_crlf_line_endings_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = root / ".codex/config.toml"
            cfg.parent.mkdir(parents=True)
            cfg.write_bytes(b'model = "o3"\r\n[sandbox_workspace_write]\r\nwritable_roots = ["/tmp/a"]\r\n')
            with (
                patch.object(u, "HOME", root),
                patch.object(u, "UNIENV_HOME", root / ".unienv"),
            ):
                self.assertTrue(u._install_codex_sandbox(cfg))
            self.assertIn(b"\r\n", cfg.read_bytes())

    def test_sandbox_install_all_skips_undetected_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            out = io.StringIO()
            with (
                patch.object(u, "HOME", root),
                patch.object(u, "UNIENV_HOME", root / ".unienv"),
                patch.object(u, "which", return_value=None),
                patch.dict(os.environ, {"CODEX_HOME": str(root / ".codex")}),
                contextlib.redirect_stdout(out),
            ):
                rc = u.cmd_sandbox(argparse.Namespace(action="install", tool="all"))
            self.assertEqual(rc, 0)
            self.assertFalse((root / ".claude").exists())
            self.assertFalse((root / ".codex").exists())
            self.assertIn("skipped (not detected)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
