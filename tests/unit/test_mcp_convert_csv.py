"""Unit tests for multi-sheet spreadsheet CSV conversion in unienv_mcp."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("unienv_mcp", ROOT / "src" / "unienv_mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class ConvertCsvAllSheetsTests(unittest.TestCase):
    def test_xlsx_to_csv_uses_all_sheets_filter_and_moves_every_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "book.xlsx"
            src.write_bytes(b"fake-xlsx")
            # Pre-create one file to prove free_name avoids overwriting
            existing = root / "book-Q1.csv"
            existing.write_text("existing\n")

            seen_cmds = []

            def fake_run(cmd, *, cwd, timeout, env=None):
                seen_cmds.append(cmd)
                outdir = Path(cmd[cmd.index("--outdir") + 1])
                (outdir / "book-Q1.csv").write_text("a,b\n1,2\n")
                (outdir / "book-Q2.csv").write_text("c,d\n3,4\n")
                return 0, "", "", 0.1

            with patch.object(mcp, "run", side_effect=fake_run):
                result = mcp.t_convert_document({"input_path": str(src), "output_format": "csv"})

            self.assertEqual(len(seen_cmds), 1)
            fmt_arg = seen_cmds[0][seen_cmds[0].index("--convert-to") + 1]
            self.assertEqual(fmt_arg, mcp._CSV_ALL_SHEETS_FILTER)
            self.assertIn("Converted to 2 files:", result)
            self.assertIn(str(root / "book-Q1-1.csv"), result)
            self.assertIn(str(root / "book-Q2.csv"), result)
            self.assertEqual(existing.read_text(), "existing\n")
            self.assertEqual((root / "book-Q1-1.csv").read_text(), "a,b\n1,2\n")
            self.assertEqual((root / "book-Q2.csv").read_text(), "c,d\n3,4\n")

    def test_single_sheet_csv_returns_single_converted_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "single.ods"
            src.write_bytes(b"fake-ods")

            def fake_run(cmd, *, cwd, timeout, env=None):
                outdir = Path(cmd[cmd.index("--outdir") + 1])
                (outdir / "single.csv").write_text("x\n1\n")
                return 0, "", "", 0.1

            with patch.object(mcp, "run", side_effect=fake_run):
                result = mcp.t_convert_document({"input_path": str(src), "output_format": "csv"})

            self.assertEqual(result, f"Converted to {root / 'single.csv'}")
            self.assertEqual((root / "single.csv").read_text(), "x\n1\n")


if __name__ == "__main__":
    unittest.main()
