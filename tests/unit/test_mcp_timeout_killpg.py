import importlib.util
import os
import pathlib
import sys
import tempfile
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


class TimeoutKillpgTests(unittest.TestCase):
    def test_t_run_python_timeout_kills_grandchild_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            ue_py = bin_dir / "ue-py"
            ue_py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            ue_py.chmod(0o755)
            pid_file = work / "grandchild.pid"
            code = (
                "import pathlib, subprocess, time\n"
                "child = subprocess.Popen(['sleep', '300'])\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                "print('spawned', flush=True)\n"
                "time.sleep(300)\n"
            )
            with patch.object(mcp, "BIN", bin_dir), patch.object(mcp, "WORKDIR", work):
                with self.assertRaises(mcp.ToolError) as ctx:
                    mcp.t_run_python({"code": code, "cwd": str(work), "timeout_s": 1})
            self.assertIn("exit code: 124", str(ctx.exception))
            self.assertIn("timed out after 1s", str(ctx.exception))
            self.assertTrue(pid_file.exists(), "grandchild pid was not recorded before timeout")
            grandchild_pid = int(pid_file.read_text().strip())
            self.assertFalse(_pid_alive(grandchild_pid), f"grandchild sleep 300 (pid {grandchild_pid}) survived")

    def test_run_timeout_escalates_to_sigkill_for_sigterm_ignoring_grandchild(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            pid_file = work / "stubborn.pid"
            child_code = (
                "import pathlib, signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(__import__('os').getpid()))\n"
                "time.sleep(300)\n"
            )
            parent_code = (
                "import subprocess, sys, time\n"
                f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
                "time.sleep(300)\n"
            )
            code, _out, err, _secs = mcp.run([sys.executable, "-c", parent_code], cwd=work, timeout=1)
            self.assertEqual(code, 124)
            self.assertIn("timed out after 1s", err)
            self.assertTrue(pid_file.exists())
            grandchild_pid = int(pid_file.read_text().strip())
            self.assertFalse(_pid_alive(grandchild_pid), f"SIGKILL escalation failed for pid {grandchild_pid}")

    def test_soffice_safe_cleans_up_profile_and_child_on_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            pid_file = work / "soffice.pid"
            fake_soffice = work / "fake-soffice"
            fake_soffice.write_text(f"#!/bin/sh\necho $$ > {str(pid_file)!r}\nexec sleep 300\n")
            fake_soffice.chmod(0o755)
            shim = ROOT / "shims" / "soffice-safe"
            env = {**mcp.tool_env(), "TMPDIR": str(work), "UNIENV_SOFFICE": str(fake_soffice)}
            code, _out, err, _secs = mcp.run([str(shim), "--convert-to", "pdf"], cwd=work, timeout=2, env=env)
            self.assertEqual(code, 124)
            self.assertIn("timed out after 2s", err)
            self.assertTrue(pid_file.exists())
            soffice_pid = int(pid_file.read_text().strip())
            self.assertFalse(_pid_alive(soffice_pid), "fake soffice child process survived")
            leftover_profiles = list(work.glob("ue_lo.*"))
            self.assertEqual(leftover_profiles, [], f"profile dir leaked: {leftover_profiles}")


if __name__ == "__main__":
    unittest.main()
