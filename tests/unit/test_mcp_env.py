"""Unit tests for tool_env() allowlist in unienv_mcp."""

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv_mcp", ROOT / "src" / "unienv_mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class ToolEnvTests(unittest.TestCase):
    def test_passes_through_proxy_ca_package_and_unienv_vars_only(self):
        fake_environ = {
            "HOME": "/tmp/home",
            "USER": "alice",
            "HTTP_PROXY": "http://proxy.corp:8080",
            "https_proxy": "http://proxy.corp:8443",
            "NO_PROXY": "localhost,127.0.0.1",
            "no_proxy": ".internal",
            "ALL_PROXY": "socks5://proxy.corp:1080",
            "all_proxy": "socks5://proxy.corp:1080",
            "SSL_CERT_FILE": "/etc/ssl/corp.pem",
            "SSL_CERT_DIR": "/etc/ssl/certs",
            "REQUESTS_CA_BUNDLE": "/etc/ssl/corp.pem",
            "NODE_EXTRA_CA_CERTS": "/etc/ssl/corp.pem",
            "UV_INDEX_URL": "https://pypi.corp/simple",
            "UV_NATIVE_TLS": "true",
            "PIP_INDEX_URL": "https://pypi.corp/simple",
            "PIP_EXTRA_INDEX_URL": "https://pypi.org/simple",
            "HOMEBREW_NO_AUTO_UPDATE": "1",
            "UNIENV_SOFFICE": "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "TESSDATA_PREFIX": "/opt/tessdata",
            # Secrets / unrelated env vars must NOT pass through:
            "OPENAI_API_KEY": "sk-secret",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "GITHUB_TOKEN": "ghp_secret",
            "RANDOM_VAR": "should-not-leak",
        }
        with patch.dict(os.environ, fake_environ, clear=True):
            env = mcp.tool_env()

        for expected_key in (
            "HOME",
            "USER",
            "HTTP_PROXY",
            "https_proxy",
            "NO_PROXY",
            "no_proxy",
            "ALL_PROXY",
            "all_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "NODE_EXTRA_CA_CERTS",
            "UV_INDEX_URL",
            "UV_NATIVE_TLS",
            "PIP_INDEX_URL",
            "PIP_EXTRA_INDEX_URL",
            "HOMEBREW_NO_AUTO_UPDATE",
            "UNIENV_SOFFICE",
            "TESSDATA_PREFIX",
        ):
            self.assertEqual(env[expected_key], fake_environ[expected_key])

        for secret_key in ("OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "RANDOM_VAR"):
            self.assertNotIn(secret_key, env)

        self.assertEqual(env["UNIENV_HOME"], str(mcp.UNIENV_HOME))
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")
        self.assertEqual(env["MPLBACKEND"], "Agg")


if __name__ == "__main__":
    unittest.main()
