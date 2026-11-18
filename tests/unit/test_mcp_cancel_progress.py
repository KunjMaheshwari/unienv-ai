import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP_PATH = ROOT / "src" / "unienv_mcp.py"
spec = importlib.util.spec_from_file_location("unienv_mcp", MCP_PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class McpCancelAndProgressTests(unittest.TestCase):
    def test_in_flight_tool_call_answers_ping_and_terminates_on_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            unienv_home = work / ".unienv"
            bin_dir = unienv_home / "bin"
            bin_dir.mkdir(parents=True)
            ue_py = bin_dir / "ue-py"
            ue_py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            ue_py.chmod(0o755)
            pid_file = work / "started.pid"

            env = {
                "HOME": str(work),
                "PATH": "/usr/bin:/bin",
                "UNIENV_HOME": str(unienv_home),
                "UNIENV_WORKDIR": str(work),
            }
            server = subprocess.Popen(
                [sys.executable, str(MCP_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            try:
                code = (
                    "import pathlib, subprocess, time\n"
                    "child = subprocess.Popen(['sleep', '300'])\n"
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                    "time.sleep(300)\n"
                )
                req = {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {"name": "run_python", "arguments": {"code": code, "timeout_s": 60}},
                }
                server.stdin.write(json.dumps(req) + "\n")
                server.stdin.flush()

                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not pid_file.exists():
                    time.sleep(0.05)
                self.assertTrue(pid_file.exists(), "tool call did not start child process in time")
                grandchild_pid = int(pid_file.read_text().strip())

                # Send ping while request 10 is still running
                server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 11, "method": "ping"}) + "\n")
                server.stdin.flush()
                ping_line = server.stdout.readline()
                self.assertEqual(json.loads(ping_line), {"jsonrpc": "2.0", "id": 11, "result": {}})

                # Now cancel request 10
                cancel_start = time.monotonic()
                server.stdin.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/cancelled",
                            "params": {"requestId": 10, "reason": "user pressed stop"},
                        }
                    )
                    + "\n"
                )
                server.stdin.flush()
                tool_line = server.stdout.readline()
                cancel_elapsed = time.monotonic() - cancel_start
                self.assertLess(cancel_elapsed, 5.0)
                tool_reply = json.loads(tool_line)
                self.assertEqual(tool_reply["id"], 10)
                self.assertTrue(tool_reply["result"]["isError"])
                self.assertIn("cancelled", tool_reply["result"]["content"][0]["text"])
                self.assertFalse(_pid_alive(grandchild_pid), "grandchild process survived cancellation")
            finally:
                server.stdin.close()
                server.wait(timeout=5)
                server.stdout.close()
                server.stderr.close()

    def test_progress_token_emits_progress_notifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            txt = work / "hello.txt"
            txt.write_text("hello progress")
            buf = io.StringIO()
            with patch.object(mcp, "WORKDIR", work), contextlib.redirect_stdout(buf):
                reply = mcp.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 20,
                        "method": "tools/call",
                        "params": {
                            "name": "read_document",
                            "arguments": {"path": str(txt)},
                            "_meta": {"progressToken": "tok-20"},
                        },
                    }
                )
            self.assertFalse(reply["result"]["isError"])
            notifications = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
            self.assertGreaterEqual(len(notifications), 2)
            self.assertEqual(notifications[0]["method"], "notifications/progress")
            self.assertEqual(notifications[0]["params"]["progressToken"], "tok-20")
            self.assertEqual(notifications[0]["params"]["progress"], 0)
            self.assertEqual(notifications[-1]["params"]["progress"], 1)
            self.assertEqual(notifications[-1]["params"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
