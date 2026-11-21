"""Unit tests for non-UTF-8 and read-only dotfile handling."""

import argparse
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class DotfileResilienceTests(unittest.TestCase):
    def test_non_utf8_bytes_round_trip_through_block_helpers(self):
        raw_prefix = b"# caf\xe9 \xff comment\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".zshenv"
            path.write_bytes(raw_prefix)
            self.assertTrue(u.upsert_block(path, "export FOO=1", "# BEGIN", "# END"))
            self.assertEqual(u.read_block(path, "# BEGIN", "# END"), "export FOO=1")
            self.assertTrue(path.read_bytes().startswith(raw_prefix))
            self.assertTrue(u.remove_block(path, "# BEGIN", "# END"))
            self.assertEqual(path.read_bytes(), raw_prefix)

    def test_read_block_returns_none_on_os_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unreadable"
            path.write_text("hello")
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                self.assertIsNone(u.read_block(path, "# BEGIN", "# END"))

    def test_wire_shells_continues_past_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ro = root / ".zshenv"
            ok = root / ".profile"
            ro.write_text("# read-only\n")
            ok.write_text("# writable\n")

            orig_upsert = u.upsert_block

            def fake_upsert(path, *args, **kwargs):
                if path == ro:
                    raise PermissionError("read-only file system")
                return orig_upsert(path, *args, **kwargs)

            err = io.StringIO()
            with (
                patch.dict(os.environ, {"ZDOTDIR": ""}),
                patch.object(u, "HOME", root),
                patch.object(u, "STATE_FILE", root / ".unienv" / "state.json"),
                patch.object(u, "ENV_SH", root / ".unienv" / "env.sh"),
                patch.object(u, "SHELL_FILES", [ro, ok]),
                patch.object(u, "upsert_block", side_effect=fake_upsert),
                contextlib.redirect_stderr(err),
            ):
                changed = u.wire_shells()

            self.assertEqual(changed, ["~/.profile"])
            self.assertIn("could not update", err.getvalue())
            self.assertIn("source", err.getvalue())
            self.assertIsNotNone(u.read_block(ok, u.SHELL_BEGIN, u.SHELL_END))

    def test_sync_agents_continues_past_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ro_md = root / "RO.md"
            ok_md = root / "OK.md"
            ro_md.write_text("# ro\n")
            ok_md.write_text("# ok\n")
            agents = [
                {"name": "ReadOnlyAgent", "instructions": ro_md, "skills": None},
                {"name": "WritableAgent", "instructions": ok_md, "skills": None},
            ]
            orig_upsert = u.upsert_block

            def fake_upsert(path, *args, **kwargs):
                if path == ro_md:
                    raise PermissionError("read-only")
                return orig_upsert(path, *args, **kwargs)

            err = io.StringIO()
            with (
                patch.object(u, "AGENTS_COPY", root / "AGENTS.md"),
                patch.object(u, "agent_targets", return_value=agents),
                patch.object(u, "render_agent_block", return_value="agent-block"),
                patch.object(u, "render_skill", return_value="skill-body"),
                patch.object(u, "upsert_block", side_effect=fake_upsert),
                contextlib.redirect_stderr(err),
            ):
                done = u.sync_agents({}, [], only_detected=False)

            self.assertEqual(done, ["WritableAgent"])
            self.assertIn("could not update", err.getvalue())
            self.assertEqual(u.read_block(ok_md, u.MD_BEGIN, u.MD_END), "agent-block")

    def test_uninstall_continues_past_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ro_rc = root / ".zshenv"
            ok_rc = root / ".profile"
            ro_md = root / "RO.md"
            ok_md = root / "OK.md"
            u.upsert_block(ro_rc, "source x", u.SHELL_BEGIN, u.SHELL_END)
            u.upsert_block(ok_rc, "source x", u.SHELL_BEGIN, u.SHELL_END)
            u.upsert_block(ro_md, "block", u.MD_BEGIN, u.MD_END)
            u.upsert_block(ok_md, "block", u.MD_BEGIN, u.MD_END)

            orig_remove = u.remove_block

            def fake_remove(path, *args, **kwargs):
                if path in (ro_rc, ro_md):
                    raise PermissionError("read-only")
                return orig_remove(path, *args, **kwargs)

            agents = [
                {"name": "RO", "instructions": ro_md, "skills": None},
                {"name": "OK", "instructions": ok_md, "skills": None},
            ]
            args = argparse.Namespace(purge=False)
            err = io.StringIO()
            with (
                patch.object(u, "SHELL_FILES", [ro_rc, ok_rc]),
                patch.object(u, "agent_targets", return_value=agents),
                patch.object(u, "mcp_clients", return_value={}),
                patch.object(u, "LAUNCH_AGENT", root / "none.plist"),
                patch.object(u, "UNIENV_HOME", root / ".unienv"),
                patch.object(u, "remove_block", side_effect=fake_remove),
                contextlib.redirect_stderr(err),
            ):
                rc = u.cmd_uninstall(args)

            self.assertEqual(rc, 0)
            self.assertIsNone(u.read_block(ok_rc, u.SHELL_BEGIN, u.SHELL_END))
            self.assertIsNone(u.read_block(ok_md, u.MD_BEGIN, u.MD_END))
            self.assertIn("could not update", err.getvalue())


if __name__ == "__main__":
    unittest.main()
