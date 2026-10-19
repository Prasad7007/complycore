"""
Deterministic visual triage: score each ``<img>`` / ``<table>`` in Docling metadata HTML.

Downstream vision selection (recall for raster tables) is implemented in
``apis.services.ai.processing.visual_document`` — when HTML has no ``<table>`` tags,
that layer picks the **largest on-disk images** in addition to these scores.

Input is metadata HTML (same shape as ``document_versions.extracted_text``).
"""

from __future__ import annotations

import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from apis.services.ai.processing.chunking import Chunker


FINANCE_KEYWORDS = {
    "return", "returns", "performance", "benchmark", "outperform", "alpha",
    "volatility", "risk", "drawdown", "yield", "cagr", "forecast", "projection",
    "annualized", "sharpe", "index", "fund", "portfolio", "equity", "fixed income",
}
CHART_CUES = {
    "chart", "graph", "line", "bar", "histogram", "axis", "x-axis", "y-axis",
    "legend", "table", "plot", "trend", "since inception",
}
DISCLAIMER_CUES = {
    "past performance", "not guaranteed", "actual results may vary", "forward-looking",
    "subject to market risks", "source:", "for illustrative purposes", "no guarantee",
}
DECORATIVE_CUES = {
    "team", "people", "portrait", "office", "lifestyle", "hero image", "cover photo",
}


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _numeric_signal_count(text: str) -> int:
    if not text:
        return 0
    percent_hits = len(re.findall(r"\d+(?:\.\d+)?\s*%", text))
    year_hits = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    currency_hits = len(re.findall(r"[$€£]\s*\d", text))
    return percent_hits + year_hits + currency_hits


def _keyword_hits(text: str, keywords: set[str]) -> int:
    if not text:
        return 0
    text_l = text.lower()
    return sum(1 for kw in keywords if kw in text_l)


def _get_nearby_context(node, max_chars: int = 800) -> str:
    figure = node.find_parent("figure")
    parts: list[str] = []

    if figure is not None:
        fig_text = _compact_text(figure.get_text(" ", strip=True))
        if fig_text:
            parts.append(fig_text)

        prev_sib = figure.find_previous_sibling(["p", "h1", "h2", "h3", "li", "div"])
        if prev_sib is not None:
            prev_text = _compact_text(prev_sib.get_text(" ", strip=True))
            if prev_text:
                parts.append(prev_text)

        next_sib = figure.find_next_sibling(["p", "h1", "h2", "h3", "li", "div"])
        if next_sib is not None:
            next_text = _compact_text(next_sib.get_text(" ", strip=True))
            if next_text:
                parts.append(next_text)

    alt_text = _compact_text(node.get("alt", ""))
    title_text = _compact_text(node.get("title", ""))
    if alt_text:
        parts.append(alt_text)
    if title_text:
        parts.append(title_text)

    merged = _compact_text(" | ".join(parts))
    return merged[:max_chars]


def _score_visual(
    source_ref: str,
    item_kind: str,
    important_flag: bool,
    nearby_context: str,
    probable_chart_like: bool,
    has_table_structure: bool,
) -> tuple[int, list[str], dict[str, Any]]:
    context_l = nearby_context.lower()
    finance_hits = _keyword_hits(context_l, FINANCE_KEYWORDS)
    chart_hits = _keyword_hits(context_l, CHART_CUES)
    disclaimer_hits = _keyword_hits(context_l, DISCLAIMER_CUES)
    decorative_hits = _keyword_hits(context_l, DECORATIVE_CUES)
    numeric_hits = _numeric_signal_count(nearby_context)

    score = 0
    reasons: list[str] = []

    if important_flag:
        score += 2
        reasons.append("docling_marked_important")

    if item_kind == "table":
        score += 4
        reasons.append("html_table_detected")

    if probable_chart_like:
        score += 3
        reasons.append("source_looks_like_chart")

    if has_table_structure:
        score += 3
        reasons.append("table_structure_detected")

    if chart_hits > 0:
        score += 3
        reasons.append(f"chart_cues:{chart_hits}")

    if finance_hits > 0:
        score += 2
        reasons.append(f"finance_cues:{finance_hits}")

    if numeric_hits > 0:
        score += 2
        reasons.append(f"numeric_signals:{numeric_hits}")

    if disclaimer_hits > 0:
        score += 2
        reasons.append(f"disclaimer_cues:{disclaimer_hits}")

    if decorative_hits > 0 and chart_hits == 0 and finance_hits == 0 and numeric_hits == 0:
        score -= 3
        reasons.append(f"decorative_cues:{decorative_hits}")

    diagnostics = {
        "item_kind": item_kind,
        "source_ref": source_ref,
        "important_flag": important_flag,
        "probable_chart_like": probable_chart_like,
        "has_table_structure": has_table_structure,
        "chart_hits": chart_hits,
        "finance_hits": finance_hits,
        "numeric_hits": numeric_hits,
        "disclaimer_hits": disclaimer_hits,
        "decorative_hits": decorative_hits,
    }
    return score, reasons, diagnostics


def _looks_like_chart_reference(source_ref: str) -> bool:
    src_l = (source_ref or "").lower()
    hints = ("chart", "graph", "plot", "table", "figure", "legend", "benchmark")
    return any(h in src_l for h in hints)


def _table_structure_signals(table_tag) -> bool:
    rows = table_tag.find_all("tr")
    headers = table_tag.find_all("th")
    cells = table_tag.find_all("td")
    return len(rows) >= 2 and (len(headers) > 0 or len(cells) >= 4)


def _item_label(item_kind: str, probable_chart_like: bool, has_table_structure: bool, score: int) -> str:
    if item_kind == "table" or has_table_structure:
        return "table"
    if probable_chart_like or score >= 5:
        return "chart"
    return "image"


def _looks_like_table_image_context(context: str) -> bool:
    """
    Heuristic for table-as-image cases where HTML has only <img> (no <table> tag).
    We treat dense numeric + tabular wording as a strong analyze signal.
    """
    if not context:
        return False
    ctx = context.lower()
    table_terms = (
        "table", "tabular", "week", "mtd", "qtd", "ytd", "1y", "benchmark",
        "index", "composite", "nasdaq", "s&p", "column", "row",
    )
    term_hits = sum(1 for t in table_terms if t in ctx)
    numeric_hits = _numeric_signal_count(context)
    return term_hits >= 2 and numeric_hits >= 2


def _image_asset_fingerprint(source_ref: str) -> str | None:
    """Docling artifact names look like image_000004_<hex>.png — group duplicates by <hex>."""
    if not source_ref:
        return None
    stem = Path(source_ref.replace("\\", "/")).stem
    m = re.match(r"^image_\d+_(.+)$", stem, re.IGNORECASE)
    if m and len(m.group(1)) >= 16:
        return m.group(1).lower()
    return None


def _dedupe_image_items_by_asset(
    analyzed: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Same Docling raster (image_00000_<hex>.png) referenced twice: keep one analyze
    (highest score); demote other analyze rows to skip with duplicate_image_asset.
    """
    all_items = analyzed + skipped
    by_fp: dict[str, list[dict[str, Any]]] = {}
    for item in all_items:
        if item.get("item_type") != "image":
            continue
        fp = _image_asset_fingerprint(item.get("source_ref") or "")
        if not fp:
            continue
        by_fp.setdefault(fp, []).append(item)

    for _fp, group in by_fp.items():
        if len(group) < 2:
            continue
        analyzers = [g for g in group if g.get("decision") == "analyze"]
        if len(analyzers) <= 1:
            continue
        analyzers.sort(key=lambda g: (-(g.get("score") or 0), str(g.get("image_id", ""))))
        winner = analyzers[0]
        for g in analyzers[1:]:
            g["decision"] = "skip"
            reasons = list(g.get("reasons") or [])
            reasons.append("duplicate_image_asset")
            g["reasons"] = reasons
            g["dedupe_kept_image_id"] = winner.get("image_id")

    new_analyzed = [x for x in all_items if x.get("decision") == "analyze"]
    new_skipped = [x for x in all_items if x.get("decision") == "skip"]
    return new_analyzed, new_skipped


def triage_html_metadata(html_text: str) -> dict[str, Any]:
    """
    Classify embedded visuals in Docling **metadata HTML** (not raw PDF bytes).

    "Metadata HTML" is the file produced by ``Parsing.add_metadata_to_file``: it includes
    layout-derived tags (e.g. ``important`` on figures, font/pos spans on text) that the
    chunker and this triage use. ``triage`` means: score each image/table and label it
    **analyze** (send to downstream vision / compliance) vs **skip** (decorative / duplicate).

    No PDF I/O here — pass the same ``extracted_text`` string the analysis pipeline already uses.

    Returns: ``summary``, ``analyze_items``, ``skipped_items`` (same shape as the root POC).
    """
    soup = BeautifulSoup(html_text, "html.parser")

    chunker = Chunker()
    chunks = chunker.chunk_html_with_media(html_text)
    chunk_image_count = sum(
        1 for ch in chunks for m in ch.get("media", []) if m.get("type") == "image"
    )
    chunk_table_count = sum(
        1 for ch in chunks for m in ch.get("media", []) if m.get("type") == "table"
    )

    analyzed_items: list[dict[str, Any]] = []
    skipped_items: list[dict[str, Any]] = []

    for idx, img in enumerate(soup.find_all("img"), start=1):
        source_ref = img.get("src", "")
        important_flag = str(img.get("important", "")).lower() == "true"
        nearby_context = _get_nearby_context(img)
        probable_chart_like = _looks_like_chart_reference(source_ref)

        score, reasons, diagnostics = _score_visual(
            source_ref=source_ref,
            item_kind="image",
            important_flag=important_flag,
            nearby_context=nearby_context,
            probable_chart_like=probable_chart_like,
            has_table_structure=False,
        )

        finance_or_chart_signal = (
            diagnostics["chart_hits"] > 0
            or diagnostics["finance_hits"] > 0
            or diagnostics["disclaimer_hits"] > 0
            or probable_chart_like
        )
        table_image_signal = _looks_like_table_image_context(nearby_context)

        if score >= 4:
            decision = "analyze"
        elif score >= 2 and finance_or_chart_signal:
            decision = "analyze"
        elif table_image_signal:
            decision = "analyze"
            reasons.append("table_image_context_signal")
        else:
            # Covers score <= 0, score in [1,3] with no finance/chart signal, etc.
            decision = "skip"

        label = _item_label("image", probable_chart_like, False, score)

        item_payload = {
            "image_id": f"img_{idx}",
            "item_type": "image",
            "classification": label,
            "source_ref": source_ref,
            "decision": decision,
            "score": score,
            "reasons": reasons,
            "nearby_context_excerpt": nearby_context[:300],
            "signals": diagnostics,
            "table_image_signal": table_image_signal,
        }
        if decision == "analyze":
            analyzed_items.append(item_payload)
        else:
            skipped_items.append(item_payload)

    for idx, table in enumerate(soup.find_all("table"), start=1):
        source_ref = f"table_{idx}"
        nearby_context = _get_nearby_context(table)
        table_text = _compact_text(table.get_text(" ", strip=True))
        merged_context = _compact_text(f"{nearby_context} | {table_text}")
        has_table_structure = _table_structure_signals(table)
        probable_chart_like = _looks_like_chart_reference(merged_context)

        score, reasons, diagnostics = _score_visual(
            source_ref=source_ref,
            item_kind="table",
            important_flag=True,
            nearby_context=merged_context,
            probable_chart_like=probable_chart_like,
            has_table_structure=has_table_structure,
        )

        decision = "analyze" if score >= 2 else "skip"
        label = _item_label("table", probable_chart_like, has_table_structure, score)

        item_payload = {
            "image_id": f"table_{idx}",
            "item_type": "table",
            "classification": label,
            "source_ref": source_ref,
            "decision": decision,
            "score": score,
            "reasons": reasons,
            "nearby_context_excerpt": merged_context[:300],
            "signals": diagnostics,
        }
        if decision == "analyze":
            analyzed_items.append(item_payload)
        else:
            skipped_items.append(item_payload)

    analyzed_items, skipped_items = _dedupe_image_items_by_asset(analyzed_items, skipped_items)

    all_items = analyzed_items + skipped_items
    decision_counts = Counter(r["decision"] for r in all_items)
    class_counts = Counter(r["classification"] for r in all_items)
    type_counts = Counter(r["item_type"] for r in all_items)
    analyzed_type_counts = Counter(r["item_type"] for r in analyzed_items)
    skipped_type_counts = Counter(r["item_type"] for r in skipped_items)
    return {
        "summary": {
            "total_visual_items_detected": len(all_items),
            "total_images_found_in_html": type_counts.get("image", 0),
            "total_tables_found_in_html": type_counts.get("table", 0),
            "chunk_image_blocks": chunk_image_count,
            "chunk_table_blocks": chunk_table_count,
            "to_analyze": decision_counts.get("analyze", 0),
            "to_skip": decision_counts.get("skip", 0),
            "analyze_images": analyzed_type_counts.get("image", 0),
            "analyze_tables": analyzed_type_counts.get("table", 0),
            "skip_images": skipped_type_counts.get("image", 0),
            "skip_tables": skipped_type_counts.get("table", 0),
            "classified_as_chart": class_counts.get("chart", 0),
            "classified_as_table": class_counts.get("table", 0),
            "classified_as_image": class_counts.get("image", 0),
        },
        "analyze_items": analyzed_items,
        "skipped_items": skipped_items,
    }


def triage_pdf_to_report(pdf_path: Path, *, html_file_name: str = "triage_output.html") -> dict[str, Any]:
    """
    Parse PDF with Docling (temp dir), build metadata HTML, run triage_html_metadata.

    Adds pdf_path to the returned dict for CLI/POC convenience.

    Note: ``Parsing`` is imported here rather than at module level to avoid a circular
    import between the triage module and the parsing pipeline.
    """
    # Parsing imported locally to avoid circular import with parsing pipeline.
    from apis.services.ai.processing.parsing import Parsing  # noqa: PLC0415

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmpdir_p = Path(tmpdir)
        parser = Parsing(pdf_path)
        html_path = parser.add_metadata_to_file(tmpdir_p, html_file_name)
        html_text = html_path.read_text(encoding="utf-8")

    inner = triage_html_metadata(html_text)
    return {"pdf_path": str(pdf_path), **inner}