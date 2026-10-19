"""
Vision extraction from Docling metadata HTML and on-disk image artifacts.

- ``build_vision_candidates`` — deterministic candidate ordering + caps (for tests / debug).
- ``extract_visual_extractions_from_html_workspace`` — triage + vision merge (call before
  deleting the temp dir that contains ``html_path``).
- ``extract_visual_extractions_from_pdf_bytes`` — parse PDF once, then workspace extract.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from apis.services.ai.core import config
from apis.services.ai.compliance_engine.extractor import merge_extraction_results
from apis.services.ai.compliance_engine.models import ExtractionResult
from apis.services.ai.compliance_engine.visual_extract import extract_claims_from_chart_image
from apis.services.ai.processing.media_triage import triage_html_metadata
from apis.services.ai.processing.parsing import Parsing

logger = logging.getLogger(__name__)


def _guess_mime_type(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".webp":
        return "image/webp"
    if suf == ".gif":
        return "image/gif"
    return "image/png"


def _resolve_image_path(html_path: Path, source_ref: str) -> Path | None:
    if not source_ref:
        return None
    p = Path(source_ref.replace("\\", "/"))
    if p.is_absolute() and p.exists():
        return p
    cand = html_path.parent / source_ref
    if cand.exists():
        return cand
    name = p.name
    if name:
        cand2 = html_path.parent / name
        if cand2.exists():
            return cand2
    return None


def _item_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("source_ref") or ""), str(item.get("image_id") or ""))


def _safe_stat_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _all_html_image_items(tri: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bucket in (tri.get("analyze_items") or [], tri.get("skipped_items") or []):
        for it in bucket:
            if it.get("item_type") != "image":
                continue
            k = _item_key(it)
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
    return out


def build_vision_candidates(
    html_path: Path,
    *,
    tri: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Build ordered image items to send to vision, with per-document policy:

    - **HTML has ≥1 `<table>`:** union of (a) ``table_image_signal`` images and
      (b) triage ``decision == analyze`` images. Caps: ``MAX_VISION_TABLE_IMAGES`` for
      signal rows, ``MAX_VISION_IMAGES`` for regular analyze rows.

    - **HTML has zero `<table>`:** recall-first — take the **largest K** on-disk images
      (by byte size), after dropping assets smaller than ``MIN_VISION_IMAGE_BYTES``
      (unless that would empty the pool). Budget per doc:
      ``max(MAX_VISION_IMAGES, MAX_VISION_NO_TABLE_LARGEST_K)``.

    Each returned item is the original triage dict (mutated only with optional debug keys
    ``_vision_inclusion`` / ``_vision_bytes`` for tracing).
    """
    if not html_path.is_file():
        return [], {"error": "html_missing", "html_path": str(html_path)}

    tri = tri if tri is not None else triage_html_metadata(html_path.read_text(encoding="utf-8"))
    summary = tri.get("summary") or {}
    total_tables = int(summary.get("total_tables_found_in_html") or 0)

    min_bytes = max(0, config.MIN_VISION_IMAGE_BYTES)
    k_largest = max(1, config.MAX_VISION_NO_TABLE_LARGEST_K)
    max_regular = max(0, config.MAX_VISION_IMAGES)
    max_signal = max(1, config.MAX_VISION_TABLE_IMAGES)

    meta: dict[str, Any] = {
        "total_tables_found_in_html": total_tables,
        "mode": "scored_with_html_tables" if total_tables > 0 else "largest_k_no_html_table",
    }

    if total_tables > 0:
        return _candidates_when_html_tables(tri, max_regular, max_signal, meta)

    return _candidates_largest_k_no_html_table(html_path, tri, min_bytes, k_largest, max_regular, meta)


def _candidates_when_html_tables(
    tri: dict[str, Any],
    max_regular: int,
    max_signal: int,
    meta: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Triage-forward selection when real HTML tables exist."""
    seen: set[tuple[str, str]] = set()
    ordered: list[dict[str, Any]] = []

    def _push(it: dict[str, Any], *, reason: str) -> None:
        k = _item_key(it)
        if k in seen:
            return
        seen.add(k)
        it = dict(it)
        it["_vision_inclusion"] = reason
        ordered.append(it)

    for it in (tri.get("analyze_items") or []) + (tri.get("skipped_items") or []):
        if it.get("item_type") != "image":
            continue
        if it.get("table_image_signal"):
            _push(it, reason="table_image_signal")

    for it in tri.get("analyze_items") or []:
        if it.get("item_type") != "image" or it.get("decision") != "analyze":
            continue
        _push(it, reason="triage_analyze")

    # Apply caps while preserving order: signals first, then regular.
    out: list[dict[str, Any]] = []
    used_sig = 0
    used_reg = 0
    for it in ordered:
        is_sig = bool(it.get("table_image_signal"))
        if is_sig:
            if used_sig >= max_signal:
                continue
            used_sig += 1
        else:
            if used_reg >= max_regular:
                continue
            used_reg += 1
        out.append(it)

    meta["cap_signal"] = max_signal
    meta["cap_regular"] = max_regular
    meta["selected"] = len(out)
    meta["used_signal"] = used_sig
    meta["used_regular"] = used_reg
    return out, meta


def _candidates_largest_k_no_html_table(
    html_path: Path,
    tri: dict[str, Any],
    min_bytes: int,
    k_largest: int,
    max_regular_floor: int,
    meta: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    No HTML <table>: recall-first — ``table_image_signal`` rows first (even if small),
    then fill the budget with the largest on-disk images (charts/tables tend to be large).
    """
    budget = max(max_regular_floor, k_largest)
    items = _all_html_image_items(tri)

    sized: list[tuple[int, dict[str, Any], bool]] = []
    for it in items:
        src = it.get("source_ref") or ""
        path = _resolve_image_path(html_path, str(src))
        if not path or not path.is_file():
            continue
        sz = _safe_stat_size(path)
        if sz is None:
            continue
        row = dict(it)
        row["_vision_bytes"] = sz
        row["_vision_resolved"] = str(path)
        sized.append((sz, row, bool(it.get("table_image_signal"))))

    if not sized:
        meta["selected"] = 0
        meta["budget"] = budget
        return [], meta

    # Size floor for "largest K" filler only — table_image_signal bypasses the floor.
    filler_pool = [(sz, r) for sz, r, sig in sized if not sig and sz >= min_bytes]
    if not filler_pool:
        filler_pool = [(sz, r) for sz, r, _sig in sized]

    filler_pool.sort(key=lambda x: (-x[0], x[1].get("image_id") or ""))

    signal_rows = [(sz, r) for sz, r, sig in sized if sig]
    signal_rows.sort(key=lambda x: (-x[0], x[1].get("image_id") or ""))

    seen: set[tuple[str, str]] = set()
    chosen: list[dict[str, Any]] = []

    def _take(sz: int, row: dict[str, Any], reason: str) -> None:
        if len(chosen) >= budget:
            return
        k = _item_key(row)
        if k in seen:
            return
        seen.add(k)
        row["_vision_inclusion"] = reason
        chosen.append(row)

    for sz, row in signal_rows:
        _take(sz, row, "table_image_signal_no_html_table")

    for sz, row in filler_pool:
        _take(sz, row, "largest_k_no_html_table")

    meta["budget"] = budget
    meta["min_bytes_filter"] = min_bytes
    meta["pool_size"] = len(sized)
    meta["selected"] = len(chosen)
    meta["signal_picks"] = sum(1 for r in chosen if r.get("_vision_inclusion") == "table_image_signal_no_html_table")
    meta["largest_bytes_preview"] = [sz for sz, _ in filler_pool[: min(5, len(filler_pool))]]
    return chosen, meta


def extract_visual_extractions_from_html_workspace(
    html_path: Path,
    llm_client: Any,
) -> ExtractionResult | None:
    """
    Run vision on candidates from ``build_vision_candidates`` and merge ``ExtractionResult``s.
    """
    if not html_path.is_file() or not hasattr(llm_client, "invoke_with_image"):
        return None

    candidates, meta = build_vision_candidates(html_path)
    logger.info(
        "visual_extract_start mode=%s selected=%s tables_in_html=%s",
        meta.get("mode"),
        meta.get("selected"),
        meta.get("total_tables_found_in_html"),
    )

    merged: ExtractionResult | None = None
    for item in candidates:
        src = item.get("source_ref") or ""
        img_path = _resolve_image_path(html_path, str(src))
        if not img_path or not img_path.is_file():
            logger.debug("visual_extract_skip_missing_path src=%s", str(src)[:80])
            continue

        caption = str(item.get("nearby_context_excerpt") or "")[:1200]
        try:
            data = img_path.read_bytes()
        except OSError as e:
            logger.warning("visual_extract_read_failed path=%s err=%s", img_path, e)
            continue

        ext = extract_claims_from_chart_image(
            data,
            llm_client,
            caption=caption,
            mime_type=_guess_mime_type(img_path),
        )
        if ext is None:
            continue
        merged = merge_extraction_results(merged, ext)
        n_claims = len(ext.claims or [])
        logger.info(
            "visual_extract_ok image_id=%s inclusion=%s claims=%s bytes=%s",
            item.get("image_id"),
            item.get("_vision_inclusion"),
            n_claims,
            item.get("_vision_bytes"),
        )

    return merged


def extract_visual_extractions_from_pdf_bytes(
    pdf_bytes: bytes,
    llm_client: Any,
) -> ExtractionResult | None:
    """One Docling parse in a temp dir, then vision from that workspace."""
    if not pdf_bytes or not hasattr(llm_client, "invoke_with_image"):
        return None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmpdir_p = Path(tmpdir)
        logger.debug("VISUAL_PARSE_TEMP_CREATED path=%s", tmpdir)
        pdf_path = tmpdir_p / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)
        parser = Parsing(pdf_path)
        out_dir = tmpdir_p / "out"
        html_path = parser.add_metadata_to_file(out_dir, "output.html")
        merged = extract_visual_extractions_from_html_workspace(html_path, llm_client)

    logger.debug("VISUAL_PARSE_TEMP_REMOVED path=%s (TemporaryDirectory cleanup)", tmpdir)
    return merged
