#!/usr/bin/env python3
"""Unit tests for system package checks (stdlib unittest only)."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))
import unienv  # noqa: E402


def _result(cmd, stdout="", code=0):
    return subprocess.CompletedProcess(cmd, code, stdout, "")


class AptInstalledTest(unittest.TestCase):
    """`unienv install` must only skip packages dpkg says are fully installed."""

    def _run_install(self, query_stdout, query_code=0):
        cmds = []

        def fake_run(cmd, **kw):
            cmds.append(cmd)
            if cmd[:1] == ["dpkg-query"]:
                return _result(cmd, query_stdout, query_code)
            return _result(cmd)

        w = {"apt": ["tesseract-ocr"], "bins": []}
        with (
            mock.patch.object(unienv, "platform_key", return_value="debian"),
            mock.patch.object(unienv, "run", side_effect=fake_run),
            mock.patch.object(unienv.os, "geteuid", return_value=0, create=True),
        ):
            failures = unienv.install_system(w, assume_yes=True)
        return failures, cmds

    def test_config_files_package_is_reinstalled(self):
        # After `apt remove`, dpkg-query reports `deinstall ok config-files`.
        # Such a package is NOT installed and must be reinstalled.
        failures, cmds = self._run_install("deinstall ok config-files\n")
        self.assertEqual(failures, [])
        self.assertTrue(
            any(c[:2] == ["apt-get", "install"] for c in cmds), "a config-files package should trigger apt-get install"
        )

    def test_fully_installed_package_is_not_reinstalled(self):
        failures, cmds = self._run_install("install ok installed\n")
        self.assertEqual(failures, [])
        self.assertFalse(any("apt-get" in c for c in cmds), "an installed package must not be reinstalled")

    def test_uses_dpkg_query_status(self):
        _, cmds = self._run_install("install ok installed\n")
        self.assertTrue(
            any(c[:1] == ["dpkg-query"] for c in cmds), "installed check should use dpkg-query's Status field"
        )

    def test_unknown_package_is_installed(self):
        failures, cmds = self._run_install("", query_code=1)
        self.assertEqual(failures, [])
        self.assertTrue(any(c[:2] == ["apt-get", "install"] for c in cmds))


if __name__ == "__main__":
    unittest.main()
