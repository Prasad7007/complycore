"""
Deterministic checks — Rule 5 formatting/metadata only.

Rules 1, 2, 3, 6, 7, 8 are evaluated by LLM on extracted claims (see pipeline).
Legacy rule 3/6/7/8 helpers remain for reference but are not invoked.
"""

import logging
import re
from dataclasses import dataclass
from typing import Literal

from .models import (
    ChunkMetadata,
    ExtractionResult,
    LanguageIndicators,
    Violation,
)
from .rules.config import (
    CORE_ABSOLUTE_PHRASES,
    LEVERAGE_DERIVATIVE_PHRASES,
    RULE_3_RISK_MINIMIZATION_PHRASES,
    RULE_5_DISCLAIMER_DISTANCE_MAX_CHARS,
    RULE_5_DISCLAIMER_FONT_RATIO_MIN,
    RULE_6_QUALIFIER_PROXIMITY_CHARS,
    RULE_NAMES,
    RULE_8_DISCLAIMER_PHRASES,
    RULE_8_DISCLAIMER_PROXIMITY_CHARS,
    RULE_8_FORWARD_PROJECTION_PHRASES,
)

logger = logging.getLogger(__name__)


@dataclass
class DeterministicResult:
    """Result of running deterministic checks on one chunk."""

    violations: list[Violation]
    """Auto-flagged violations (Rule 5 formatting only)."""

    rules_still_needing_llm: list[int]
    """Deprecated — pipeline always runs claim-level LLM rules when claims exist."""

    projection_without_disclaimer: bool = False
    """Deprecated — retained for ChunkResult schema compatibility."""


def _indicators(_extraction: ExtractionResult) -> LanguageIndicators:
    """Extraction no longer provides language indicators; use chunk_text scans instead."""
    return LanguageIndicators()


def _phrases_in_text(text: str, phrases: list[str]) -> list[str]:
    lower = (text or "").lower()
    return [p for p in phrases if p.lower() in lower]


def _violation(
    rule: int,
    reasoning: str,
    chunk_index: int = 0,
    claim_text: str = "",
    claim_id: str = "",
    problematic_phrase: str = "",  # NEW: Exact keyword that triggered violation
    severity: str = "MEDIUM",
    status: Literal["APPROVE", "CONDITIONAL", "REJECT"] = "REJECT",
) -> Violation:
    return Violation(
        rule=rule,
        rule_name=RULE_NAMES.get(rule, ""),
        claim_text=claim_text,
        claim_id=claim_id,
        problematic_phrase=problematic_phrase,  # NEW
        chunk_index=chunk_index,
        status=status,
        compliant=(status == "APPROVE"),
        reasoning=reasoning,
        severity=severity,
        method="deterministic",
    )


# ----- Rule 5: Formatting (metadata only) -----


def _check_rule5(
    metadata: ChunkMetadata | None,
    chunk_index: int,
    claim_text: str = "",
) -> Violation | None:
    """If metadata shows formatting issues, return a violation. Else None."""
    if metadata is None:
        return None

    if metadata.claim_font_size and metadata.disclaimer_font_size is not None:
        ratio = metadata.disclaimer_font_size / metadata.claim_font_size
        if ratio < RULE_5_DISCLAIMER_FONT_RATIO_MIN:
            return _violation(
                rule=5,
                reasoning=f"Disclaimer font size is less than 50% of claim font (ratio={ratio:.2f}).",
                chunk_index=chunk_index,
                claim_text=claim_text,
                severity="HIGH",
            )

    if metadata.disclaimer_distance_chars is not None:
        if metadata.disclaimer_distance_chars > RULE_5_DISCLAIMER_DISTANCE_MAX_CHARS:
            return _violation(
                rule=5,
                reasoning=f"Disclaimer is more than {RULE_5_DISCLAIMER_DISTANCE_MAX_CHARS} characters from claim.",
                chunk_index=chunk_index,
                claim_text=claim_text,
                severity="MEDIUM",
            )

    return None


# ----- Rule 6: Absolutes / promotional (v2: proximity logic) -----


def _absolutes_in_chunk(chunk_text: str) -> list[str]:
    """Find core absolute phrases present in chunk (deterministic red-flag list)."""
    lower = chunk_text.lower()
    return [p for p in CORE_ABSOLUTE_PHRASES if p in lower]


def _phrase_spans_in_text(text: str, phrases: list[str]) -> list[tuple[int, int]]:
    """Return all (start, end) spans for any of the given phrases in text (case-insensitive)."""
    if not phrases:
        return []
    lower = text.lower()
    spans: list[tuple[int, int]] = []
    for phrase in phrases:
        if not phrase.strip():
            continue
        start = 0
        while True:
            idx = lower.find(phrase.lower(), start)
            if idx == -1:
                break
            spans.append((idx, idx + len(phrase)))
            start = idx + 1
    return sorted(spans)


def _min_distance_between_spans(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Minimum character distance between two spans (0 if overlapping)."""
    a_start, a_end = a
    b_start, b_end = b
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _has_qualifier_near(absolute_span: tuple[int, int], qualifier_spans: list[tuple[int, int]], max_chars: int) -> bool:
    """True if at least one qualifier span is within max_chars of the absolute span."""
    for q in qualifier_spans:
        if _min_distance_between_spans(absolute_span, q) <= max_chars:
            return True
    return False


_NEGATION_WORDS = re.compile(r"\b(not|no|never|without|nor|non)\b", re.IGNORECASE)
_NEGATION_LOOKBACK_CHARS = 30  # How far back to check for negation before the absolute phrase
_RULE_6_HARD_FAIL_PHRASES = {
    "risk-free",
    "guaranteed",
    "guarantee",
    "never fails",
    "never failed",
    "always profitable",
    "completely safe",
    "100% safe",
    "cannot lose",
    "no risk",
    "certain returns",
    "without risk",
    "risk eliminated",
}
_RULE_8_INVESTOR_OUTCOME_HINTS = (
    "return",
    "returns",
    "yield",
    "income",
    "growth",
    "outperform",
    "alpha",
    "upside",
    "downside",
    "drawdown",
    "capital",
    "wealth",
    "portfolio",
    "investment",
    "investor",
    "fund",
    "strategy",
    "performance",
    "cashflow",
    "distribution",
)


def _is_negated(chunk_text: str, span: tuple[int, int]) -> bool:
    """F2: True if the absolute phrase at span is preceded by a negation word.

    Example: 'returns are not guaranteed' → 'guaranteed' is negated → skip flag.
    We look back up to _NEGATION_LOOKBACK_CHARS characters before the span start.
    """
    start, _ = span
    lookback_start = max(0, start - _NEGATION_LOOKBACK_CHARS)
    preceding_text = chunk_text[lookback_start:start]
    return bool(_NEGATION_WORDS.search(preceding_text))


def _extract_sentence(chunk_text: str, span: tuple[int, int]) -> str:
    """F3: Extract the full sentence containing the given span, without breaking mid-word.

    Walks backwards to the previous sentence-ending punctuation or start of text,
    then forwards to the next sentence-ending punctuation or end of text.
    Also respects newlines as hard boundaries to prevent bullet-point swallowing.
    """
    start, end = span
    
    # Walk backward to find sentence start
    sent_start = 0
    for i in range(start - 1, -1, -1):
        if chunk_text[i] in ('.', '!', '?', '\n', '\r'):
            sent_start = i + 1
            break

    # Walk forward to find sentence end
    sent_end = len(chunk_text)
    for i in range(end, len(chunk_text)):
        if chunk_text[i] in ('.', '!', '?', '\n', '\r'):
            sent_end = i + 1 if chunk_text[i] not in ('\n', '\r') else i
            break

    sentence = chunk_text[sent_start:sent_end].strip()
    # Safety: cap at 400 chars to avoid returning a wall of text (e.g. no punctuation at all)
    if len(sentence) > 400:
        # Try to cut at a word boundary near char 400
        cut = sentence.rfind(' ', 0, 400)
        sentence = sentence[:cut if cut > 0 else 400] + "…"
    return sentence



def _check_rule6(
    indicators: LanguageIndicators,
    chunk_text: str,
    chunk_index: int,
    claim_text: str = "",
) -> tuple[Violation | None, bool]:
    """
    Returns (violation or None, needs_llm).
    Rule 6 is LLM-only for final decision quality:
    - If certainty/promotion cues are present, route to LLM.
    - If no relevant cues are present, skip Rule 6.

    Deterministic Rule 6 violations are intentionally disabled.
    """
    core_found = _absolutes_in_chunk(chunk_text)
    if core_found:
        return None, True
    return None, False



# ----- Rule 7: Emotional -----


def _check_rule7(
    indicators: LanguageIndicators,
    chunk_index: int,
    claim_text: str = "",
    chunk_text: str = "",
) -> tuple[Violation | None, bool]:
    """
    Returns (violation or None, needs_llm).
    Rule 7 is LLM-only for decision quality:
    - emotional empty → (None, False)
    - emotional non-empty but none verified in chunk_text → (None, False)
    - emotional verified in chunk_text → (None, True)  # route to LLM (no deterministic auto-flag)
    """
    # Route emotional evaluation to LLM; chunk text is the source of truth.
    if (chunk_text or "").strip():
        return None, True
    return None, False


# ----- Rule 8: Forward-looking -----


def _has_disclaimer_phrase(chunk_text: str) -> bool:
    """True if chunk contains a forward-looking disclaimer phrase."""
    lower = chunk_text.lower()
    return any(phrase in lower for phrase in RULE_8_DISCLAIMER_PHRASES)


def _has_span_near(span: tuple[int, int], other_spans: list[tuple[int, int]], max_chars: int) -> bool:
    """True if at least one of other_spans is within max_chars of span."""
    for other in other_spans:
        if _min_distance_between_spans(span, other) <= max_chars:
            return True
    return False


def _check_rule8_proximity(
    indicators: LanguageIndicators,
    chunk_text: str,
    chunk_index: int,
    claim_text: str = "",
    extraction: ExtractionResult | None = None,
) -> Violation | None:
    """
    v2: If forward projection in chunk but no disclaimer within RULE_8_DISCLAIMER_PROXIMITY_CHARS,
    return a Rule 8 violation with HIGH severity. Otherwise None.
    """
    projection_phrases = _phrases_in_text(chunk_text, RULE_8_FORWARD_PROJECTION_PHRASES)
    if not projection_phrases:
        return None
    projection_spans = _phrase_spans_in_text(chunk_text, projection_phrases)

    disclaimer_phrases = list(RULE_8_DISCLAIMER_PHRASES)
        
    disclaimer_spans = _phrase_spans_in_text(chunk_text, disclaimer_phrases)

    if not projection_spans:
        return None

    for span in projection_spans:
        if not _has_span_near(span, disclaimer_spans, RULE_8_DISCLAIMER_PROXIMITY_CHARS):
            problematic_phrase = _extract_sentence(chunk_text, span)  # F3: full sentence
            return _violation(
                rule=8,
                reasoning=(
                    f"Forward-looking or projection language with no disclaimer within "
                    f"{RULE_8_DISCLAIMER_PROXIMITY_CHARS} characters. Disclaimer must be proximate to the claim."
                ),
                chunk_index=chunk_index,
                claim_text=claim_text,
                problematic_phrase=problematic_phrase,
                severity="HIGH",
            )
    return None


def _check_rule8(
    indicators: LanguageIndicators,
    chunk_text: str,
    chunk_index: int,
    claim_text: str = "",
    extraction: ExtractionResult | None = None,
) -> tuple[Violation | None, bool]:
    """
    Returns (violation or None, needs_llm).
    
    Logic: Always send Rule 8 to LLM evaluator for context-aware evaluation.
    - Evaluator checks passage context (A/B/C) and only flags when forward-looking
      language is tied to products/performance/returns, not generic educational/narrative.
    - Skip Rule 8 only if no forward_looking keywords are present.
    """
    chunk_lower = (chunk_text or "").lower()
    has_outcome_hint = any(token in chunk_lower for token in _RULE_8_INVESTOR_OUTCOME_HINTS)

    forward_phrases = _phrases_in_text(chunk_text, RULE_8_FORWARD_PROJECTION_PHRASES)
    if forward_phrases and has_outcome_hint:
        return None, True
    if extraction and extraction.claims:
        return None, True
    return None, False


# ----- Rule 3: Leverage/derivative + "without changing risk" → HIGH (risk minimization) -----
def _check_rule3_leverage_risk_minimization(
    extraction: ExtractionResult,
    chunk_text: str,
    chunk_index: int,
    claim_text: str = "",
) -> Violation | None:
    """If chunk has leverage/derivative language and risk-minimization phrasing, flag Rule 3 HIGH."""
    if not (chunk_text or "").strip():
        return None
    lower = (chunk_text or "").lower()
    has_leverage = bool(_phrases_in_text(chunk_text, LEVERAGE_DERIVATIVE_PHRASES))
    if not has_leverage:
        return None
    has_risk_min_phrase = any(p in lower for p in RULE_3_RISK_MINIMIZATION_PHRASES)
    if not has_risk_min_phrase:
        return None
    return _violation(
        rule=3,
        reasoning="Leverage or derivative language combined with risk-minimization phrasing (e.g. 'without changing risk'); structural risk misrepresentation.",
        chunk_index=chunk_index,
        claim_text=claim_text,
        severity="HIGH",
        status="REJECT",
    )


# ----- Rule 4 coupling (performance without risk in same chunk) -----


def _check_rule4_coupling(
    extraction: ExtractionResult,
    indicators: LanguageIndicators,
    chunk_index: int,
    claim_text: str = "",
) -> Violation | None:
    """If chunk has performance but no risk language, flag Rule 4 CONDITIONAL."""
    has_performance = any(c.has_kind("performance") for c in (extraction.claims or []))
    if not has_performance:
        return None
    has_risk = any(c.has_kind("risk") for c in (extraction.claims or []))
    if has_risk:
        return None
    return _violation(
        rule=4,
        reasoning="Performance claims in chunk without risk disclosure in same context; balance may be inadequate.",
        chunk_index=chunk_index,
        claim_text=claim_text,
        severity="MEDIUM",
        status="CONDITIONAL",
    )


# ----- Main entry -----


def run_deterministic(
    _extraction: ExtractionResult,
    chunk_text: str,
    chunk_index: int = 0,
    metadata: ChunkMetadata | None = None,
    claim_text: str = "",
) -> DeterministicResult:
    """
    Run deterministic Rule 5 formatting checks only.

    Claim-level rules (1, 2, 3, 6, 7, 8) are always evaluated by LLM in the pipeline
    when the chunk has at least one extracted claim.
    """
    violations: list[Violation] = []

    v5 = _check_rule5(metadata, chunk_index, claim_text)
    if v5:
        violations.append(v5)

    result = DeterministicResult(
        violations=violations,
        rules_still_needing_llm=[],
        projection_without_disclaimer=False,
    )
    logger.info(
        "deterministic_done chunk_index=%s violations=%s",
        chunk_index,
        len(result.violations),
    )
    return result