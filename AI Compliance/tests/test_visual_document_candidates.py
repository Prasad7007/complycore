"""
Unit tests for ``build_vision_candidates`` (largest-K when no HTML tables).

Run from ``AI Compliance`` root::

    PYTHONPATH=. python -m unittest tests.test_visual_document_candidates -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Repo layout: tests live under ``AI Compliance/tests``; imports are ``apis.*``.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apis.services.ai.processing.media_triage import triage_html_metadata
from apis.services.ai.processing.visual_document import build_vision_candidates


class BuildVisionCandidatesTest(unittest.TestCase):
    def test_no_html_table_orders_by_file_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            big = tdir / "big.png"
            small = tdir / "small.png"
            big.write_bytes(b"x" * 8000)
            small.write_bytes(b"y" * 500)
            html = tdir / "out.html"
            html.write_text(
                '<html><body>'
                f'<img src="{small.name}" important="false" />'
                f'<img src="{big.name}" important="false" />'
                "</body></html>",
                encoding="utf-8",
            )
            tri = triage_html_metadata(html.read_text(encoding="utf-8"))
            cands, meta = build_vision_candidates(html, tri=tri)

            self.assertEqual(meta.get("total_tables_found_in_html"), 0)
            self.assertEqual(meta.get("mode"), "largest_k_no_html_table")
            self.assertGreaterEqual(len(cands), 1)
            # Big file should rank before small in candidate list
            self.assertIn("big.png", cands[0].get("source_ref", ""))

    def test_table_image_signal_first_when_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            big = tdir / "big.png"
            small = tdir / "small_signal.png"
            big.write_bytes(b"x" * 8000)
            small.write_bytes(b"y" * 400)
            html = tdir / "out.html"
            # Dense numeric + table-ish context triggers ``table_image_signal`` on small image.
            html.write_text(
                '<html><body><figure>'
                f'<img src="{small.name}" important="false" />'
                "<figcaption>QTD YTD 1Y benchmark returns 12.3% 8.1% table composite index</figcaption>"
                "</figure>"
                f'<img src="{big.name}" important="false" />'
                "</body></html>",
                encoding="utf-8",
            )
            tri = triage_html_metadata(html.read_text(encoding="utf-8"))
            cands, meta = build_vision_candidates(html, tri=tri)

            self.assertEqual(meta.get("total_tables_found_in_html"), 0)
            self.assertGreaterEqual(len(cands), 1)
            first = cands[0].get("source_ref", "")
            self.assertIn("small_signal", first)


if __name__ == "__main__":
    unittest.main()
