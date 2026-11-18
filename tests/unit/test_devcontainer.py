"""Unit tests for #41 (Dockerfile and Dev Container Feature schema validation)."""

import json
import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class DevcontainerDockerTests(unittest.TestCase):
    def test_devcontainer_feature_json_matches_schema(self):
        path = ROOT / ".devcontainer" / "unienv" / "devcontainer-feature.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["id"], "unienv")
        self.assertIn("version", data)
        self.assertIn("name", data)
        self.assertIn("description", data)
        self.assertIn("options", data)
        self.assertIn("batteries", data["options"])
        self.assertEqual(data["options"]["batteries"]["type"], "string")
        self.assertEqual(data["options"]["batteries"]["default"], "")

    def test_devcontainer_install_script_exists_and_is_executable(self):
        script = ROOT / ".devcontainer" / "unienv" / "install.sh"
        self.assertTrue(script.exists())
        self.assertTrue(os.access(script, os.X_OK))
        text = script.read_text()
        self.assertIn("BATTERIES", text)
        self.assertIn("--all-agents", text)

    def test_dockerfile_uses_debian_bookworm_slim_and_wires_agents(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("FROM debian:bookworm-slim", dockerfile)
        self.assertIn("./install.sh --yes --all-agents", dockerfile)
        self.assertIn("AGENTS.md", dockerfile)
        self.assertIn("CLAUDE.md", dockerfile)


if __name__ == "__main__":
    unittest.main()
