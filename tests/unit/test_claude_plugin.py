"""Unit tests for #40 (Claude Code plugin manifests, dynamic skill, and MCP launcher)."""

import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ClaudePluginTests(unittest.TestCase):
    def test_plugin_manifests_are_valid_json_and_register_mcp_and_skills(self):
        for rel in (".claude-plugin/plugin.json", "plugins/unienv/.claude-plugin/plugin.json"):
            with self.subTest(manifest=rel):
                path = ROOT / rel
                self.assertTrue(path.exists(), f"missing {rel}")
                data = json.loads(path.read_text())
                self.assertEqual(data["name"], "unienv")
                self.assertIn("version", data)
                self.assertIn("description", data)
                self.assertIn("skills", data)
                self.assertIn("unienv", data["mcpServers"])
                self.assertIn("unienv-mcp.sh", data["mcpServers"]["unienv"]["command"])

    def test_marketplace_manifest_is_valid(self):
        path = ROOT / ".claude-plugin" / "marketplace.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["name"], "unienv")
        self.assertEqual(data["plugins"][0]["name"], "unienv")
        self.assertEqual(data["plugins"][0]["source"], "./plugins/unienv")

    def test_plugin_skill_reads_manifest_and_shows_install_command(self):
        skill = (ROOT / "plugins/unienv/skills/unienv/SKILL.md").read_text()
        self.assertIn("name: unienv", skill)
        self.assertIn("~/.unienv/manifest.json", skill)
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/rupeshbharambe24/unienv-ai/main/install.sh | bash", skill
        )

    def test_plugin_mcp_launcher_prints_install_hint_when_unienv_missing(self):
        script = ROOT / "plugins/unienv/scripts/unienv-mcp.sh"
        self.assertTrue(os.access(script, os.X_OK))
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [str(script)],
                env={"HOME": tmp, "UNIENV_HOME": f"{tmp}/.unienv", "PATH": "/usr/bin:/bin"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("UniEnv is not installed", r.stderr)
            self.assertIn("install.sh | bash", r.stderr)


if __name__ == "__main__":
    unittest.main()
