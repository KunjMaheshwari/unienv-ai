"""Unit tests for MCP safe mode (UNIENV_MCP_MODE, UNIENV_MCP_ALLOW_INSTALL, UNIENV_MCP_ROOTS)."""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
