"""
Highlighting utilities for PDF, DOCX, and PPTX files.
Highlights flagged phrases from the compliance pipeline in the original document.
"""
from pathlib import Path
from typing import List
from copy import deepcopy
import re
import unicodedata

import fitz  # PyMuPDF


# ── PDF ───────────────────────────────────────────────────────────────────────

def _robust_page_search(page, text: str) -> list:
    # 1. Exact match
    rects = page.search_for(text)
    if rects:
        return rects

    # 2. FIX #1: Try BOTH left and right curly quotes (original only tried right)
    # Right curly quotes (closing)
    alternate_right = (text.replace("'", "\u2019").replace("'", "\u2018")
                       .replace('"', "\u201d").replace('"', "\u201c"))
    if alternate_right != text:
        rects = page.search_for(alternate_right)
        if rects:
            return rects

    # Left curly quotes (opening) — fixes chunks starting with "The ... 
    alternate_left = (text.replace('"', "\u201c").replace('"', "\u201d")
                      .replace("'", "\u2018").replace("'", "\u2019"))
    if alternate_left != text and alternate_left != alternate_right:
        rects = page.search_for(alternate_left)
        if rects:
            return rects

    # 3. Normalize LLM dashes to standard hyphens
    norm_dashes = re.sub(r'[—–−]', '-', text)
    if norm_dashes != text:
        rects = page.search_for(norm_dashes)
        if rects:
            return rects

    # 4. Try En dash
    en_dash = re.sub(r'[-—]', '–', text)
    if en_dash != text:
        rects = page.search_for(en_dash)
        if rects:
            return rects

    # 5. Try Em dash
    em_dash = re.sub(r'[-–]', '—', text)
    if em_dash != text:
        rects = page.search_for(em_dash)
        if rects:
            return rects

    return []


_BOUNDARY_CHARS = "\"'.,;:!?()[]{}<>/\\|`~@#$%^&*_+=\u201c\u201d\u2018\u2019\u00ab\u00bb"
_DASH_CHARS_PATTERN = r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043\u00ad]"


def _normalize_text(text: str) -> str:
    """Normalize text for robust phrase matching across punctuation variants."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = (
        t.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    t = re.sub(_DASH_CHARS_PATTERN, "-", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _normalize_token(token: str) -> str:
    """Normalize token and strip boundary punctuation for token-level comparison."""
    t = _normalize_text(token)
    if not t:
        return ""
    return t.strip(_BOUNDARY_CHARS)


def _phrase_tokens(phrase: str) -> list[str]:
    return [tok for tok in (_normalize_token(x) for x in phrase.split()) if tok]


def _tokenize_page_words(page) -> list[dict]:
    """
    Build normalized token list with original bbox references.
    PyMuPDF words: (x0, y0, x1, y1, word, block_no, line_no, word_no)
    """
    words = page.get_text("words")
    out = []
    for w in words:
        if len(w) < 5:
            continue
        x0, y0, x1, y1, raw = w[:5]
        raw_text = str(raw or "")
        norm = _normalize_token(raw_text)
        if not norm:
            continue
        out.append(
            {
                "norm": norm,
                "bbox": fitz.Rect(float(x0), float(y0), float(x1), float(y1)),
                "line": (int(w[5]), int(w[6])) if len(w) > 6 else (0, 0),
            }
        )
    return out


def _match_score(claim_tokens: list[str], match_count: int, span_len: int) -> float:
    if not claim_tokens or span_len <= 0:
        return 0.0
    coverage = match_count / len(claim_tokens)
    compactness = match_count / span_len
    return (0.7 * coverage) + (0.3 * compactness)


def _find_best_token_window(page, claim_text: str) -> tuple[list[fitz.Rect], float]:
    """
    Match claim on a page in normalized token space.
    Returns (rects, confidence). Empty rects if no confident match.
    """
    claim_tokens = _phrase_tokens(claim_text)
    if len(claim_tokens) < 3:
        return ([], 0.0)

    page_tokens = _tokenize_page_words(page)
    if not page_tokens:
        return ([], 0.0)

    n = len(claim_tokens)
    min_required = max(3, int(round(n * 0.9)))
    best: tuple[float, int, int, int] | None = None  # (score, i, j, matched)

    for i in range(len(page_tokens)):
        # Anchor on first or second claim token (helps with punctuation splits)
        first = claim_tokens[0]
        second = claim_tokens[1] if len(claim_tokens) > 1 else None
        if page_tokens[i]["norm"] not in {first, second}:
            continue

        j = i
        k = 0
        matched = 0
        max_skip = 2
        skip_budget = max_skip

        while j < len(page_tokens) and k < n:
            pw = page_tokens[j]["norm"]
            cw = claim_tokens[k]

            if pw == cw:
                matched += 1
                k += 1
                j += 1
                continue

            # Handle line-break hyphenation: "long-" + "term" vs "longterm"
            if (
                j + 1 < len(page_tokens)
                and pw.endswith("-")
                and (pw[:-1] + page_tokens[j + 1]["norm"]) == cw
            ):
                matched += 1
                k += 1
                j += 2
                continue

            if skip_budget > 0:
                skip_budget -= 1
                j += 1
            else:
                break

        span_end = max(i + 1, j)
        span_len = span_end - i
        score = _match_score(claim_tokens, matched, span_len)
        if matched >= min_required:
            candidate = (score, i, span_end, matched)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if not best:
        return ([], 0.0)

    score, i, j, _matched = best
    if score < 0.88:
        return ([], score)

    rects = [t["bbox"] for t in page_tokens[i:j]]
    return (rects, score)


def _best_search_text(phrase: str) -> list[str]:
    """
    Return candidate search strings for a phrase, from most to least specific.
    Handles PDFs where long phrases span line breaks and can't be found verbatim.
    """
    candidates = [phrase]

    words = phrase.split()
    for max_len in [100, 70, 50, 35]:
        chunk = ""
        for w in words:
            trial = (chunk + " " + w).strip()
            if len(trial) <= max_len:
                chunk = trial
            else:
                break
        if chunk and chunk != phrase:
            candidates.append(chunk)

    if len(words) > 6:
        candidates.append(" ".join(words[:6]))

    seen, unique = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def find_claim_location(pdf_bytes: bytes, claim_text: str) -> str:
    if not claim_text or not pdf_bytes:
        return "Document Level"
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        search_str = claim_text.strip()
        candidates = _best_search_text(search_str)

        rects_found = []
        target_page = None

        for candidate in candidates:
            for page in doc:
                rects = _robust_page_search(page, candidate)
                if rects:
                    rects_found = rects
                    target_page = page
                    break
            if target_page:
                break

        # Try normalized token matching if phrase-level search fails.
        if not target_page:
            best_page = None
            best_rects = []
            best_score = 0.0
            for page in doc:
                rects, score = _find_best_token_window(page, search_str)
                if rects and score > best_score:
                    best_rects = rects
                    best_page = page
                    best_score = score
            if best_page and best_rects:
                target_page = best_page
                rects_found = best_rects

        # Legacy fallback: chunk search with stripped boundary punctuation.
        if not target_page:
            words = search_str.split()
            for i in range(0, len(words) - 8, 4):
                chunk = " ".join(words[i : i + 8])
                # FIX #3: strip boundary punctuation so find_claim_location
                # uses the same logic as highlight_pdf_bytes and doesn't diverge
                chunk_stripped = chunk.strip('"\u201c\u201d\u2018\u2019\'.,;:!?—–-')
                for page in doc:
                    rects = _robust_page_search(page, chunk)
                    if not rects and chunk_stripped != chunk:
                        rects = _robust_page_search(page, chunk_stripped)
                    if rects:
                        rects_found = rects
                        target_page = page
                        break
                if target_page:
                    break

        if rects_found and target_page:
            pn = target_page.number + 1

            # ── Approximate line number ──
            # Count distinct text-line y-positions above the found rect's top-y.
            line_no = None
            section_label = None
            try:
                first_rect = rects_found[0]
                target_y = float(first_rect.y0) if hasattr(first_rect, "y0") else float(first_rect[1])

                # Extract all word y-positions and build unique visual lines (cluster by y within 3pt)
                words = target_page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
                if words:
                    line_ys = []
                    for w in words:
                        y = float(w[1])
                        # Cluster: treat lines within 3pt as the same visual line
                        if not line_ys or abs(y - line_ys[-1]) > 3:
                            line_ys.append(y)
                    # Count lines with y <= target_y
                    line_no = sum(1 for y in line_ys if y <= target_y + 1)
                    if line_no < 1:
                        line_no = 1

                # ── Section heading extraction ──
                # Look at text blocks above the found rect for a likely heading
                # (shorter text, possibly bold / larger font — heuristically the last short block above)
                blocks = target_page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, type)
                if blocks:
                    candidate_heading = None
                    for b in blocks:
                        if len(b) < 5 or b[6] != 0:  # skip image blocks
                            continue
                        block_y1 = float(b[3])
                        block_text = str(b[4]).strip().split("\n")[0].strip()  # first line of block
                        if block_y1 <= target_y and 3 < len(block_text) < 120:
                            # Heuristic: headings tend to be shorter, standalone blocks
                            word_count = len(block_text.split())
                            if word_count <= 15:
                                candidate_heading = block_text
                    if candidate_heading:
                        # Clean up: remove trailing punctuation, truncate
                        section_label = candidate_heading.rstrip(".:;,").strip()
                        if len(section_label) > 60:
                            section_label = section_label[:57] + "…"
            except Exception:
                pass  # line/section extraction is best-effort

            # Build rich location string
            parts = [f"Page {pn}"]
            if line_no is not None:
                parts.append(f"Line {line_no}")
            location_str = ", ".join(parts)
            if section_label:
                location_str += f" · {section_label}"

            doc.close()
            return location_str

        doc.close()
        return "Document Level"
    except Exception as e:
        return "Document Level"


def highlight_pdf_bytes(
    pdf_bytes: bytes,
    highlights: list[tuple[str, tuple[float, float, float], int | None]]
) -> bytes:
    import fitz

    def _annotate(page, rects, color):
        for rect in rects:
            annot = page.add_highlight_annot(rect)
            annot.set_colors(stroke=color)
            annot.update()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for phrase, color, target_page in highlights:
        phrase = phrase.strip()
        if not phrase:
            continue

        candidates = _best_search_text(phrase)
        found = False

        pages_to_search = (
            [doc[target_page]]
            if (target_page is not None and 0 <= target_page < len(doc))
            else list(doc)
        )

        for candidate in candidates:
            for page in pages_to_search:
                rects = _robust_page_search(page, candidate)
                if rects:
                    found = True
                    _annotate(page, rects, color)
            if found:
                break

        # Robust fallback: normalized token sequence matching for special chars /
        # punctuation/hyphenation mismatches.
        if not found:
            for page in pages_to_search:
                rects, score = _find_best_token_window(page, phrase)
                if rects and score >= 0.88:
                    found = True
                    _annotate(page, rects, color)

        # Sliding window to catch the rest of the phrase (or cross-block phrases)
        words = phrase.split()
        window_size = 8
        step = 4
        for i in range(0, len(words), step):
            chunk_words = words[i : i + window_size]
            if len(chunk_words) < 3:
                continue
            chunk = " ".join(chunk_words)
            # FIX #1 (previous error): strip boundary punctuation so chunks
            # starting/ending with curly quotes or punctuation still match
            chunk_stripped = chunk.strip('"\u201c\u201d\u2018\u2019\'.,;:!?—–-')
            for page in pages_to_search:
                rects = _robust_page_search(page, chunk)
                if not rects and chunk_stripped != chunk:
                    rects = _robust_page_search(page, chunk_stripped)
                if rects:
                    _annotate(page, rects, color)
                    # FIX #2: removed break — keep searching other pages
                    # so repeated phrases/headers on multiple pages all get highlighted

    out = doc.write()
    doc.close()
    return out


# FIX #4: highlight_pdf now delegates to highlight_pdf_bytes so both
# functions use identical search logic (previously highlight_pdf used
# 6-word non-overlapping chunks with no _robust_page_search)
def highlight_pdf(
    pdf_path: Path | str,
    phrases: List[str],
    output_path: Path | str,
    color: tuple = (1, 1, 0),
) -> Path:
    """
    Highlight all `phrases` in a PDF using PyMuPDF text search.
    Delegates to highlight_pdf_bytes for consistent search logic.

    :param pdf_path: Path to source PDF.
    :param phrases: List of exact phrases to highlight.
    :param output_path: Where to save the annotated PDF.
    :param color: RGB highlight color in 0-1 range. Default: yellow.
    :return: Path to the saved highlighted PDF.
    """
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)

    pdf_bytes = pdf_path.read_bytes()

    # Convert to the highlights format expected by highlight_pdf_bytes
    highlights = [(phrase, color, None) for phrase in phrases if phrase.strip()]

    out_bytes = highlight_pdf_bytes(pdf_bytes, highlights)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(out_bytes)
    return output_path


# ── DOCX ──────────────────────────────────────────────────────────────────────

def _build_segments(combined: str, phrases: List[str]):
    """
    Given a full paragraph text and a list of phrases, return a list of
    (text, highlight) segments covering the entire string.
    Handles multiple phrases and duplicate occurrences in a single pass.
    """
    intervals = []
    for phrase in phrases:
        phrase = phrase.strip()
        if not phrase:
            continue
        # FIX #5: find ALL occurrences of phrase, not just the first
        lower_combined = combined.lower()
        lower_phrase = phrase.lower()
        start = 0
        while True:
            idx = lower_combined.find(lower_phrase, start)
            if idx == -1:
                break
            intervals.append((idx, idx + len(phrase)))
            start = idx + 1  # advance by 1 to catch overlapping matches too

    if not intervals:
        return None

    intervals.sort()
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    segments = []
    pos = 0
    for start, end in merged:
        if pos < start:
            segments.append((combined[pos:start], False))
        segments.append((combined[start:end], True))
        pos = end
    if pos < len(combined):
        segments.append((combined[pos:], False))

    return segments


def _highlight_para_docx(para, phrases: List[str]) -> bool:
    """
    Highlight all `phrases` in a DOCX paragraph in one pass.
    FIX #6: preserves per-run formatting (bold, italic, font, color) instead
    of applying only the first run's rPr to every rebuilt run.
    """
    from docx.oxml.ns import qn
    from lxml import etree
    from copy import deepcopy

    runs = para.runs
    if not runs:
        return False

    combined = "".join(run.text for run in runs)
    segments = _build_segments(combined, phrases)
    if segments is None:
        return False

    # Build a character-level map: for each char position, which run owned it
    # so we can copy that run's rPr for the rebuilt segment
    char_to_run_rpr = []
    for run in runs:
        rpr = run._r.find(qn("w:rPr"))
        for _ in run.text:
            char_to_run_rpr.append(deepcopy(rpr) if rpr is not None else None)

    p = para._p
    for r in p.findall(qn("w:r")):
        p.remove(r)

    pos = 0
    for text, do_highlight in segments:
        if not text:
            pos += len(text)
            continue

        # Use the rPr of the first character of this segment
        source_rpr = char_to_run_rpr[pos] if pos < len(char_to_run_rpr) else None

        r_elem = etree.SubElement(p, qn("w:r"))
        new_rpr = deepcopy(source_rpr) if source_rpr is not None else etree.Element(qn("w:rPr"))

        hl = new_rpr.find(qn("w:highlight"))
        if do_highlight:
            if hl is None:
                hl = etree.SubElement(new_rpr, qn("w:highlight"))
            hl.set(qn("w:val"), "yellow")
        else:
            if hl is not None:
                new_rpr.remove(hl)

        r_elem.insert(0, new_rpr)
        t_elem = etree.SubElement(r_elem, qn("w:t"))
        t_elem.text = text
        if text != text.strip():
            t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

        pos += len(text)

    return True


def highlight_docx(
    docx_path: Path | str,
    phrases: List[str],
    output_path: Path | str,
) -> Path:
    """
    Highlight all `phrases` in a DOCX file.
    Searches paragraphs (including inside tables) and applies yellow highlight
    to all matching text spans in a single pass per paragraph.
    """
    from docx import Document

    docx_path = Path(docx_path)
    output_path = Path(output_path)

    doc = Document(str(docx_path))

    def _iter_paragraphs(document):
        for para in document.paragraphs:
            yield para
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        yield para

    for para in _iter_paragraphs(doc):
        _highlight_para_docx(para, phrases)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path


# ── PPTX ──────────────────────────────────────────────────────────────────────

def _highlight_para_pptx(para, phrases: List[str]) -> bool:
    """
    Highlight all `phrases` in a PPTX paragraph in one pass.
    FIX #6: preserves per-run formatting instead of using only first run's rPr.
    """
    from pptx.oxml.ns import qn as pqn
    from lxml import etree
    from copy import deepcopy

    runs = para.runs
    if not runs:
        return False

    combined = "".join(run.text for run in runs)
    segments = _build_segments(combined, phrases)
    if segments is None:
        return False

    # Build character-level rPr map from original runs (FIX #6)
    char_to_run_rpr = []
    for run in runs:
        rPr = run._r.find(pqn("a:rPr"))
        for _ in run.text:
            char_to_run_rpr.append(deepcopy(rPr) if rPr is not None else None)

    p = para._p
    for r in p.findall(pqn("a:r")):
        p.remove(r)

    endParaRPr = p.find(pqn("a:endParaRPr"))

    HIGHLIGHT_XML = (
        '<a:highlight xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:srgbClr val="FFFF00"/>'
        '</a:highlight>'
    )

    pos = 0
    for text, do_highlight in segments:
        if not text:
            pos += len(text)
            continue

        source_rPr = char_to_run_rpr[pos] if pos < len(char_to_run_rpr) else None

        r_elem = etree.Element(pqn("a:r"))
        new_rPr = deepcopy(source_rPr) if source_rPr is not None else etree.Element(pqn("a:rPr"))

        existing_hl = new_rPr.find(pqn("a:highlight"))
        if do_highlight:
            if existing_hl is not None:
                new_rPr.remove(existing_hl)
            new_rPr.append(etree.fromstring(HIGHLIGHT_XML))
        else:
            if existing_hl is not None:
                new_rPr.remove(existing_hl)

        r_elem.append(new_rPr)
        t_elem = etree.SubElement(r_elem, pqn("a:t"))
        t_elem.text = text
        if endParaRPr is not None:
            endParaRPr.addprevious(r_elem)
        else:
            p.append(r_elem)

        pos += len(text)

    return True


def highlight_pptx(
    pptx_path: Path | str,
    phrases: List[str],
    output_path: Path | str,
) -> Path:
    """
    Highlight all `phrases` in a PPTX file.
    Searches all text frames in all slides and applies a yellow highlight
    to matching text runs.

    :param pptx_path: Path to source PPTX.
    :param phrases: List of exact phrases to highlight.
    :param output_path: Where to save the annotated PPTX.
    :return: Path to the saved highlighted PPTX.
    """
    from pptx import Presentation

    pptx_path = Path(pptx_path)
    output_path = Path(output_path)

    prs = Presentation(str(pptx_path))

    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                _highlight_para_pptx(para, phrases)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    return output_path