import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]

spec_u = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec_u)
spec_u.loader.exec_module(u)

spec_m = importlib.util.spec_from_file_location("unienv_mcp", ROOT / "src" / "unienv_mcp.py")
m = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(m)


class McpHelpersTest(unittest.TestCase):
    def test_release_versions_stay_in_sync(self):
        manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text())
        self.assertEqual(u.VERSION, m.SERVER_VERSION)
        self.assertEqual(u.VERSION, manifest["version"])

    def test_free_name_increments_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp) / "report.pdf"
            self.assertEqual(m.free_name(base), base)
            base.write_text("v0")
            p1 = m.free_name(base)
            self.assertEqual(p1.name, "report-1.pdf")
            p1.write_text("v1")
            p2 = m.free_name(base)
            self.assertEqual(p2.name, "report-2.pdf")

    def test_resolve_and_workdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp) / "work"
            with patch.object(m, "WORKDIR", base):
                rel = m.resolve("notes/todo.md")
                self.assertEqual(rel, base / "notes/todo.md")
                abs_p = m.resolve("/tmp/example.txt")
                self.assertEqual(abs_p, pathlib.Path("/tmp/example.txt"))
                tilde_p = m.resolve("~/doc.pdf")
                self.assertEqual(tilde_p, pathlib.Path(os.path.expanduser("~/doc.pdf")))

                wd = m.workdir(None)
                self.assertEqual(wd, base)
                self.assertTrue(wd.is_dir())

                sub_wd = m.workdir("sub/dir")
                self.assertEqual(sub_wd, base / "sub/dir")
                self.assertTrue(sub_wd.is_dir())

    def test_cap_truncates_with_summary(self):
        self.assertEqual(m.cap("short", 10), "short")
        out = m.cap("abcdefghijklmno", 5)
        self.assertTrue(out.startswith("abcde\n\n[… truncated 10 more characters]"))

    def test_snapshot_and_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            a = d / "a.txt"
            a.write_text("initial")
            before = m.snapshot(d)
            self.assertEqual(m.changed_files(d, before), [])

            b = d / "b.txt"
            b.write_text("created")
            self.assertEqual(m.changed_files(d, before), [str(b)])

    def test_allowed_tools_filters_uv_and_missing_bins_and_includes_ue_node(self):
        fake_manifest = {
            "bins": {
                "pandoc": "/opt/homebrew/bin/pandoc",
                "qpdf": None,
                "uv": "/Users/test/.local/bin/uv",
            }
        }
        with patch.object(m, "manifest", return_value=fake_manifest):
            tools = m.allowed_tools()
        self.assertIn("pandoc", tools)
        self.assertIn("ue-node", tools)
        self.assertNotIn("qpdf", tools)
        self.assertNotIn("uv", tools)

    def test_tool_env_sets_path_and_tmpdir(self):
        with patch.dict(os.environ, {"TMPDIR": "/tmp", "SECRET_TOKEN": "hidden"}, clear=False):
            env = m.tool_env()
        self.assertIn(str(m.BIN), env["PATH"].split(os.pathsep))
        self.assertNotIn("SECRET_TOKEN", env)
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")
        self.assertEqual(env["MPLBACKEND"], "Agg")
        if m.sys.platform == "darwin":
            self.assertEqual(env["TMPDIR"], "/private/tmp")

    def test_install_package_validation_and_invocation(self):
        with self.assertRaises(m.ToolError):
            m.t_install_package({"name": "seaborn", "kind": "apt"})
        for bad in ("", "-y", "--cask", "pkg\nother", "pkg;rm"):
            with self.subTest(bad=bad):
                with self.assertRaises(m.ToolError):
                    m.t_install_package({"name": bad, "kind": "python"})

        with patch.object(m, "run", return_value=(0, "installed ok", "", 0.5)) as mock_run:
            res = m.t_install_package({"name": "seaborn @scope/pkg@1.0", "kind": "node"})
        self.assertIn("installed ok", res)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[1:4], ["need", "--node", "--"])
        self.assertEqual(cmd[4:], ["seaborn", "@scope/pkg@1.0"])


if __name__ == "__main__":
    unittest.main()
