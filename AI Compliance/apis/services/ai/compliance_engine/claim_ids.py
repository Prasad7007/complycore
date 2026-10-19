"""
Stable claim ID normalization after extraction.

Format: {doc_id}_chunk_{i}_claim_{j}  (0-based chunk and claim indices)
"""

import re

from .models import ClaimExtraction, ExtractionResult

_CLAIM_ID_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_document_id(document_id: str) -> str:
    """Normalize document_id for use inside claim_id strings."""
    if not document_id:
        return "unknown_doc"
    s = str(document_id).strip().replace(" ", "_")
    s = _CLAIM_ID_UNSAFE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown_doc"


def make_claim_id(document_id: str, chunk_index: int, claim_index: int) -> str:
    """Build a stable claim_id: {doc_id}_chunk_{i}_claim_{j}."""
    doc = sanitize_document_id(document_id)
    return f"{doc}_chunk_{chunk_index}_claim_{claim_index}"


def normalize_extraction_claim_ids(
    extraction: ExtractionResult | None,
    document_id: str,
    chunk_index: int,
) -> ExtractionResult | None:
    """
    Overwrite every claim's claim_id after extraction parse (LLM IDs are discarded).
    Claim order within the chunk is preserved (0-based claim index).
    """
    if extraction is None:
        return None

    normalized: list[ClaimExtraction] = []
    for claim_index, claim in enumerate(extraction.claims or []):
        normalized.append(
            claim.model_copy(
                update={
                    "claim_id": make_claim_id(document_id, chunk_index, claim_index),
                }
            )
        )
    extraction.claims = normalized
    return extraction
