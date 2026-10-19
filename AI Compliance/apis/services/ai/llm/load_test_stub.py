"""
UAT load-test LLM stub — simulates Vertex/Bedrock latency without API calls.

Enable only on UAT workers:
  LOAD_TEST_STUB_LLM=true
  LOAD_TEST_STUB_LLM_DELAY_SEC=1.5          # per invoke (default)
  LOAD_TEST_STUB_LLM_DELAY_PER_DOC_SEC=120  # optional: one sleep per worker task

Never enable when APP_ENV=production.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_TRUE = frozenset({"1", "true", "yes", "on"})

_local = threading.local()


def load_test_stub_enabled() -> bool:
    return os.getenv("LOAD_TEST_STUB_LLM", "").strip().lower() in _TRUE


def assert_stub_allowed() -> None:
    if not load_test_stub_enabled():
        return
    if os.getenv("APP_ENV", "development").strip().lower() == "production":
        raise RuntimeError(
            "LOAD_TEST_STUB_LLM is set but APP_ENV=production — refusing to start stub LLM"
        )


def reset_stub_sleep_state() -> None:
    """Call at the start of each Celery analysis task when using per-doc delay."""
    _local.slept = False


def _sleep_stub() -> None:
    per_doc = (os.getenv("LOAD_TEST_STUB_LLM_DELAY_PER_DOC_SEC") or "").strip()
    if per_doc:
        if getattr(_local, "slept", False):
            return
        delay = float(per_doc)
        _local.slept = True
    else:
        delay = float(os.getenv("LOAD_TEST_STUB_LLM_DELAY_SEC", "1.0"))
    if delay > 0:
        time.sleep(delay)


def stub_response_for_label(label: str) -> str:
    """Minimal JSON/text that keeps the compliance pipeline running."""
    if label == "document_classification":
        return json.dumps(
            {
                "is_in_scope": True,
                "detected_type": "educational_content",
                "reason": "load_test_stub",
            }
        )
    if label in ("extraction", "visual_extraction"):
        return json.dumps({"claims": []})
    if label == "combined_suggestion":
        return json.dumps({"combined_suggestion": ""})
    if label.startswith("rule_") and label.endswith("_eval"):
        return json.dumps([])
    return json.dumps({})


class LoadTestStubLLMClient:
    """Wraps a real client but never calls the provider when stub is active."""

    def __init__(self, inner: Any):
        self._inner = inner

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str:
        label = str(kwargs.pop("_label", "invoke"))
        _sleep_stub()
        out = stub_response_for_label(label)
        logger.info("LOAD_TEST_STUB_LLM invoke label=%s out_chars=%s", label, len(out))
        return out

    def invoke_with_image(self, *args: Any, **kwargs: Any) -> str:
        label = str(kwargs.pop("_label", "invoke_with_image"))
        _sleep_stub()
        out = stub_response_for_label(label if label != "invoke_with_image" else "visual_extraction")
        logger.info("LOAD_TEST_STUB_LLM invoke_with_image label=%s out_chars=%s", label, len(out))
        return out


def log_stub_startup() -> None:
    if not load_test_stub_enabled():
        return
    assert_stub_allowed()
    per_doc = (os.getenv("LOAD_TEST_STUB_LLM_DELAY_PER_DOC_SEC") or "").strip()
    per_call = os.getenv("LOAD_TEST_STUB_LLM_DELAY_SEC", "1.0")
    mode = f"per_doc={per_doc}s" if per_doc else f"per_call={per_call}s"
    logger.warning(
        "LOAD_TEST_STUB_LLM ACTIVE — no Vertex/Bedrock calls; delay mode: %s",
        mode,
    )
