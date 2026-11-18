import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class McpClientsTests(unittest.TestCase):
    def test_mcp_clients_paths_and_keys_on_mac_and_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            with patch.object(u, "HOME", home), patch.object(u, "IS_MAC", True):
                mac_clients = u.mcp_clients()
            self.assertEqual(
                set(mac_clients),
                {"claude-desktop", "cursor", "windsurf", "lm-studio", "vscode", "zed", "claude-code"},
            )
            self.assertEqual(
                mac_clients["vscode"],
                home / "Library/Application Support/Code/User/mcp.json",
            )
            self.assertEqual(mac_clients["windsurf"], home / ".codeium/windsurf/mcp_config.json")
            self.assertEqual(mac_clients["lm-studio"], home / ".lmstudio/mcp.json")
            self.assertEqual(mac_clients["zed"], home / ".config/zed/settings.json")
            self.assertEqual(mac_clients["claude-code"], home / ".claude.json")

            with patch.object(u, "HOME", home), patch.object(u, "IS_MAC", False):
                linux_clients = u.mcp_clients()
            self.assertEqual(linux_clients["vscode"], home / ".config/Code/User/mcp.json")
            self.assertEqual(
                linux_clients["claude-desktop"],
                home / ".config/Claude/claude_desktop_config.json",
            )

    def test_install_doctor_and_uninstall_preserve_existing_servers_and_backups(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            home = pathlib.Path(tmp)
            manifest = home / "manifest.json"
            manifest.write_text("{}")
            for name, value in {
                "HOME": home,
                "UNIENV_HOME": home,
                "BIN": home / "bin",
                "LOG_FILE": home / "log" / "unienv.log",
                "PY_DIR": home / "py",
                "MANIFEST_FILE": manifest,
                "IS_MAC": False,
            }.items():
                stack.enter_context(patch.object(u, name, value))

            clients = u.mcp_clients()
            for client_name, cfg_path in clients.items():
                key = u.mcp_client_key(client_name)
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(json.dumps({key: {"existing": {"command": "other"}}, "extra": True}))

                with contextlib.redirect_stdout(io.StringIO()):
                    rc = u.cmd_mcp(argparse.Namespace(action="install", client=client_name))
                self.assertEqual(rc, 0)

                data = json.loads(cfg_path.read_text())
                self.assertEqual(data["extra"], True)
                self.assertEqual(data[key]["existing"], {"command": "other"})
                self.assertEqual(data[key]["unienv"], u.mcp_entry())
                backups = list(cfg_path.parent.glob(cfg_path.name + ".unienv-backup-*"))
                self.assertTrue(backups, f"expected backup for {client_name}")

            # Verify doctor detects all configured clients across root keys
            for name, value in {
                "load_recipes": {},
                "load_state": {"options": {"exclude": []}},
                "active_recipes": [],
                "wanted": {"node": [], "bins": [], "skipped_bins": []},
                "node_packages": {},
                "agent_targets": [],
                "brew_prefix": None,
                "render_agent_block": "",
                "_clean_shell_probe": str(u.BIN / "ue-py"),
                "mcp_handshake": (True, "6 tools", 0.1),
            }.items():
                stack.enter_context(patch.object(u, name, return_value=value))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                u.cmd_doctor(argparse.Namespace(json=True, fix=False, quiet_ok=False))
            report = json.loads(stdout.getvalue())
            mcp_check = next(c for c in report["checks"] if c["id"] == "mcp")
            self.assertEqual(mcp_check["status"], "ok")
            for client_name in clients:
                self.assertIn(client_name, mcp_check["message"])

            # Verify uninstall removes only unienv and preserves existing entries
            with contextlib.redirect_stdout(io.StringIO()):
                u.cmd_mcp(argparse.Namespace(action="uninstall", client="all"))
            for client_name, cfg_path in clients.items():
                key = u.mcp_client_key(client_name)
                data = json.loads(cfg_path.read_text())
                self.assertEqual(data, {key: {"existing": {"command": "other"}}, "extra": True})


if __name__ == "__main__":
    unittest.main()
