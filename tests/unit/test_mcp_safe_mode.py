"""Unit tests for MCP safe mode (UNIENV_MCP_MODE, UNIENV_MCP_ALLOW_INSTALL, UNIENV_MCP_ROOTS)."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv_mcp", ROOT / "src" / "unienv_mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class McpSafeModeTests(unittest.TestCase):
    def test_readonly_mode_exposes_only_safe_tools_and_blocks_code_execution(self):
        with patch.dict(os.environ, {"UNIENV_MCP_MODE": "readonly"}, clear=False):
            listed = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            names = {t["name"] for t in listed["result"]["tools"]}
            self.assertEqual(names, {"unienv_capabilities", "read_document", "convert_document"})

            for blocked, args in [
                ("run_python", {"code": "print(1)"}),
                ("run_tool", {"tool": "pandoc"}),
                ("install_package", {"name": "seaborn"}),
            ]:
                reply = mcp.handle(
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": blocked, "arguments": args}}
                )
                self.assertTrue(reply["result"]["isError"])
                self.assertIn("disabled by MCP safe mode", reply["result"]["content"][0]["text"])

    def test_allow_install_zero_hides_and_blocks_install_package(self):
        with patch.dict(os.environ, {"UNIENV_MCP_ALLOW_INSTALL": "0"}, clear=False):
            listed = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            names = {t["name"] for t in listed["result"]["tools"]}
            self.assertNotIn("install_package", names)
            self.assertIn("run_python", names)

            reply = mcp.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "install_package", "arguments": {"name": "seaborn"}},
                }
            )
            self.assertTrue(reply["result"]["isError"])
            self.assertIn("disabled by MCP safe mode", reply["result"]["content"][0]["text"])

    def test_mcp_roots_allows_inside_and_rejects_outside_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            allowed = base / "allowed"
            outside = base / "outside"
            allowed.mkdir()
            outside.mkdir()
            inside_file = allowed / "ok.txt"
            inside_file.write_text("hello")
            outside_file = outside / "secret.txt"
            outside_file.write_text("secret")
            escape_link = allowed / "escape.txt"
            escape_link.symlink_to(outside_file)

            with (
                patch.dict(os.environ, {"UNIENV_MCP_ROOTS": str(allowed)}, clear=False),
                patch.object(mcp, "WORKDIR", allowed),
            ):
                self.assertEqual(mcp.resolve(str(inside_file)), inside_file)
                self.assertEqual(mcp.workdir(None), allowed)

                with self.assertRaises(mcp.ToolError) as ctx_out:
                    mcp.resolve(str(outside_file))
                self.assertIn("outside allowed UNIENV_MCP_ROOTS", str(ctx_out.exception))

                with self.assertRaises(mcp.ToolError) as ctx_trav:
                    mcp.resolve(str(allowed / ".." / "outside" / "secret.txt"))
                self.assertIn("outside allowed UNIENV_MCP_ROOTS", str(ctx_trav.exception))

                with self.assertRaises(mcp.ToolError) as ctx_sym:
                    mcp.resolve(str(escape_link))
                self.assertIn("outside allowed UNIENV_MCP_ROOTS", str(ctx_sym.exception))

    def test_roots_hide_and_block_execution_and_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"UNIENV_MCP_ROOTS": tmp, "UNIENV_MCP_MODE": "full"}):
                names = {t["name"] for t in mcp.active_tools()}
                self.assertEqual(names, {"unienv_capabilities", "read_document", "convert_document"})
                for name in ("run_python", "run_tool", "install_package"):
                    with self.subTest(name=name), patch.object(mcp, "run") as run:
                        reply = mcp.handle(
                            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name}}
                        )
                        self.assertTrue(reply["result"]["isError"])
                        run.assert_not_called()

    def test_empty_root_entries_fail_closed(self):
        with patch.dict(os.environ, {"UNIENV_MCP_ROOTS": os.pathsep * 2}):
            with self.assertRaisesRegex(mcp.ToolError, "at least one directory"):
                mcp.resolve("secret.txt")

    def test_readonly_conversion_checks_output_before_creating_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source_dir = root / "source"
            source_dir.mkdir()
            src = source_dir / "notes.md"
            src.write_text("hello")
            work = root / "work"
            rejected = root / "outside"

            def fake_run(cmd, **kwargs):
                self.assertIn("--sandbox", cmd)
                Path(cmd[cmd.index("-o") + 1]).write_text("converted")
                return 0, "", "", 0.0

            with (
                patch.dict(os.environ, {"UNIENV_MCP_MODE": "readonly", "UNIENV_MCP_ROOTS": ""}),
                patch.object(mcp, "WORKDIR", work),
                patch.object(mcp, "run", side_effect=fake_run) as run,
            ):
                for output_dir in (None, str(source_dir), str(work)):
                    args = {"input_path": str(src), "output_format": "docx"}
                    if output_dir:
                        args["output_dir"] = output_dir
                    result = mcp.t_convert_document(args)
                    self.assertIn("Converted to ", result)
                run.reset_mock()
                with self.assertRaisesRegex(mcp.ToolError, "readonly conversions"):
                    mcp.t_convert_document(
                        {"input_path": str(src), "output_format": "docx", "output_dir": str(rejected)}
                    )
                self.assertFalse(rejected.exists())
                run.assert_not_called()
                alias = source_dir / "alias"
                alias.symlink_to(rejected, target_is_directory=True)
                with self.assertRaisesRegex(mcp.ToolError, "readonly conversions"):
                    mcp.t_convert_document(
                        {"input_path": str(src), "output_format": "docx", "output_dir": str(alias)}
                    )
                self.assertFalse(rejected.exists())

    def test_conversion_does_not_write_through_dangling_output_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            allowed = root / "allowed"
            allowed.mkdir()
            src = allowed / "notes.md"
            src.write_text("hello")
            outside = root / "outside"
            outside.mkdir()
            for name in ("notes.docx", "notes-1.docx"):
                (allowed / name).symlink_to(outside / name)

            def fake_run(cmd, **kwargs):
                self.assertIn("--sandbox", cmd)
                Path(cmd[cmd.index("-o") + 1]).write_text("converted")
                return 0, "", "", 0.0

            with (
                patch.dict(os.environ, {"UNIENV_MCP_ROOTS": str(allowed)}),
                patch.object(mcp, "run", side_effect=fake_run),
            ):
                result = mcp.t_convert_document({"input_path": str(src), "output_format": "docx"})
            self.assertEqual(result, f"Converted to {allowed / 'notes-2.docx'}")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue((allowed / "notes.docx").is_symlink())
            self.assertTrue((allowed / "notes-1.docx").is_symlink())

    def test_output_format_cannot_escape_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notes.md"
            src.write_text("hello")
            with patch.object(mcp, "run") as run:
                with self.assertRaisesRegex(mcp.ToolError, "output_format"):
                    mcp.t_convert_document({"input_path": str(src), "output_format": "/../../escape"})
                run.assert_not_called()

    def test_extension_settings_are_wired_to_server_policy(self):
        manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text())
        env = manifest["server"]["mcp_config"]["env"]
        for setting, variable in (
            ("mode", "UNIENV_MCP_MODE"),
            ("allow_install", "UNIENV_MCP_ALLOW_INSTALL"),
            ("roots", "UNIENV_MCP_ROOTS"),
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, manifest["user_config"])
                self.assertEqual(env[variable], "${user_config." + setting + "}")


if __name__ == "__main__":
    unittest.main()
