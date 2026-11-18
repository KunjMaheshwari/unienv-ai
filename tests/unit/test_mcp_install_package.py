"""Unit tests for install_package validation and command construction in unienv_mcp."""

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("unienv_mcp", Path(__file__).parents[2] / "src/unienv_mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class InstallPackageTests(unittest.TestCase):
    def test_accepts_valid_package_specs(self):
        cases = [
            ("pandas==2.*", "python", []),
            ("requests==2.31.0", "python", []),
            ("scikit-learn", "python", []),
            ("pkg[a,b]>=1,<2", "python", []),
            ("node-gyp@^9", "node", ["--node"]),
            ("docx@~8.5", "node", ["--node"]),
            ("@scope/pkg", "node", ["--node"]),
            ("@scope/pkg@^1.2.3", "node", ["--node"]),
            ("user/tap/formula", "brew", ["--bin"]),
        ]
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="installed\n", stderr="")
        for name, kind, expected_flag in cases:
            with self.subTest(name=name, kind=kind):
                with patch.object(mcp.subprocess, "run", return_value=fake_proc) as mock_run:
                    result = mcp.t_install_package({"name": name, "kind": kind})
                self.assertEqual(result, "installed")
                mock_run.assert_called_once()
                cmd = mock_run.call_args.args[0]
                self.assertEqual(cmd, [str(mcp.BIN / "unienv"), "need", *expected_flag, "--", name])
                self.assertFalse(mock_run.call_args.kwargs.get("shell", False))

    def test_accepts_multiple_space_separated_specs(self):
        fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch.object(mcp.subprocess, "run", return_value=fake_proc) as mock_run:
            result = mcp.t_install_package({"name": "pandas==2.* requests==2.31.0", "kind": "python"})
        self.assertEqual(result, "ok")
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd, [str(mcp.BIN / "unienv"), "need", "--", "pandas==2.*", "requests==2.31.0"])

    def test_rejects_malicious_and_invalid_specs(self):
        invalid_specs = [
            "",
            "   ",
            "--help",
            "\u2013help",
            "-y",
            "pandas -y",
            "seaborn --cask evil",
            "pandas\n--help",
            "pkg\nmalicious",
            "pkg\tmalicious",
            "*pkg",
            "^pkg",
            "; rm -rf /",
            "x; rm -rf /",
            "pkg;echo malicious",
            "pkg|command",
            "$(malicious_command)",
            "pkg && malicious_command",
            "pkg`id`",
            'pkg"quote',
        ]
        for bad in invalid_specs:
            with self.subTest(name=bad):
                with patch.object(mcp.subprocess, "run") as mock_run:
                    with self.assertRaises(mcp.ToolError) as ctx:
                        mcp.t_install_package({"name": bad, "kind": "python"})
                self.assertIn("invalid package name", str(ctx.exception))
                mock_run.assert_not_called()

    def test_rejects_invalid_kind(self):
        with patch.object(mcp.subprocess, "run") as mock_run:
            with self.assertRaises(mcp.ToolError) as ctx:
                mcp.t_install_package({"name": "pandas", "kind": "pip"})
        self.assertIn("kind must be one of", str(ctx.exception))
        mock_run.assert_not_called()

    def test_nonzero_exit_raises_tool_error(self):
        fake_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no such package\n")
        with patch.object(mcp.subprocess, "run", return_value=fake_proc):
            with self.assertRaises(mcp.ToolError) as ctx:
                mcp.t_install_package({"name": "pandas==2.*", "kind": "python"})
        self.assertIn("no such package", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
