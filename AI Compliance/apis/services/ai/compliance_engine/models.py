"""
Pydantic models for the compliance engine.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Tri-state for compliance decisions (regulator-ready)
ComplianceStatus = Literal["APPROVE", "CONDITIONAL", "REJECT"]


# ----- Extraction (LLM output) -----


class LanguageIndicators(BaseModel):
    """Terms extracted for structured compliance checking (optimized for Stage 2-4)."""

    absolutes: list[str] = Field(default_factory=list)
    qualifiers: list[str] = Field(default_factory=list)
    superlatives: list[str] = Field(default_factory=list)
    emotional: list[str] = Field(default_factory=list)
    forward_looking: list[str] = Field(default_factory=list)
    risk_terms: list[str] = Field(default_factory=list)
    evidence_markers: list[str] = Field(default_factory=list)
    # Optimized: merged leverage and derivative; renamed guarantee
    leverage_derivative: list[str] = Field(default_factory=list)
    guarantee_verbs: list[str] = Field(default_factory=list)
    universal_quantifiers: list[str] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


ClaimKind = Literal["performance", "risk", "other", "citation"]
VALID_CLAIM_KINDS: frozenset[str] = frozenset({"performance", "risk", "other", "citation"})


class ClaimExtraction(BaseModel):
    """Single claim extracted from a chunk."""

    claim_id: str
    claim_text: str
    kind: list[ClaimKind] = Field(default_factory=lambda: ["other"])

    def has_kind(self, name: str) -> bool:
        return name.lower() in {k.lower() for k in self.kind}


class ExtractionResult(BaseModel):
    """Output of the extraction LLM call (per chunk)."""

    claims: list[ClaimExtraction] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


# ----- Formatting metadata (from HTML parsing) -----


class ChunkMetadata(BaseModel):
    """Metadata for deterministic Rule 5 (formatting)."""

    disclaimer_font_size: float | None = None
    claim_font_size: float | None = None
    disclaimer_distance_chars: int | None = None
    disclaimer_distance_pixels: int | None = None
    is_heading: bool = False
    is_bold: bool = False
    section_identifier: str = ""


# ----- Violations and results -----


class Violation(BaseModel):
    """A single compliance finding (APPROVE / CONDITIONAL / REJECT)."""

    # Allow field mutation so pipeline.py can set suggested_alternative after creation
    model_config = ConfigDict(frozen=False)

    rule: int
    rule_name: str = ""
    claim_text: str = ""  # Full claim that triggered violation
    claim_id: str = ""  # ID of the claim
    problematic_phrase: str = ""  # Specific keyword/phrase that violated (e.g., "guaranteed")
    chunk_index: int = 0
    status: ComplianceStatus = "REJECT"  # APPROVE = pass, CONDITIONAL = needs fix, REJECT = violation
    compliant: bool = False  # True only when status == APPROVE (backward compat)
    reasoning: str = ""
    severity: str = "MEDIUM"
    method: str = "llm"
    failed_step: int | None = None
    # Reviewer-ready (optional, from LLM)
    what_was_checked: str = ""
    evidence_assumed: str = ""
    would_break_compliance: str = ""
    suggested_alternative: str = ""  # NEW: AI-generated compliant replacement text



class ClaimResult(BaseModel):
    """Aggregated compliance result for a single claim across all rules."""
    
    claim_id: str
    claim_text: str
    chunk_index: int
    rules_violated: list[int] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    combined_suggestion: str = ""


class ChunkResult(BaseModel):
    """Result of evaluating one chunk."""

    chunk_index: int
    chunk_text: str = ""
    extraction: ExtractionResult | None = None
    claim_results: list[ClaimResult] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    deterministic_flags: list[Violation] = Field(default_factory=list)
    # Per-stage raw LLM responses keyed by stage name:
    # "extraction", "claim_eval", "tone_eval", "auditor"
    llm_responses: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    projection_without_disclaimer: bool = False  # v2: for document-layer aggregation


class DocumentMetrics(BaseModel):
    """Document-level kind counts for Rule 4 (fair & balanced)."""

    total_claims: int = 0
    total_performance_claims: int = 0
    total_risk_claims: int = 0
    total_other_claims: int = 0
    performance_to_risk_ratio: float = 0.0
    repetition_frequency_map: dict[str, int] = Field(default_factory=dict)

    @property
    def total_risk_mentions(self) -> int:
        """Backward-compatible alias for total_risk_claims."""
        return self.total_risk_claims


class DocumentResult(BaseModel):
    """Result of evaluating a full document."""

    chunks_processed: int = 0
    claim_results: list[ClaimResult] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    chunk_results: list[ChunkResult] = Field(default_factory=list)
    projection_without_disclaimer_count: int = 0  # v2: kept for backward compat; also in document_metrics
    document_metrics: DocumentMetrics | None = None  # v2: full document metrics layer