"""
Extraction step: one LLM call per chunk to get claims with kind labels.
"""

import json
import logging
import re
from typing import Any, Protocol

from json_repair import repair_json  # pip install json-repair

from apis.services.ai.core import config
from .models import (
    VALID_CLAIM_KINDS,
    ClaimExtraction,
    ClaimKind,
    ExtractionResult,
)
from .rules.prompts import EXTRACTION_SYSTEM, EXTRACTION_USER

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Any client with invoke(system_prompt, user_prompt) -> str."""

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str: ...


def _strip_json_block(raw: str) -> str:
    """
    More robustly extract JSON from an LLM response.
    1. Finds the first '{' and the last '}'.
    2. Strips everything outside that range.
    This handles markdown code fences and conversational filler before/after the JSON.
    """
    text = raw.strip()
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        return match.group(0)
    return text


def _parse_extraction_response(raw: str) -> dict[str, Any]:
    """Parse LLM response into a normalized dict. Raises ValueError on failure."""
    text = _strip_json_block(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(
            "extraction_json_decode_error offset=%s msg=%s — attempting repair",
            e.pos, e.msg,
        )
        try:
            repaired = repair_json(text, return_objects=True)
            if isinstance(repaired, dict):
                logger.info("extraction_json_repair_success")
                return repaired
            if isinstance(repaired, list):
                logger.info("extraction_json_repair_success_list_wrapped")
                return {"claims": repaired}
            result = json.loads(repair_json(text))
            if isinstance(result, list):
                logger.info("extraction_json_repair_success_list_wrapped")
                return {"claims": result}
            logger.info("extraction_json_repair_success")
            return result
        except Exception as repair_err:
            logger.error(
                "extraction_json_repair_failed error=%s raw_preview=%s",
                repair_err, raw[:200],
            )
        raise ValueError(f"Invalid JSON from extraction LLM: {e}") from e


def _normalize_kind(raw: Any) -> list[ClaimKind]:
    """Normalize kind to a non-empty list of performance|risk|other|citation."""
    if raw is None:
        return ["other"]
    items = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, list) else []
    kinds: list[ClaimKind] = []
    for item in items:
        key = str(item).lower().strip()
        if key in VALID_CLAIM_KINDS and key not in kinds:
            kinds.append(key)  # type: ignore[arg-type]
    return kinds or ["other"]


def _dict_to_claim(c: dict[str, Any]) -> ClaimExtraction:
    return ClaimExtraction(
        claim_id=str(c.get("claim_id", "")),
        claim_text=str(c.get("claim_text", "")),
        kind=_normalize_kind(c.get("kind")),
    )


def extract_chunk(
    chunk_text: str,
    llm_client: LLMClient,
    *,
    section_identifier: str = "",
    doc_type: str = "",
    max_tokens: int = config.LLM_MAX_TOKENS,
    temperature: float = 0.2,
) -> ExtractionResult:
    """
    Run extraction LLM on one chunk. Returns claims with kind labels.

    :param chunk_text: Raw text (or HTML) of the chunk.
    :param llm_client: Client with .invoke(system_prompt, user_prompt) -> str.
    :param section_identifier: Optional context (e.g. page/section) for the prompt.
    :param doc_type: Optional document type for the prompt.
    :return: (ExtractionResult, raw_llm_response_text).
    """
    system_prompt = EXTRACTION_SYSTEM
    user_prompt = EXTRACTION_USER.replace("{chunk_text}", chunk_text)

    raw_response = llm_client.invoke(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        _label="extraction",
    )

    data = _parse_extraction_response(raw_response)
    if isinstance(data, list):
        data = {"claims": data}

    logger.info(
        "extraction_done claims=%s",
        len(data.get("claims") or []),
    )

    claims = []
    for item in data.get("claims") or []:
        try:
            claims.append(_dict_to_claim(item))
        except Exception as e:
            logger.warning("extraction_claim_skip item=%s error=%s", item, e)

    return ExtractionResult(
        claims=claims,
        raw=data,
    ), raw_response


def merge_extraction_results(
    primary: ExtractionResult | None,
    secondary: ExtractionResult | None,
) -> ExtractionResult | None:
    """
    Merge two extraction results (e.g. text chunk + chart image extraction).
    Claim IDs are reassigned by normalize_extraction_claim_ids after merge.
    """
    if primary is None and secondary is None:
        return None
    if primary is None:
        return secondary
    if secondary is None:
        return primary

    raw_merged = {"primary": primary.raw, "secondary": secondary.raw}

    return ExtractionResult(
        claims=list(primary.claims) + list(secondary.claims),
        raw=raw_merged,
    )
