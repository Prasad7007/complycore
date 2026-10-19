"""
Pipeline orchestration: 4-stage compliance evaluation per chunk.
"""

import logging
import re
from typing import Callable, Protocol

from .deterministic import run_deterministic
from .evaluator import evaluate_claims_for_rules, evaluate_balance_v2, get_combined_suggestion
from .claim_ids import normalize_extraction_claim_ids
from .extractor import extract_chunk, merge_extraction_results
from .models import (
    ChunkMetadata,
    ChunkResult,
    ClaimExtraction,
    ClaimResult,
    DocumentMetrics,
    DocumentResult,
    ExtractionResult,
    Violation,
)
logger = logging.getLogger(__name__)

# Chunk index used for document-level violations (no single chunk)
DOCUMENT_LEVEL_CHUNK_INDEX = -1

# Claim-level rules always evaluated by LLM when a chunk has extracted claims.
LLM_CLAIM_RULES: list[int] = [1, 2, 3, 6, 7, 8]


class LLMClient(Protocol):
    """Client for evaluation steps."""

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str: ...


def _compute_chunk_metadata(raw: list[dict] | dict) -> ChunkMetadata:
    """Convert raw metadata from chunker into ChunkMetadata model.

    The chunker passes a list of per-element metadata dicts (font_size, is_heading, etc.).
    Disclaimer/claim font fields are not computed at chunk-level so they remain None.
    """
    if isinstance(raw, list):
        if not raw:
            return ChunkMetadata()
        return ChunkMetadata(
            is_heading=any(bool(m.get("is_heading")) for m in raw),
            is_bold=any(bool(m.get("is_bold")) for m in raw),
            section_identifier=str(raw[0].get("section_identifier") or ""),
            # claim_font_size / disclaimer_font_size are not in raw chunker output yet
        )
    # Legacy: flat dict with pre-computed fields
    return ChunkMetadata(
        disclaimer_font_size=raw.get("disclaimer_font_size"),
        claim_font_size=raw.get("claim_font_size"),
        disclaimer_distance_chars=raw.get("disclaimer_distance_chars"),
        disclaimer_distance_pixels=raw.get("disclaimer_distance_pixels"),
        is_heading=bool(raw.get("is_heading")),
        is_bold=bool(raw.get("is_bold")),
        section_identifier=str(raw.get("section_identifier") or ""),
    )


def _get_claim_with_context(chunk_text: str, claim_text: str) -> dict:
    """
    Find claim in chunk and return dict with 1 sentence before and after.
    Used for Rule 2 context in Stage 2.
    """
    if not claim_text or not chunk_text:
        return {"claim_text": claim_text, "context_before": "", "context_after": ""}
    
    # Simple sentence-like splitter (not perfect but fast)
    sentences = re.split(r'(?<=[.!?])\s+', chunk_text)
    claim_idx = -1
    for idx, s in enumerate(sentences):
        if claim_text.lower() in s.lower():
            claim_idx = idx
            break
            
    if claim_idx == -1:
        return {"claim_text": claim_text, "context_before": "", "context_after": ""}
        
    before = sentences[claim_idx - 1] if claim_idx > 0 else ""
    after = sentences[claim_idx + 1] if claim_idx < len(sentences) - 1 else ""
    
    return {
        "claim_text": claim_text,
        "context_before": before,
        "context_after": after
    }


def _build_visual_evidence_payload(extraction: ExtractionResult | None) -> list[dict]:
    """Compact visual evidence payload injected into rule prompts."""
    if extraction is None:
        return []

    claims = extraction.claims or []
    # Dedup + cap to keep prompt size stable (production safety).
    seen_norm: set[str] = set()
    chart_items: list[dict] = []
    table_items: list[dict] = []

    def _norm_key(s: str) -> str:
        return " ".join((s or "").lower().strip().split())[:200]

    def _infer_item_type(text: str) -> str:
        t = (text or "").lower()
        if any(k in t for k in ("table", "tabular", "row", "column", "quarter", "q1", "q2", "q3", "q4")):
            return "table_image"
        # Visual extraction currently processes image candidates that are usually chart/figure-like.
        return "chart"

    MAX_CHART_ITEMS = 10
    MAX_TABLE_ITEMS = 8
    MAX_TEXT_CHARS = 160

    for idx, claim in enumerate(claims, start=1):
        text = (claim.claim_text or "").strip()
        if not text:
            continue

        norm = _norm_key(text)
        if not norm or norm in seen_norm:
            continue
        seen_norm.add(norm)

        item_type = _infer_item_type(text)
        payload_item = {
            "evidence_id": f"visual_merge:{idx}",
            "item_type": item_type,
            "claim_text": text[:MAX_TEXT_CHARS],
        }
        if item_type == "table_image":
            if len(table_items) < MAX_TABLE_ITEMS:
                table_items.append(payload_item)
        else:
            if len(chart_items) < MAX_CHART_ITEMS:
                chart_items.append(payload_item)

        if len(chart_items) >= MAX_CHART_ITEMS and len(table_items) >= MAX_TABLE_ITEMS:
            break

    # Keep ordering stable: charts first, then table-image.
    return chart_items + table_items



def _deduplicate_violations(violations: list[Violation]) -> list[Violation]:
    """Remove duplicate violations across chunks.

    Two violations are considered duplicates if they share:
    - Same rule number
    - Substantially the same claim text (first 120 normalized chars)

    The first occurrence (lowest chunk_index) is kept.
    Document-level violations (chunk_index == -1) are always kept.
    """
    seen: set[tuple] = set()
    deduped: list[Violation] = []

    for v in violations:
        # Always keep document-level structural violations
        if v.chunk_index == DOCUMENT_LEVEL_CHUNK_INDEX:
            deduped.append(v)
            continue

        # Fingerprint: rule + first 120 chars of normalized claim text
        claim_key = (v.claim_text or v.problematic_phrase or "").lower().strip()[:120]
        fingerprint = (v.rule, claim_key)

        if fingerprint not in seen:
            seen.add(fingerprint)
            deduped.append(v)
        else:
            logger.debug(
                "dedup_skip rule=%s chunk=%s claim=%s",
                v.rule, v.chunk_index, claim_key[:60],
            )

    original_count = len(violations)
    deduped_count = len(deduped)
    if original_count != deduped_count:
        logger.info(
            "deduplication removed %s duplicate violations (%s -> %s)",
            original_count - deduped_count, original_count, deduped_count,
        )
    return deduped


def _is_citation_only_claim(claim: ClaimExtraction) -> bool:
    """True when the row is a source/footnote line, not evaluable marketing copy."""
    if not claim.has_kind("citation"):
        return False
    return not claim.has_kind("performance") and not claim.has_kind("risk")


def _collect_global_citations(extractions: list[ExtractionResult | None]) -> list[str]:
    """Merge citation-kind claim text across chunks (deduped, order preserved)."""
    seen: set[str] = set()
    citations: list[str] = []
    for ext in extractions:
        if not ext:
            continue
        for claim in ext.claims or []:
            if not claim.has_kind("citation"):
                continue
            text = (claim.claim_text or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            citations.append(text)
    return citations


def _compute_kind_metrics(chunk_results: list[ChunkResult]) -> DocumentMetrics:
    """Aggregate kind counts and claim-text repetition across chunks."""
    total_performance_claims = 0
    total_risk_claims = 0
    total_other_claims = 0
    total_claims = 0
    repetition_map: dict[str, int] = {}

    for cr in chunk_results:
        ext = cr.extraction
        if not ext:
            continue
        for claim in ext.claims or []:
            if _is_citation_only_claim(claim):
                continue
            total_claims += 1
            if claim.has_kind("performance"):
                total_performance_claims += 1
            if claim.has_kind("risk"):
                total_risk_claims += 1
            if not claim.has_kind("performance") and not claim.has_kind("risk"):
                total_other_claims += 1
            if claim.claim_text and len(claim.claim_text.strip()) > 10:
                key = claim.claim_text.strip().lower()[:200]
                repetition_map[key] = repetition_map.get(key, 0) + 1

    performance_to_risk_ratio = round(
        total_performance_claims / max(1, total_risk_claims), 2
    )

    return DocumentMetrics(
        total_claims=total_claims,
        total_performance_claims=total_performance_claims,
        total_risk_claims=total_risk_claims,
        total_other_claims=total_other_claims,
        performance_to_risk_ratio=performance_to_risk_ratio,
        repetition_frequency_map=repetition_map,
    )


def _sample_claims_by_kind(
    chunk_results: list[ChunkResult],
    *,
    kind: str,
    limit: int = 8,
) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for cr in chunk_results:
        ext = cr.extraction
        if not ext:
            continue
        for claim in ext.claims or []:
            if not claim.has_kind(kind):
                continue
            samples.append(
                {"claim_id": claim.claim_id, "claim_text": claim.claim_text}
            )
            if len(samples) >= limit:
                return samples
    return samples


def _repeated_claim_phrases(
    repetition_map: dict[str, int],
    *,
    min_count: int = 2,
    limit: int = 5,
) -> list[dict[str, str | int]]:
    repeated = [
        {"claim_text": text, "count": count}
        for text, count in repetition_map.items()
        if count >= min_count and len(text.strip()) > 15
    ]
    repeated.sort(key=lambda item: item["count"], reverse=True)
    return repeated[:limit]


def _build_document_context(chunks: list[str], max_chars: int = 2000) -> str:
    parts: list[str] = []
    remaining = max_chars
    for i, text in enumerate(chunks):
        if remaining <= 0:
            break
        snippet = (text or "").strip()[: min(500, remaining)]
        if not snippet:
            continue
        parts.append(f"[Chunk {i}]\n{snippet}")
        remaining -= len(snippet) + 20
    return "\n\n".join(parts) if parts else "(no document text available)"


def run_pipeline(
    chunks: list[str],
    llm_client: LLMClient,
    *,
    document_id: str = "",
    metadata_dicts: list[list[dict]] | None = None,
    prompts_map: dict[int, str] | None = None,
    on_rules_progress: Callable[[set[int]], None] | None = None,
    visual_extraction_merge: ExtractionResult | None = None,
) -> DocumentResult:
    """
    Run the full 4-stage compliance pipeline on a list of chunks.

    Per chunk:
      1. Extraction (LLM): claims with kind labels.
      1.5. Deterministic pre-pass: Rule 5 (formatting/metadata only).
      2. Claim evaluation (LLM): Rules 1, 2, 3, 6, 7, 8 on all extracted claims.

    After all chunks:
      4. Rule 4 (LLM): one document-level fair & balanced check using kind counts,
         sample claims, repetition, and short document context.

    :param chunks: List of chunk texts (e.g. from your chunker).
    :param llm_client: Client with .invoke(system_prompt, user_prompt) -> str.
    :param document_id: Stable document identifier for normalized claim_ids.
    :param metadata_dicts: Optional list of raw metadata lists from Chunker.
    :param visual_extraction_merge: Optional chart/image extraction merged into chunk 0.
    :return: DocumentResult with chunks_processed, violations (all), and chunk_results.
    """
    # Build proper ChunkMetadata objects
    metadata_objects = []
    if metadata_dicts and len(metadata_dicts) == len(chunks):
        for raw in metadata_dicts:
            metadata_objects.append(_compute_chunk_metadata(raw))
    else:
        metadata_objects = [ChunkMetadata() for _ in range(len(chunks))]

    all_violations: list[Violation] = []
    chunk_results: list[ChunkResult] = []
    all_claim_results: list[ClaimResult] = []
    
    doc_id = document_id or "unknown_doc"

    # Phase 1: Extraction (Parallel across all chunks)
    extractions = [None] * len(chunks)
    llm_responses_by_chunk = [{} for _ in range(len(chunks))]
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _safe_extract(idx, chunk_text):
        try:
            return idx, extract_chunk(chunk_text, llm_client)
        except Exception as e:
            if "Throttling" in str(e) or "LimitExceeded" in str(e):
                logger.warning("pipeline extraction chunk=%s throttled", idx)
            else:
                logger.exception("pipeline extraction chunk=%s error=%s", idx, e)
            # Keep raw response typed as string for ChunkResult.llm_responses schema.
            return idx, (None, "")

    with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
        futures = [executor.submit(_safe_extract, i, text) for i, text in enumerate(chunks)]
        for future in as_completed(futures):
            i, (ext, raw) = future.result()
            extractions[i] = ext
            llm_responses_by_chunk[i] = {"extraction": raw}

    for i, ext in enumerate(extractions):
        extractions[i] = normalize_extraction_claim_ids(ext, doc_id, i)

    visual_evidence_payload: list[dict] = _build_visual_evidence_payload(visual_extraction_merge)

    if visual_extraction_merge is not None and extractions:
        extractions[0] = merge_extraction_results(extractions[0], visual_extraction_merge)
        extractions[0] = normalize_extraction_claim_ids(extractions[0], doc_id, 0)

    global_citations = _collect_global_citations(extractions)

    # Phase 2: Evaluation (Parallel across all chunks)
    all_violations: list[Violation] = []
    chunk_results: list[ChunkResult] = [None] * len(chunks)
    all_claim_results: list[ClaimResult] = []

    import threading
    _progress_lock = threading.Lock()
    _completed_rules: set[int] = set()

    def _report_rules(new_rules: set[int]):
        """Thread-safe: merge *new_rules* into global set; fire callback only when set grows."""
        if not on_rules_progress or not new_rules:
            return
        with _progress_lock:
            before = len(_completed_rules)
            _completed_rules.update(new_rules)
            if len(_completed_rules) <= before:
                return
            snapshot = set(_completed_rules)
        try:
            on_rules_progress(snapshot)
        except Exception:
            pass

    def _process_chunk_eval(i):
        chunk_text = chunks[i]
        metadata = metadata_objects[i]
        extraction = extractions[i]
        llm_responses = llm_responses_by_chunk[i]

        if not extraction:
            return i, ChunkResult(chunk_index=i, error="Extraction failed"), [], []

        try:
            # --- Stage 1: Deterministic pre-pass (Rule 5) ---
            first_claim = next(
                (c for c in (extraction.claims or []) if not _is_citation_only_claim(c)),
                None,
            )
            rep_claim_text = (
                first_claim.claim_text
                if first_claim and first_claim.claim_text
                else chunk_text[:chunk_text.find('.') + 1 if '.' in chunk_text[:200] else 200].strip()
            )

            det = run_deterministic(
                extraction, chunk_text, chunk_index=i, metadata=metadata, claim_text=rep_claim_text,
            )
            chunk_violations = det.violations

            for v in chunk_violations:
                if not v.suggested_alternative and v.method == "deterministic":
                    try:
                        v.suggested_alternative = get_combined_suggestion(
                            claim_text=v.problematic_phrase or rep_claim_text,
                            violations=[v], llm_client=llm_client,
                        )
                    except Exception:
                        pass

            _report_rules({5})

            evaluable_claims = [
                c for c in (extraction.claims or []) if not _is_citation_only_claim(c)
            ]
            # --- Stage 2: LLM evaluation (Rules 1,2,3,6,7,8) — skip citation-only rows ---
            rules_for_chunk = list(LLM_CLAIM_RULES) if evaluable_claims else []

            chunk_claim_results = []
            c_ctx_list = []
            for claim in evaluable_claims:
                c_ctx = _get_claim_with_context(chunk_text, claim.claim_text)
                c_ctx["claim_id"] = claim.claim_id
                c_ctx_list.append(c_ctx)

            if c_ctx_list:
                c_violations, c_responses = evaluate_claims_for_rules(
                    claims_context_list=c_ctx_list, rules_to_run=rules_for_chunk,
                    llm_client=llm_client, chunk_text=chunk_text, chunk_index=i,
                    global_citations=global_citations,
                    visual_evidence=visual_evidence_payload,
                    prompts_map=prompts_map,
                )
                llm_responses.update(c_responses)

                v_by_claim = {}
                for v in c_violations:
                    cid = v.claim_id
                    if cid not in v_by_claim:
                        v_by_claim[cid] = []
                    v_by_claim[cid].append(v)

                for claim in (extraction.claims or []):
                    cid = claim.claim_id
                    claim_viols = v_by_claim.get(cid, [])
                    if claim_viols:
                        combined_alt = ""
                        if len(claim_viols) > 1:
                            combined_alt = get_combined_suggestion(claim.claim_text, claim_viols, llm_client)
                        elif len(claim_viols) == 1:
                            combined_alt = claim_viols[0].suggested_alternative
                        chunk_claim_results.append(ClaimResult(
                            claim_id=cid, claim_text=claim.claim_text, chunk_index=i,
                            rules_violated=[v.rule for v in claim_viols],
                            violations=claim_viols, combined_suggestion=combined_alt,
                        ))
                chunk_violations.extend(c_violations)

            _report_rules(set(rules_for_chunk))

            res = ChunkResult(
                chunk_index=i, chunk_text=chunk_text[:1000],
                extraction=extraction, claim_results=chunk_claim_results,
                violations=chunk_violations, deterministic_flags=det.violations,
                llm_responses=llm_responses, projection_without_disclaimer=det.projection_without_disclaimer,
            )
            return i, res, chunk_violations, chunk_claim_results

        except Exception as e:
            logger.exception("pipeline eval chunk=%s error=%s", i, e)
            return i, ChunkResult(chunk_index=i, error=str(e)), [], []

    # Fire all chunk evaluations concurrently (full pipelining, no barriers)
    with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
        futures = [executor.submit(_process_chunk_eval, i) for i in range(len(chunks))]
        for future in as_completed(futures):
            i, c_res, c_viols, c_claims = future.result()
            chunk_results[i] = c_res
            all_violations.extend(c_viols)
            all_claim_results.extend(c_claims)

            
    document_metrics = _compute_kind_metrics(chunk_results)

    # Stage 4: Rule 4 (Fair & Balanced) — one LLM call per document when claims exist
    if document_metrics.total_claims > 0:
        logger.info(
            "pipeline running Rule 4 doc-level eval claims=%s perf=%s risk=%s other=%s",
            document_metrics.total_claims,
            document_metrics.total_performance_claims,
            document_metrics.total_risk_claims,
            document_metrics.total_other_claims,
        )
        try:
            violations_stage4, raw_s4 = evaluate_balance_v2(
                document_context=_build_document_context(chunks),
                performance_count=document_metrics.total_performance_claims,
                risk_count=document_metrics.total_risk_claims,
                other_count=document_metrics.total_other_claims,
                performance_to_risk_ratio=document_metrics.performance_to_risk_ratio,
                sample_performance_claims=_sample_claims_by_kind(
                    chunk_results, kind="performance"
                ),
                sample_risk_claims=_sample_claims_by_kind(chunk_results, kind="risk"),
                repeated_phrases=_repeated_claim_phrases(
                    document_metrics.repetition_frequency_map
                ),
                llm_client=llm_client,
                chunk_index=DOCUMENT_LEVEL_CHUNK_INDEX,
            )
            if chunk_results:
                chunk_results[0].llm_responses["rule_4_doc"] = raw_s4
            all_violations.extend(violations_stage4)
        except Exception as e:
            logger.warning("Rule 4 doc-level eval failed: %s", e)
    else:
        logger.info("Rule 4 skipped — no extracted claims in document")

    _report_rules({4})

    # Deduplicate violations across chunks before returning
    # (same claim + same rule seen in multiple chunks → keep first occurrence)
    all_violations = _deduplicate_violations(all_violations)

    return DocumentResult(
        chunks_processed=len(chunks),
        claim_results=all_claim_results,
        violations=all_violations,
        chunk_results=chunk_results,
        projection_without_disclaimer_count=0,
        document_metrics=document_metrics,
    )