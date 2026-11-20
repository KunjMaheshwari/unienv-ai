"""Cancellation, progress, and bounded subprocess cleanup regressions."""

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP_PATH = ROOT / "src" / "unienv_mcp.py"
spec = importlib.util.spec_from_file_location("unienv_mcp", MCP_PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class McpCancelAndProgressTests(unittest.TestCase):
    def setUp(self):
        mcp._REQUEST_TOOLS.clear()
        mcp._CANCELLED_IDS.clear()

    @contextlib.contextmanager
    def server(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            bin_dir = work / ".unienv" / "bin"
            bin_dir.mkdir(parents=True)
            launcher = bin_dir / "ue-py"
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            launcher.chmod(0o755)
            installer = bin_dir / "unienv"
            installer.write_text("#!/bin/sh\nsleep 0.5\nprintf installed\n")
            installer.chmod(0o755)
            proc = subprocess.Popen(
                [sys.executable, str(MCP_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "HOME": str(work),
                    "PATH": "/usr/bin:/bin",
                    "UNIENV_HOME": str(bin_dir.parent),
                    "UNIENV_WORKDIR": str(work),
                },
            )
            replies = queue.Queue()

            def read():
                for line in proc.stdout:
                    replies.put(json.loads(line))

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                yield proc, replies, work
            finally:
                proc.stdin.close()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                reader.join(timeout=2)
                proc.stdout.close()
                proc.stderr.close()

    def send(self, proc, msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def call(self, request_id, name, args):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }

    def cancel(self, proc, request_id):
        self.send(proc, {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": request_id}})

    def test_in_flight_call_answers_ping_and_cancelled_call_has_no_reply(self):
        with self.server() as (proc, replies, work):
            started = work / "started"
            code = (
                "import pathlib, signal, subprocess, sys, time\n"
                "child = subprocess.Popen(['sleep', '60'])\n"
                "def stop(*_):\n"
                "    child.wait(timeout=2)\n"
                "    sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                f"pathlib.Path({str(started)!r}).write_text(str(child.pid))\n"
                "time.sleep(60)\n"
            )
            self.send(proc, self.call(10, "run_python", {"code": code}))
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(started.exists())
            self.send(proc, {"jsonrpc": "2.0", "id": 11, "method": "ping"})
            self.assertEqual(replies.get(timeout=5), {"jsonrpc": "2.0", "id": 11, "result": {}})
            self.cancel(proc, 10)
            doc = work / "hello.txt"
            doc.write_text("worker recovered")
            self.send(proc, self.call(12, "read_document", {"path": str(doc)}))
            reply = replies.get(timeout=8)
            self.assertEqual(reply["id"], 12)
            self.assertFalse(reply["result"]["isError"])
            self.assertTrue(replies.empty())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(started.read_text()), 0)

    def test_queued_cancellation_and_unknown_ids_do_not_poison_future_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = pathlib.Path(tmp) / "hello.txt"
            doc.write_text("hello")
            request = self.call(20, "read_document", {"path": str(doc)})
            for invalid in (None, True, [], {}, "unknown", 999):
                self.assertFalse(mcp.cancel_request(invalid))
            self.assertEqual(mcp._CANCELLED_IDS, set())
            mcp._register_requests(request)
            self.assertTrue(mcp.cancel_request(20))
            with patch.object(mcp, "run") as run:
                self.assertIsNone(mcp._dispatch_message(request))
                run.assert_not_called()
            self.assertEqual(mcp._REQUEST_TOOLS, {})
            self.assertEqual(mcp._CANCELLED_IDS, set())
            self.assertFalse(mcp.cancel_request(20))
            self.assertFalse(mcp.handle(request)["result"]["isError"])

    def test_install_cancellation_is_ignored_and_normal_reply_is_sent(self):
        with self.server() as (proc, replies, _work):
            self.send(proc, self.call(30, "install_package", {"name": "six"}))
            self.cancel(proc, 30)
            reply = replies.get(timeout=5)
            self.assertEqual(reply["id"], 30)
            self.assertFalse(reply["result"]["isError"])
            self.assertIn("installed", reply["result"]["content"][0]["text"])

    def test_progress_heartbeats_increase_while_child_is_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            launcher = bin_dir / "ue-py"
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            launcher.chmod(0o755)
            req = self.call(40, "run_python", {"code": "import time; time.sleep(0.4)", "cwd": tmp})
            req["params"]["_meta"] = {"progressToken": "heartbeat"}
            buf = io.StringIO()
            with (
                patch.object(mcp, "BIN", bin_dir),
                patch.object(mcp, "_PROGRESS_INTERVAL", 0.05),
                contextlib.redirect_stdout(buf),
            ):
                reply = mcp.handle(req)
            self.assertFalse(reply["result"]["isError"])
            notifications = [json.loads(line) for line in buf.getvalue().splitlines()]
            values = [n["params"]["progress"] for n in notifications]
            self.assertGreaterEqual(len(values), 3)
            self.assertEqual(values, sorted(set(values)))
            self.assertTrue(any("Waiting for" in n["params"]["message"] for n in notifications))
            self.assertTrue(all(n["params"]["progressToken"] == "heartbeat" for n in notifications))
            self.assertTrue(all("total" not in n["params"] for n in notifications))

    def test_no_progress_without_a_valid_token(self):
        for token in (None, True, [], {}, 1.5):
            with self.subTest(token=token), contextlib.redirect_stdout(io.StringIO()) as buf:
                mcp._CURRENT_CTX.progress_token = token
                mcp.emit_progress("waiting")
                self.assertEqual(buf.getvalue(), "")
        mcp._CURRENT_CTX.progress_token = None

    def test_cleanup_bounds_communicate_and_keeps_partial_output(self):
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired("test", 2, output=b"partial")
        with patch.object(mcp, "_terminate_proc") as terminate:
            self.assertEqual(mcp._stop_and_drain(proc), "partial")
        terminate.assert_called_once_with(proc)
        proc.communicate.assert_called_once_with(timeout=2.0)
        proc.stdout.close.assert_called_once()
        proc.stderr.close.assert_called_once()
        proc.wait.assert_called_once_with(timeout=2.0)

    def test_timeout_does_not_hang_on_detached_child_holding_output_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            pid_file = work / "detached.pid"
            child_code = "import time; time.sleep(30)"
            code = (
                "import pathlib, subprocess, sys, time\n"
                f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}], start_new_session=True)\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                "print('partial output', flush=True)\n"
                "time.sleep(30)\n"
            )
            started = time.monotonic()
            try:
                result, out, err, _ = mcp.run([sys.executable, "-c", code], cwd=work, timeout=1)
                self.assertEqual(result, 124)
                self.assertIn("timed out", err)
                self.assertIn("partial output", out)
                self.assertLess(time.monotonic() - started, 8)
            finally:
                if pid_file.exists():
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(int(pid_file.read_text()), signal.SIGKILL)

    def test_termination_escalates_after_grace_period(self):
        proc = MagicMock(pid=123)
        proc.wait.side_effect = subprocess.TimeoutExpired("test", 3)
        with patch.object(mcp.os, "killpg") as killpg:
            mcp._terminate_proc(proc)
        self.assertEqual([call.args for call in killpg.call_args_list], [(123, signal.SIGTERM), (123, signal.SIGKILL)])
        proc.wait.assert_called_once_with(timeout=3.0)

    def test_soffice_launcher_cleans_profile_after_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            soffice = work / "fake-soffice"
            soffice.write_text("#!/bin/sh\nexec sleep 30\n")
            soffice.chmod(0o755)
            env = {**mcp.tool_env(), "TMPDIR": tmp, "UNIENV_SOFFICE": str(soffice)}
            code, _, _, _ = mcp.run([str(ROOT / "shims" / "soffice-safe")], cwd=work, timeout=1, env=env)
            self.assertEqual(code, 124)
            self.assertEqual(list(work.glob("ue_lo.*")), [])


if __name__ == "__main__":
    unittest.main()
