"""Unit tests for #39 (Homebrew formula and Cellar detection in `unienv update`)."""

import argparse
import contextlib
import importlib.util
import io
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class HomebrewUpdateTests(unittest.TestCase):
    def test_is_homebrew_install_detects_cellar_path(self):
        with patch.object(u, "__file__", "/opt/homebrew/Cellar/unienv/0.2.2/libexec/src/unienv.py"):
            self.assertTrue(u._is_homebrew_install())
            self.assertEqual(u._cli_script_path(), pathlib.Path("/opt/homebrew/opt/unienv/libexec/src/unienv.py"))
        with patch.object(u, "__file__", "/opt/homebrew/opt/unienv/libexec/src/unienv.py"):
            self.assertTrue(u._is_homebrew_install())
        with patch.object(u, "__file__", "/Users/alice/.unienv/share/src/unienv.py"):
            self.assertFalse(u._is_homebrew_install())

    def test_cmd_update_recommends_brew_upgrade_when_in_cellar(self):
        out = io.StringIO()
        with (
            patch.object(u, "__file__", "/opt/homebrew/Cellar/unienv/0.2.2/libexec/src/unienv.py"),
            contextlib.redirect_stdout(out),
        ):
            rc = u.cmd_update(argparse.Namespace(ref="main", no_wire=False))
        self.assertEqual(rc, 0)
        self.assertIn("UniEnv was installed via Homebrew; update with: brew upgrade unienv", out.getvalue())

    def test_formula_template_exists_and_has_required_stanzas(self):
        formula = (ROOT / "Formula" / "unienv.rb").read_text()
        self.assertIn("class Unienv < Formula", formula)
        self.assertIn('license any_of: ["MIT", "Apache-2.0"]', formula)
        self.assertIn("/releases/download/", formula)
        self.assertIn('depends_on "uv"', formula)
        self.assertNotIn('depends_on "python@3.12"', formula)
        self.assertIn("python find 3.12 --managed-python --system", formula)
        self.assertIn("#{opt_libexec}/src/unienv.py", formula)
        self.assertIn('libexec.install "src", "recipes", "templates", "shims"', formula)
        self.assertIn("unienv install", formula)

    def test_release_workflow_renders_valid_quoted_formula_from_sha256sums(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
        match = re.search(
            r"- name: Render Homebrew formula\n\s+run: \|\n((?: {10}.*\n)+)",
            workflow,
        )
        self.assertIsNotNone(match, "Render Homebrew formula step not found in release.yml")
        script = "\n".join(line[10:] for line in match.group(1).splitlines())
        self.assertIn("releases/download", script)
        self.assertIn("dist/SHA256SUMS", script)
        self.assertNotIn("archive/refs/tags", script)
        self.assertIn("ruby -c dist/unienv.rb", script)
        self.assertIn("rupeshbharambe24/homebrew-tap.git", workflow)
        self.assertNotIn("homebrew-unienv", workflow)

        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / "Formula").mkdir()
            (work / "dist").mkdir()
            shutil.copy2(ROOT / "Formula" / "unienv.rb", work / "Formula" / "unienv.rb")
            fake_sha = "a" * 64
            (work / "dist" / "SHA256SUMS").write_text(f"{fake_sha}  unienv-ai-v0.3.0.tar.gz\n{'b' * 64}  unienv.mcpb\n")
            env = dict(os.environ)
            env["GITHUB_REPOSITORY"] = "rupeshbharambe24/unienv-ai"
            env["GITHUB_REF_NAME"] = "v0.3.0"
            res = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, f"Render step failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
            rendered = (work / "dist" / "unienv.rb").read_text()
            self.assertIn(
                '  url "https://github.com/rupeshbharambe24/unienv-ai/releases/download/v0.3.0/unienv-ai-v0.3.0.tar.gz"',
                rendered,
            )
            self.assertIn(f'  sha256 "{fake_sha}"', rendered)
            self.assertIn('  license any_of: ["MIT", "Apache-2.0"]', rendered)


if __name__ == "__main__":
    unittest.main()
