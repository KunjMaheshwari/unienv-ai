"""Unit tests for #66 (safe tar extraction on Python 3.11.0-3.11.3 and 3.11.4+)."""

import importlib.util
import io
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("unienv", ROOT / "src" / "unienv.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def _build_tar(entries: list[tuple[str, bytes | None, int, str]]) -> tarfile.TarFile:
    """Build an in-memory TarFile from (name, content, type, linkname) tuples."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data, ttype, linkname in entries:
            info = tarfile.TarInfo(name=name)
            info.type = ttype
            if linkname:
                info.linkname = linkname
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                info.size = 0
                tar.addfile(info)
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r:gz")


class SafeTarExtractTests(unittest.TestCase):
    def test_normal_extraction_with_data_filter(self):
        with (
            _build_tar([("unienv-ai-main/src/unienv.py", b"print('ok')\n", tarfile.REGTYPE, "")]) as tar,
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = pathlib.Path(tmp)
            u._safe_extract_tar(tar, dest)
            self.assertEqual((dest / "unienv-ai-main/src/unienv.py").read_text(), "print('ok')\n")

    def test_fallback_extracts_safe_members_and_internal_symlink(self):
        entries = [
            ("unienv-ai-main/bin/unienv", b"#!/bin/sh\n", tarfile.REGTYPE, ""),
            ("unienv-ai-main/bin/ue", None, tarfile.SYMTYPE, "unienv"),
        ]
        with (
            _build_tar(entries) as tar,
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tarfile, "data_filter", None),
        ):
            delattr(tarfile, "data_filter")
            dest = pathlib.Path(tmp)
            u._safe_extract_tar(tar, dest)
            self.assertEqual((dest / "unienv-ai-main/bin/unienv").read_text(), "#!/bin/sh\n")
            self.assertTrue((dest / "unienv-ai-main/bin/ue").is_symlink())

    def test_fallback_rejects_parent_traversal(self):
        with (
            _build_tar([("../evil.txt", b"pwn", tarfile.REGTYPE, "")]) as tar,
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tarfile, "data_filter", None),
        ):
            delattr(tarfile, "data_filter")
            with self.assertRaises(ValueError):
                u._safe_extract_tar(tar, pathlib.Path(tmp))

    def test_fallback_rejects_absolute_path(self):
        with (
            _build_tar([("/abs/path.txt", b"pwn", tarfile.REGTYPE, "")]) as tar,
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tarfile, "data_filter", None),
        ):
            delattr(tarfile, "data_filter")
            with self.assertRaises(ValueError):
                u._safe_extract_tar(tar, pathlib.Path(tmp))

    def test_fallback_rejects_outside_symlink(self):
        with (
            _build_tar([("unienv-ai-main/escape", None, tarfile.SYMTYPE, "../../../etc/passwd")]) as tar,
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tarfile, "data_filter", None),
        ):
            delattr(tarfile, "data_filter")
            with self.assertRaises(ValueError):
                u._safe_extract_tar(tar, pathlib.Path(tmp))

    def test_fallback_rejects_fifo_and_devices(self):
        with (
            _build_tar([("unienv-ai-main/fifo", None, tarfile.FIFOTYPE, "")]) as tar,
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tarfile, "data_filter", None),
        ):
            delattr(tarfile, "data_filter")
            with self.assertRaises(ValueError):
                u._safe_extract_tar(tar, pathlib.Path(tmp))


if __name__ == "__main__":
    unittest.main()
