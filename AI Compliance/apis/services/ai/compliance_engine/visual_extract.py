"""
Gemini vision extraction for chart / table / figure images — same JSON schema as ``extract_chunk``.

Candidate selection (which images to call) lives in ``apis.services.ai.processing.visual_document``.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from apis.services.ai.core import config

from .extractor import _dict_to_claim, _parse_extraction_response
from .models import ExtractionResult

logger = logging.getLogger(__name__)


class VisionLLMClient(Protocol):
    def invoke_with_image(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        mime_type: str,
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = 0.2,
        _label: str = "",
        **kwargs: Any,
    ) -> str: ...


VISUAL_EXTRACTION_SYSTEM = (
    "You are a Canadian financial marketing compliance analyst. "
    "The user attaches a chart, figure, or image from retail investment marketing material. "
    "Output valid JSON only, no markdown or explanation."
)

VISUAL_EXTRACTION_USER = """
TASK: From the attached image, extract structured compliance data using the SAME rules
as for a text chunk.

NEARBY DOCUMENT CONTEXT (may be empty):
\"\"\"
{caption}
\"\"\"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXTRACT CLAIMS FROM THE VISUAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Prefer regulatory-relevant assertions from visible text (titles, labels, legends, table headers/cells).
If no explicit sentence claim is visible but the visual clearly shows numeric evidence
(e.g. fund vs benchmark values, returns, ranking, period), extract concise evidence-backed claims.

When inferring from chart/table numbers:
- Keep claim_text short and factual (no marketing tone).
- Include metric + period when available (e.g., "Fund return is 10.2% vs benchmark 8.1% since inception").
- Do NOT invent values that are not visible.
- If the image is unreadable, return empty claims.

For each claim include claim_id (placeholder), claim_text, and kind (performance | risk | other).

OUTPUT (JSON only):

{{
  "claims": [
    {{
      "claim_id": "placeholder",
      "claim_text": "verbatim or concise factual claim",
      "kind": ["performance"]
    }}
  ]
}}

Return ONLY valid JSON.
"""


def extract_claims_from_chart_image(
    image_bytes: bytes,
    llm_client: VisionLLMClient,
    *,
    caption: str = "",
    mime_type: str = "image/png",
    max_tokens: int = config.LLM_MAX_TOKENS,
    temperature: float = 0.2,
) -> ExtractionResult | None:
    """
    Run vision extraction on one image. Returns None if client has no invoke_with_image
    or on hard failure.
    """
    if not image_bytes or not hasattr(llm_client, "invoke_with_image"):
        return None

    user_prompt = VISUAL_EXTRACTION_USER.format(caption=caption or "")

    try:
        raw = llm_client.invoke_with_image(
            system_prompt=VISUAL_EXTRACTION_SYSTEM,
            user_prompt=user_prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            max_tokens=max_tokens,
            temperature=temperature,
            _label="visual_extraction",
        )
    except Exception as e:
        logger.warning("visual_extract_invoke_failed error=%s", e)
        return None

    try:
        data = _parse_extraction_response(raw)
    except Exception as e:
        logger.warning("visual_extract_json_failed error=%s", e)
        return None

    claims = []
    for item in data.get("claims") or []:
        try:
            claims.append(_dict_to_claim(item))
        except Exception as e:
            logger.warning("visual_extract_claim_skip item=%s error=%s", item, e)

    return ExtractionResult(
        claims=claims,
        raw=data,
    )
