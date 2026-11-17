"""Unit tests for malformed JSON-RPC requests in unienv_mcp."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
MCP_PATH = ROOT / "src" / "unienv_mcp.py"
spec = importlib.util.spec_from_file_location("unienv_mcp", MCP_PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class MalformedRequestTests(unittest.TestCase):
    def test_non_dict_params_returns_invalid_params(self):
        for bad_params in ("abc", 123, ["x"]):
            with self.subTest(params=bad_params):
                reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": bad_params})
                self.assertEqual(reply["error"]["code"], -32602)

    def test_non_str_tool_name_returns_invalid_params(self):
        for bad_name in (["x"], 42, None, {"a": 1}):
            with self.subTest(name=bad_name):
                reply = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": bad_name}})
                self.assertEqual(reply["error"]["code"], -32602)

    def test_non_dict_arguments_returns_invalid_params(self):
        for bad_args in (5, "abc", ["a"]):
            with self.subTest(arguments=bad_args):
                reply = mcp.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "read_document", "arguments": bad_args},
                    }
                )
                self.assertEqual(reply["error"]["code"], -32602)

    def test_safe_handle_catches_unexpected_errors(self):
        with patch.object(mcp, "handle", side_effect=RuntimeError("boom")):
            reply = mcp._safe_handle({"jsonrpc": "2.0", "id": 4, "method": "ping"})
        self.assertEqual(reply["error"]["code"], -32603)
        self.assertEqual(reply["id"], 4)

    def test_stdio_server_survives_malformed_and_lone_surrogate_requests(self):
        msgs = [
            '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":"abc"}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":["x"]}}',
            '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_document","arguments":5}}',
            '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"read_document","arguments":{"path":"\\ud800"}}}',
            '{"jsonrpc":"2.0","id":5,"method":"ping"}',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(MCP_PATH)],
                input="\n".join(msgs) + "\n",
                capture_output=True,
                text=True,
                env={"HOME": tmp, "PATH": "/usr/bin:/bin", "UNIENV_HOME": f"{tmp}/.unienv"},
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        replies = {m["id"]: m for m in map(json.loads, proc.stdout.splitlines())}
        self.assertEqual(replies[1]["error"]["code"], -32602)
        self.assertEqual(replies[2]["error"]["code"], -32602)
        self.assertEqual(replies[3]["error"]["code"], -32602)
        self.assertTrue(replies[4]["result"]["isError"])
        self.assertEqual(replies[5]["result"], {})

    def test_stdio_server_handles_top_level_non_objects_and_invalid_batches(self):
        msgs = [
            "42",
            '"hello"',
            "null",
            "[]",
            '[1, {"jsonrpc":"2.0","id":10,"method":"ping"}]',
            '[1, "bad", null]',
            '[{"jsonrpc":"2.0","method":"notifications/initialized"},{"jsonrpc":"2.0","id":11,"method":"ping"}]',
            '[{"jsonrpc":"2.0","id":12,"method":123}]',
            '{"jsonrpc":"2.0","id":13,"method":"ping"}',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(MCP_PATH)],
                input="\n".join(msgs) + "\n",
                capture_output=True,
                text=True,
                env={"HOME": tmp, "PATH": "/usr/bin:/bin", "UNIENV_HOME": f"{tmp}/.unienv"},
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(lines), 9)
        for idx in (0, 1, 2, 3):
            self.assertIsNone(lines[idx]["id"])
            self.assertEqual(lines[idx]["error"]["code"], -32600)

        # Batch with invalid scalar + valid ping
        self.assertEqual(
            lines[4],
            [
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
                {"jsonrpc": "2.0", "id": 10, "result": {}},
            ],
        )
        # Batch with multiple invalid entries
        self.assertEqual(len(lines[5]), 3)
        self.assertTrue(all(item["error"]["code"] == -32600 and item["id"] is None for item in lines[5]))
        # Batch with valid notification + valid request (notification produces no reply)
        self.assertEqual(lines[6], [{"jsonrpc": "2.0", "id": 11, "result": {}}])
        # Malformed method type in request object
        self.assertEqual(
            lines[7], [{"jsonrpc": "2.0", "id": 12, "error": {"code": -32600, "message": "Invalid Request"}}]
        )
        # Server still alive
        self.assertEqual(lines[8], {"jsonrpc": "2.0", "id": 13, "result": {}})

    def test_jsonrpc_version_and_id_semantics(self):
        msgs = [
            '{"jsonrpc":"2.0","id":1,"method":"ping"}',
            '{"jsonrpc":"2.0","id":"req-2","method":"ping"}',
            '{"jsonrpc":"2.0","id":null,"method":"ping"}',
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"id":3,"method":"ping"}',
            '{"jsonrpc":"1.0","id":4,"method":"ping"}',
            '{"jsonrpc":2,"id":5,"method":"ping"}',
            '{"jsonrpc":null,"id":6,"method":"ping"}',
            '{"jsonrpc":"2.0","id":true,"method":"ping"}',
            '{"jsonrpc":"2.0","id":7,"method":"ping"}',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(MCP_PATH)],
                input="\n".join(msgs) + "\n",
                capture_output=True,
                text=True,
                env={"HOME": tmp, "PATH": "/usr/bin:/bin", "UNIENV_HOME": f"{tmp}/.unienv"},
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [json.loads(line) for line in proc.stdout.splitlines()]
        # 10 inputs, 1 notification -> 9 responses
        self.assertEqual(len(lines), 9)
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 1, "result": {}})
        self.assertEqual(lines[1], {"jsonrpc": "2.0", "id": "req-2", "result": {}})
        self.assertEqual(lines[2], {"jsonrpc": "2.0", "id": None, "result": {}})
        for idx, expected_id in [(3, 3), (4, 4), (5, 5), (6, 6), (7, None)]:
            self.assertEqual(lines[idx]["id"], expected_id)
            self.assertEqual(lines[idx]["error"]["code"], -32600)
            self.assertEqual(lines[idx]["error"]["message"], "Invalid Request")
        self.assertEqual(lines[8], {"jsonrpc": "2.0", "id": 7, "result": {}})


if __name__ == "__main__":
    unittest.main()
