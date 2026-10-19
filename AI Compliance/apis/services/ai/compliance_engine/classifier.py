
import json
import logging
import os
import re
from typing import Dict, Any

from json_repair import repair_json  # pip install json-repair
from apis.services.ai.llm.client import get_llm_client
from apis.services.ai.core import config
from .rules.classifier_prompts import CLASSIFIER_SYSTEM, CLASSIFIER_USER

logger = logging.getLogger(__name__)

_SAFE_DEFAULT = {
    "is_in_scope": True,
    "detected_type": "educational_content",
    "reason": "Classifier fallback — defaulting to in-scope",
}


def _parse_classifier_response(response_text: str) -> dict:
    """
    Robustly extract JSON from the classifier LLM response.
    - Finds the outermost { ... } block using regex (handles markdown fences).
    - Falls back to json-repair if the JSON is malformed/truncated.
    - Returns the safe default if all parsing attempts fail.
    """
    if not response_text or not response_text.strip():
        logger.error("CLASSIFICATION_ERROR empty response from LLM")
        return _SAFE_DEFAULT

    # Extract the outermost JSON object
    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if not match:
        logger.error("CLASSIFICATION_ERROR no JSON object found: %s", response_text[:200])
        return _SAFE_DEFAULT

    json_str = match.group(0)

    # Try strict parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("CLASSIFICATION_JSON_ERROR %s — attempting repair", e.msg)

    # Fallback: attempt repair
    try:
        repaired = repair_json(json_str, return_objects=True)
        if isinstance(repaired, dict) and repaired:
            logger.info("CLASSIFICATION_JSON_REPAIRED")
            return repaired
    except Exception as repair_err:
        logger.error("CLASSIFICATION_REPAIR_FAILED: %s", repair_err)

    return _SAFE_DEFAULT


class ClassifierService:
    def __init__(self):
        # Classifier JSON is small, but thinking models spend part of the
        # output budget internally — keep headroom (~3k).
        model_id = config.CLASSIFIER_MODEL_ID
        # Safety: if provider is Vertex but classifier model looks Bedrock, force Gemini Flash.
        if config.LLM_PROVIDER == "vertexai" and str(model_id).startswith("meta."):
            model_id = config.VERTEX_CLASSIFIER_MODEL_ID
            logger.warning(
                "CLASSIFIER_MODEL_OVERRIDE provider=vertexai invalid_model=%s using=%s",
                config.CLASSIFIER_MODEL_ID,
                model_id,
            )
        self.client = get_llm_client(model_id=model_id)
        self._max_tokens = int(os.getenv("CLASSIFIER_MAX_TOKENS", "6000"))

    def _clean_text(self, text: str) -> str:
        """Strips HTML tags and normalizes whitespace for cleaner classification."""
        if not text:
            return ""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "html.parser")
            text = soup.get_text(separator=" ")
        except Exception:
            import re as _re
            text = _re.sub(r'<[^>]+>', ' ', text)
        return " ".join(text.split())

    def classify_document(self, document_text: str) -> Dict[str, Any]:
        """
        Classifies a document based on its text content.
        Strips HTML first and uses a larger sample of cleaned text.
        """
        cleaned_text = self._clean_text(document_text)
        sample_text = cleaned_text[:2500]

        try:
            response_text = self.client.invoke(
                system_prompt=CLASSIFIER_SYSTEM,
                user_prompt=CLASSIFIER_USER.format(document_text=sample_text),
                max_tokens=self._max_tokens,
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "is_in_scope": {"type": "boolean"},
                        "detected_type": {
                            "type": "string",
                            "enum": ["educational_content", "marketing_content", "other"],
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["is_in_scope", "detected_type", "reason"],
                },
                _label="document_classification",
            )

            result = _parse_classifier_response(response_text)

            # Ensure we only skip if BOTH is_in_scope is false AND type is 'other'
            # to prevent false-negative skips.
            if result.get("is_in_scope") is True or result.get("detected_type") != "other":
                result["is_in_scope"] = True
            else:
                result["is_in_scope"] = False

            logger.info(
                "CLASSIFICATION_RESULT in_scope=%s type=%s reason=%s",
                result.get("is_in_scope"),
                result.get("detected_type"),
                result.get("reason"),
            )
            return result

        except Exception as e:
            logger.exception("CLASSIFICATION_EXCEPTION: %s", str(e))
            # Default to in-scope to be safe if classifier fails
            return {
                "is_in_scope": True,
                "detected_type": "educational_content",
                "reason": f"Classifier error: {str(e)}",
            }