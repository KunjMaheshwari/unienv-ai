import base64
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP_PATH = ROOT / "src" / "unienv_mcp.py"
spec = importlib.util.spec_from_file_location("unienv_mcp", MCP_PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class McpImageContentTests(unittest.TestCase):
    def test_convert_document_pdf_to_png_returns_image_blocks_capped_at_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            pdf = work / "doc.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")

            def fake_run(cmd, *, cwd, timeout, env=None):
                prefix = pathlib.Path(cmd[-1])
                for i in range(1, 6):
                    (prefix.parent / f"{prefix.name}-{i}.png").write_bytes(TINY_PNG)
                return 0, "", "", 0.1

            with patch.object(mcp, "WORKDIR", work), patch.object(mcp, "run", side_effect=fake_run):
                reply = mcp.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "convert_document",
                            "arguments": {"input_path": str(pdf), "output_format": "png"},
                        },
                    }
                )
            content = reply["result"]["content"]
            self.assertFalse(reply["result"]["isError"])
            self.assertEqual(content[0]["type"], "text")
            self.assertIn("Rendered 5 page(s)", content[0]["text"])
            images = [b for b in content if b["type"] == "image"]
            self.assertEqual(len(images), 4)
            self.assertEqual(images[0]["mimeType"], "image/png")
            self.assertEqual(base64.b64decode(images[0]["data"]), TINY_PNG)

            # With include_images=False, only the text block is returned
            with patch.object(mcp, "WORKDIR", work), patch.object(mcp, "run", side_effect=fake_run):
                reply_no_img = mcp.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "convert_document",
                            "arguments": {"input_path": str(pdf), "output_format": "png", "include_images": False},
                        },
                    }
                )
            self.assertEqual(len(reply_no_img["result"]["content"]), 1)
            self.assertEqual(reply_no_img["result"]["content"][0]["type"], "text")

    def test_run_python_attaches_new_images_under_size_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            ue_py = bin_dir / "ue-py"
            ue_py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
            ue_py.chmod(0o755)
            code = (
                "import pathlib\n"
                f"pathlib.Path('chart.png').write_bytes({TINY_PNG!r})\n"
                "pathlib.Path('huge.png').write_bytes(b'x' * (600 * 1024))\n"
                "print('done')\n"
            )
            with patch.object(mcp, "BIN", bin_dir), patch.object(mcp, "WORKDIR", work):
                reply = mcp.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "run_python", "arguments": {"code": code, "cwd": str(work)}},
                    }
                )
            content = reply["result"]["content"]
            self.assertFalse(reply["result"]["isError"])
            self.assertEqual(content[0]["type"], "text")
            self.assertIn("chart.png", content[0]["text"])
            self.assertIn("huge.png", content[0]["text"])
            images = [b for b in content if b["type"] == "image"]
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0]["mimeType"], "image/png")
            self.assertEqual(base64.b64decode(images[0]["data"]), TINY_PNG)

    def test_read_document_image_with_include_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            img = work / "page.png"
            img.write_bytes(TINY_PNG)
            with (
                patch.object(mcp, "WORKDIR", work),
                patch.object(mcp, "which", return_value="/usr/local/bin/tesseract"),
                patch.object(mcp, "run", return_value=(0, "Hello OCR\n", "", 0.1)),
            ):
                res = mcp.t_read_document({"path": str(img), "include_image": True})
            self.assertIsInstance(res, list)
            self.assertEqual(res[0]["type"], "text")
            self.assertIn("Hello OCR", res[0]["text"])
            self.assertEqual(res[1]["type"], "image")
            self.assertEqual(res[1]["mimeType"], "image/png")


if __name__ == "__main__":
    unittest.main()
