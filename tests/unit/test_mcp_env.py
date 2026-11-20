"""Unit and security regression tests for tool_env() and install_env() in unienv_mcp."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv_mcp", ROOT / "src" / "unienv_mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)

SENSITIVE_OR_UNRELATED = (
    "UV_PUBLISH_TOKEN",
    "UV_PUBLISH_PASSWORD",
    "HOMEBREW_GITHUB_API_TOKEN",
    "HOMEBREW_GITHUB_PACKAGES_TOKEN",
    "OPENAI_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
    "RANDOM_VAR",
)


def _sample_environ(tmp_home: str) -> dict[str, str]:
    return {
        "HOME": tmp_home,
        "USER": "alice",
        "HTTP_PROXY": "http://proxy.corp:8080",
        "HTTPS_PROXY": "https://proxy.corp:8443",
        "http_proxy": "http://proxy.corp:8080",
        "https_proxy": "https://proxy.corp:8443",
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
        # Credentials and unrelated vars that must never leak:
        "UV_PUBLISH_TOKEN": "pypi-secret-token",
        "UV_PUBLISH_PASSWORD": "pypi-secret-password",
        "HOMEBREW_GITHUB_API_TOKEN": "ghp_brew_secret",
        "HOMEBREW_GITHUB_PACKAGES_TOKEN": "ghp_brew_pkg_secret",
        "OPENAI_API_KEY": "sk-secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "GITHUB_TOKEN": "ghp_secret",
        "RANDOM_VAR": "should-not-leak",
    }


class ToolEnvTests(unittest.TestCase):
    def test_run_python_receives_proxy_and_ca_but_no_credentials_or_publish_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_environ = _sample_environ(tmp)
            fake_proc = MagicMock(returncode=0)
            fake_proc.communicate.return_value = ("ok\n", "")
            with (
                patch.dict(os.environ, fake_environ, clear=True),
                patch.object(mcp, "WORKDIR", Path(tmp)),
                patch.object(mcp.subprocess, "Popen", return_value=fake_proc) as mock_popen,
            ):
                mcp.t_run_python({"code": "print('ok')", "cwd": tmp})

            env = mock_popen.call_args.kwargs["env"]
            for expected_key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE",
                "UNIENV_SOFFICE",
                "TESSDATA_PREFIX",
            ):
                self.assertEqual(env[expected_key], fake_environ[expected_key])

            for blocked in (*SENSITIVE_OR_UNRELATED, "UV_INDEX_URL", "PIP_INDEX_URL", "HOMEBREW_NO_AUTO_UPDATE"):
                self.assertNotIn(blocked, env)

    def test_install_package_receives_index_proxy_ca_and_homebrew_settings_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_environ = _sample_environ(tmp)
            fake_proc = MagicMock(returncode=0)
            fake_proc.communicate.return_value = ("installed\n", "")
            with (
                patch.dict(os.environ, fake_environ, clear=True),
                patch.object(mcp.subprocess, "Popen", return_value=fake_proc) as mock_popen,
            ):
                mcp.t_install_package({"name": "pandas", "kind": "python"})

            env = mock_popen.call_args.kwargs["env"]
            for expected_key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE",
                "UV_INDEX_URL",
                "UV_NATIVE_TLS",
                "PIP_INDEX_URL",
                "PIP_EXTRA_INDEX_URL",
                "HOMEBREW_NO_AUTO_UPDATE",
                "UNIENV_SOFFICE",
                "TESSDATA_PREFIX",
            ):
                self.assertEqual(env[expected_key], fake_environ[expected_key])

            for secret_key in SENSITIVE_OR_UNRELATED:
                self.assertNotIn(secret_key, env)

            self.assertEqual(env["UNIENV_HOME"], str(mcp.UNIENV_HOME))
            self.assertEqual(env["PYTHONUNBUFFERED"], "1")
            self.assertEqual(env["MPLBACKEND"], "Agg")


if __name__ == "__main__":
    unittest.main()
