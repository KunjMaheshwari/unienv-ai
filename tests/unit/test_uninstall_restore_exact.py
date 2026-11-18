import argparse
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class UninstallRestoreExactTests(unittest.TestCase):
    def _dummy_manifest(self) -> dict:
        return {
            "unienv": u.VERSION,
            "batteries": ["core", "office"],
            "python": {"packages": {"python-docx": "1.1.2"}},
            "node": {"packages": {"docx": "8.5.0"}},
            "bins": {"pandoc": "/usr/local/bin/pandoc"},
        }

    def test_wire_and_uninstall_restores_dotfiles_and_claude_md_byte_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            ue_home = home / ".unienv"
            ue_home.mkdir()
            claude_dir = home / ".claude"
            claude_dir.mkdir()

            zshenv = home / ".zshenv"
            profile = home / ".profile"
            bashrc = home / ".bashrc"
            claude_md = claude_dir / "CLAUDE.md"

            fixtures = {
                zshenv: b"export ZSH_USER_VAR=1\nalias gs='git status'\n",
                profile: b'export PROFILE_USER_VAR=1\r\nexport PATH="$HOME/bin:$PATH"\r\n',
                bashrc: b"# bashrc config\nexport EDITOR=vim\n",
                claude_md: b"# Personal Claude Rules\n- Prefer small diffs\n",
            }
            for p, raw in fixtures.items():
                p.write_bytes(raw)

            shell_files = [home / f for f in (".zshenv", ".profile", ".bashrc", ".bash_profile", ".bash_login")]
            with (
                patch.object(u, "HOME", home),
                patch.object(u, "UNIENV_HOME", ue_home),
                patch.object(u, "ENV_SH", ue_home / "env.sh"),
                patch.object(u, "AGENTS_COPY", ue_home / "AGENTS.md"),
                patch.object(u, "SHELL_FILES", shell_files),
                patch.object(u, "LAUNCH_AGENT", home / "Library/LaunchAgents/ai.unienv.path.plist"),
            ):
                u.wire_shells()
                u.sync_agents(self._dummy_manifest(), list(u.load_recipes().values()), only_detected=True)

                for p in fixtures:
                    self.assertIn(b"unienv", p.read_bytes())

                u.cmd_uninstall(argparse.Namespace(purge=False))

                for p, expected in fixtures.items():
                    with self.subTest(file=p.name):
                        self.assertEqual(p.read_bytes(), expected)
                self.assertFalse((claude_dir / "skills" / "unienv").exists())

    def test_file_without_trailing_newline_preserves_content_after_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            ue_home = home / ".unienv"
            ue_home.mkdir()
            zshenv = home / ".zshenv"
            zshenv.write_bytes(b"export NO_TRAILING_NL=1")

            with (
                patch.object(u, "HOME", home),
                patch.object(u, "UNIENV_HOME", ue_home),
                patch.object(u, "ENV_SH", ue_home / "env.sh"),
                patch.object(u, "SHELL_FILES", [zshenv]),
                patch.object(u, "LAUNCH_AGENT", home / "Library/LaunchAgents/ai.unienv.path.plist"),
            ):
                u.wire_shells()
                self.assertIsNotNone(u.read_block(zshenv, u.SHELL_BEGIN, u.SHELL_END))
                u.cmd_uninstall(argparse.Namespace(purge=False))
                self.assertEqual(zshenv.read_text().strip(), "export NO_TRAILING_NL=1")
                self.assertIsNone(u.read_block(zshenv, u.SHELL_BEGIN, u.SHELL_END))


if __name__ == "__main__":
    unittest.main()
