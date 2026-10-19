"""
Compliance evaluation engine.

4-Stage Architecture:
  1. Extraction & Deterministic pass
  2. Claim-Level Evaluation (Rules 1, 2, 3)
  3. Chunk-Level Tone Evaluation (Rules 6, 7, 8)
  4. Post-Aggregate Auditor (Rule 4)
"""

from .models import (
    ExtractionResult,
    Violation,
    ChunkResult,
    DocumentResult,
    DocumentMetrics,
)
from .extractor import extract_chunk
from .deterministic import run_deterministic, DeterministicResult
from .evaluator import evaluate_claims_for_rules, evaluate_balance_v2, get_combined_suggestion
from .pipeline import run_pipeline

__all__ = [
    "extract_chunk",
    "run_deterministic",
    "DeterministicResult",
    "evaluate_claims_for_rules",
    "evaluate_balance_v2",
    "get_combined_suggestion",
    "run_pipeline",
    "ExtractionResult",
    "Violation",
    "ChunkResult",
    "DocumentResult",
    "DocumentMetrics",
]
