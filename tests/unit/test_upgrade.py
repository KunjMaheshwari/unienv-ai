"""Unit tests for `unienv upgrade` (#27)."""

import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class UpgradeTests(unittest.TestCase):
    def _setup_home(self, stack, tmp_dir):
        root = pathlib.Path(tmp_dir)
        stack.enter_context(patch.object(u, "UNIENV_HOME", root))
        stack.enter_context(patch.object(u, "PY_DIR", root / "py"))
        stack.enter_context(patch.object(u, "NODE_DIR", root / "node"))
        stack.enter_context(patch.object(u, "STATE_FILE", root / "state.json"))
        stack.enter_context(patch.object(u, "BACKUP_DIR", root / "backups"))
        stack.enter_context(patch.object(u, "LOG_FILE", root / "log" / "unienv.log"))
        return root

    def test_dry_run_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            self._setup_home(stack, tmp)
            recipes = u.load_recipes()
            state = u.default_state(recipes)
            u.save_state(state)
            u.PY_DIR.mkdir(parents=True, exist_ok=True)
            u.NODE_DIR.mkdir(parents=True, exist_ok=True)
            (u.PY_DIR / "pyproject.toml").write_text("# py\n")
            (u.PY_DIR / "uv.lock").write_text("version = 1\n")
            (u.NODE_DIR / "package.json").write_text("{}\n")

            cmds = []

            def fake_run(cmd, **kw):
                cmds.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "Updated pandas v2.2.0 -> v2.2.3\n", "")

            stack.enter_context(patch.object(u, "find_uv", return_value="/usr/local/bin/uv"))
            stack.enter_context(patch.object(u, "which", return_value="/usr/local/bin/npm"))
            stack.enter_context(patch.object(u, "run", side_effect=fake_run))

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = u.cmd_upgrade(argparse.Namespace(packages=[], node=False, dry_run=True))

            self.assertEqual(rc, 0)
            self.assertIn("Updated pandas v2.2.0 -> v2.2.3", out.getvalue())
            self.assertTrue(any("--dry-run" in c and "--upgrade" in c for c in cmds))
            self.assertTrue(any("outdated" in c for c in cmds))
            self.assertEqual((u.PY_DIR / "uv.lock").read_text(), "version = 1\n")
            self.assertFalse(u.BACKUP_DIR.exists())

    def test_targeted_package_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            self._setup_home(stack, tmp)
            recipes = u.load_recipes()
            state = u.default_state(recipes)
            u.save_state(state)

            cmds = []
            versions = [{"pandas": "2.2.0"}, {"pandas": "2.2.3"}]

            stack.enter_context(patch.object(u, "find_uv", return_value="/usr/local/bin/uv"))
            stack.enter_context(
                patch.object(
                    u,
                    "run",
                    side_effect=lambda cmd, **kw: cmds.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
                )
            )
            stack.enter_context(patch.object(u, "install_python", return_value=None))
            stack.enter_context(patch.object(u, "_verify_python_imports", return_value={}))
            stack.enter_context(patch.object(u, "python_packages", side_effect=lambda: versions.pop(0)))
            stack.enter_context(patch.object(u, "do_sync", return_value={}))

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = u.cmd_upgrade(argparse.Namespace(packages=["pandas"], node=False, dry_run=False))

            self.assertEqual(rc, 0)
            self.assertTrue(any("--upgrade-package" in c and "pandas" in c for c in cmds))
            self.assertFalse(any("npm" in str(c) for c in cmds))
            self.assertIn("pandas 2.2.0 -> 2.2.3", out.getvalue())

    def test_full_upgrade_updates_python_and_node(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            self._setup_home(stack, tmp)
            recipes = u.load_recipes()
            state = u.default_state(recipes)
            u.save_state(state)
            u.NODE_DIR.mkdir(parents=True, exist_ok=True)
            (u.NODE_DIR / "package.json").write_text(json.dumps({"dependencies": {"docx": "^8.0.0"}}) + "\n")

            cmds = []
            py_vers = [{"requests": "2.31.0"}, {"requests": "2.32.3"}]
            node_vers = [{"docx": "8.5.0"}, {"docx": "9.0.0"}]

            stack.enter_context(patch.object(u, "find_uv", return_value="/usr/local/bin/uv"))
            stack.enter_context(patch.object(u, "which", return_value="/usr/local/bin/npm"))
            stack.enter_context(
                patch.object(
                    u,
                    "run",
                    side_effect=lambda cmd, **kw: cmds.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
                )
            )
            stack.enter_context(patch.object(u, "install_python", return_value=None))
            stack.enter_context(patch.object(u, "_verify_python_imports", return_value={}))
            stack.enter_context(patch.object(u, "python_packages", side_effect=lambda: py_vers.pop(0)))
            stack.enter_context(patch.object(u, "node_packages", side_effect=lambda _: node_vers.pop(0)))
            stack.enter_context(patch.object(u, "do_sync", return_value={}))

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = u.cmd_upgrade(argparse.Namespace(packages=[], node=False, dry_run=False))

            self.assertEqual(rc, 0)
            self.assertTrue(any("--upgrade" in c for c in cmds))
            self.assertTrue(any("update" in c for c in cmds))
            self.assertIn("requests 2.31.0 -> 2.32.3", out.getvalue())
            self.assertIn("node:docx 8.5.0 -> 9.0.0", out.getvalue())

    def test_automatic_rollback_when_import_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            self._setup_home(stack, tmp)
            recipes = u.load_recipes()
            state = u.default_state(recipes)
            u.save_state(state)
            u.PY_DIR.mkdir(parents=True, exist_ok=True)
            orig_pyproject = "# original pyproject\n"
            orig_lock = "# original lockfile\n"
            (u.PY_DIR / "pyproject.toml").write_text(orig_pyproject)
            (u.PY_DIR / "uv.lock").write_text(orig_lock)

            def fake_run(cmd, **kw):
                (u.PY_DIR / "uv.lock").write_text("# upgraded broken lock\n")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            reinstall_calls = []

            def fake_install_python(packages):
                reinstall_calls.append(list(packages))

            stack.enter_context(patch.object(u, "find_uv", return_value="/usr/local/bin/uv"))
            stack.enter_context(patch.object(u, "run", side_effect=fake_run))
            stack.enter_context(patch.object(u, "install_python", side_effect=fake_install_python))
            stack.enter_context(
                patch.object(u, "_verify_python_imports", return_value={"pandas": "ImportError: broken ABI"})
            )
            stack.enter_context(patch.object(u, "python_packages", return_value={"pandas": "2.2.0"}))
            stack.enter_context(patch.object(u, "node_packages", return_value={}))

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                rc = u.cmd_upgrade(argparse.Namespace(packages=["pandas"], node=False, dry_run=False))

            self.assertEqual(rc, 1)
            self.assertIn("import check failed after upgrade", err.getvalue())
            self.assertIn("rolling back", err.getvalue())
            self.assertEqual((u.PY_DIR / "pyproject.toml").read_text(), orig_pyproject)
            self.assertEqual((u.PY_DIR / "uv.lock").read_text(), orig_lock)
            self.assertEqual(len(reinstall_calls), 2)


if __name__ == "__main__":
    unittest.main()
