import importlib.util
import pathlib
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def _sample_manifest() -> dict:
    return {
        "bins": {"pandoc": "/usr/local/bin/pandoc"},
        "python": {"packages": {"python-docx": "1.1.0"}},
        "node": {"packages": {"docx": "8.5.0"}},
        "batteries": ["office", "pdf"],
    }


def _sample_recipes() -> list[dict]:
    return [
        {
            "id": "office",
            "summary": "Word, Excel and PowerPoint",
            "agent": {"notes": "- Use `ue-py` with python-docx."},
        }
    ]


class AgentTemplatePathTests(unittest.TestCase):
    def test_agent_block_uses_bin_for_unienv_and_shims(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = pathlib.Path(tmp) / ".unienv"
            fake_bin = fake_home / "bin"
            with patch.object(u, "BIN", fake_bin), patch.object(u, "UNIENV_HOME", fake_home):
                rendered = u.render_agent_block(_sample_manifest())

        self.assertNotIn("{{BIN}}", rendered)
        self.assertNotIn("{{HOME_DIR}}", rendered)
        self.assertIn(f"`{fake_bin}/ue-py`", rendered)
        self.assertIn(f"`{fake_bin}/ue-node`", rendered)
        self.assertIn(f"`{fake_bin}/unienv list`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need <python-package>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need --node <package>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need --bin <homebrew-formula>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need --cask <homebrew-cask>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv doctor --json`", rendered)
        self.assertIsNone(re.search(r"`unienv\s+(?:list|need|doctor)\b", rendered))

    def test_skill_template_uses_bin_for_unienv_and_shims(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = pathlib.Path(tmp) / ".unienv"
            fake_bin = fake_home / "bin"
            with patch.object(u, "BIN", fake_bin), patch.object(u, "UNIENV_HOME", fake_home):
                rendered = u.render_skill(_sample_manifest(), _sample_recipes())

        self.assertNotIn("{{BIN}}", rendered)
        self.assertNotIn("{{HOME_DIR}}", rendered)
        self.assertIn(f"`{fake_bin}/ue-py`", rendered)
        self.assertIn(f"`{fake_bin}/ue-node`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need <package>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need --node <package>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv need --bin <homebrew-formula>`", rendered)
        self.assertIn(f"`{fake_bin}/unienv doctor --json`", rendered)
        self.assertIsNone(re.search(r"`unienv\s+(?:list|need|doctor)\b", rendered))


if __name__ == "__main__":
    unittest.main()
