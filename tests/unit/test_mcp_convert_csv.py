"""Unit tests for multi-sheet spreadsheet CSV conversion in unienv_mcp."""

import csv
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

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
            self.assertEqual(fmt_arg, "csv:Text - txt - csv (StarCalc):44,34,UTF8,1,,0,false,true,true,false,false,-1")
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

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed")
    def test_real_csv_export_preserves_formatted_percentage(self):
        for sheet_count in (1, 2):
            with self.subTest(sheet_count=sheet_count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = root / "formatted.ods"
                sheets = "".join(
                    f'<table:table table:name="Sheet{i}"><table:table-row>'
                    '<table:table-cell table:style-name="percent" office:value-type="percentage" '
                    'office:value="0.125"><text:p>12.5%</text:p></table:table-cell>'
                    "</table:table-row></table:table>"
                    for i in range(1, sheet_count + 1)
                )
                content = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<office:document-content office:version="1.2" '
                    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
                    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
                    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
                    'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0">'
                    '<office:automatic-styles><number:percentage-style style:name="percentage">'
                    '<number:number number:decimal-places="1" number:min-integer-digits="1"/>'
                    "<number:text>%</number:text></number:percentage-style>"
                    '<style:style style:name="percent" style:family="table-cell" '
                    'style:data-style-name="percentage"/></office:automatic-styles>'
                    f"<office:body><office:spreadsheet>{sheets}</office:spreadsheet>"
                    "</office:body></office:document-content>"
                )
                with ZipFile(src, "w") as archive:
                    archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
                    archive.writestr("content.xml", content)
                    archive.writestr(
                        "META-INF/manifest.xml",
                        '<manifest:manifest manifest:version="1.2" '
                        'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                        '<manifest:file-entry manifest:full-path="/" '
                        'manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
                        '<manifest:file-entry manifest:full-path="content.xml" '
                        'manifest:media-type="text/xml"/></manifest:manifest>',
                    )

                def real_run(cmd, *, cwd, timeout, env=None):
                    proc = subprocess.run(
                        [
                            shutil.which("soffice"),
                            "--headless",
                            f"-env:UserInstallation={(root / 'profile').as_uri()}",
                            *cmd[1:],
                        ],
                        cwd=cwd,
                        timeout=timeout,
                        capture_output=True,
                        text=True,
                        env=env,
                        check=False,
                    )
                    return proc.returncode, proc.stdout, proc.stderr, 0.0

                with patch.object(mcp, "run", side_effect=real_run):
                    result = mcp.t_convert_document({"input_path": str(src), "output_format": "csv"})

                outputs = sorted(root.glob("*.csv"))
                self.assertEqual(len(outputs), sheet_count)
                for output in outputs:
                    self.assertIn(str(output), result)
                    with output.open(newline="", encoding="utf-8") as stream:
                        self.assertEqual(list(csv.reader(stream)), [["12.5%"]])


if __name__ == "__main__":
    unittest.main()
