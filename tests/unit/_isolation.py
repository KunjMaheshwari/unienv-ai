"""Shared test isolation helper so unit tests never touch real user dotfiles or state."""

import contextlib
import os
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def isolated_home(
    u,
    tmp: Path | str,
    *,
    shell_files: list[Path] | None = None,
    unienv_home: Path | None = None,
    which_return=None,
    extra_env: dict[str, str] | None = None,
):
    """Redirect UniEnv's HOME, UNIENV_HOME, STATE_FILE, BACKUP_DIR, env vars, and `which` into `tmp`."""
    home = Path(tmp)
    ue_home = Path(unienv_home) if unienv_home is not None else home / ".unienv"
    env = {
        "HOME": str(home),
        "ZDOTDIR": "",
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    if extra_env:
        env.update(extra_env)
    patches = {
        "HOME": home,
        "UNIENV_HOME": ue_home,
        "BIN": ue_home / "bin",
        "PY_DIR": ue_home / "py",
        "NODE_DIR": ue_home / "node",
        "STATE_FILE": ue_home / "state.json",
        "BACKUP_DIR": ue_home / "backups",
        "MANIFEST_FILE": ue_home / "manifest.json",
        "ENV_SH": ue_home / "env.sh",
        "AGENTS_COPY": ue_home / "AGENTS.md",
        "LOG_FILE": ue_home / "log" / "events.jsonl",
        "LAUNCH_AGENT": home / "none.plist",
    }
    if shell_files is not None:
        patches["SHELL_FILES"] = shell_files
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env))
        for name, value in patches.items():
            if hasattr(u, name):
                stack.enter_context(patch.object(u, name, value))
        stack.enter_context(patch.object(u, "which", return_value=which_return))
        yield home, ue_home
