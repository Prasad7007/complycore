"""
LLM client abstraction — supports AWS Bedrock and GCP Vertex AI (Gemini 2.5 Flash).

Provider is selected at runtime via the LLM_PROVIDER env var:
  LLM_PROVIDER=bedrock   → BedrockClient  (default)
  LLM_PROVIDER=vertexai  → VertexAIClient (Gemini 2.5 Flash)

GCP auth (Option B — inline JSON):
  Set VERTEX_CREDENTIALS_JSON to the full contents of a GCP service-account
  JSON key file. The client deserialises the string into a Credentials object,
  so no file path on disk is needed.
"""

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# Load .env so env vars are available when running from different roots.
# Search order:
# 1) repo root: <workspace>/.env
# 2) backend root: <workspace>/AI Compliance/.env
try:
    from dotenv import load_dotenv

    _this = Path(__file__).resolve()
    _candidates = [
        _this.parents[5] / ".env",  # compliance_ai_clean/.env
        _this.parents[4] / ".env",  # AI Compliance/.env
    ]
    for _env_path in _candidates:
        if _env_path.exists():
            load_dotenv(_env_path, override=False)
            logger.info("dotenv_loaded path=%s", _env_path)
            break
except ImportError:
    pass

from apis.services.ai.core import config

BEDROCK_MODEL_ID = config.BEDROCK_MODEL_ID
AWS_REGION = config.AWS_REGION


# ── Protocol / base ───────────────────────────────────────────────

class LLMClient:
    """Common interface that all LLM client implementations must satisfy."""

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str:  # pragma: no cover
        raise NotImplementedError


# ── AWS Bedrock ───────────────────────────────────────────────────

class BedrockClient(LLMClient):
    """Client for invoking Bedrock models via the Converse API."""

    def __init__(
        self,
        model_id: str | None = None,
        region_name: str | None = None,
    ):
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", BEDROCK_MODEL_ID)
        self.region_name = region_name or os.environ.get("AWS_REGION", AWS_REGION)

        retry_config = Config(
            retries={"max_attempts": 10, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=60,
        )
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self.region_name,
            config=retry_config,
        )

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str:
        """Send system + user prompt to Bedrock and return the model's text response."""
        request_payload = {
            "modelId": self.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user_prompt}],
                }
            ],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if kwargs:
            request_payload["inferenceConfig"].update(
                {k: v for k, v in kwargs.items() if k in ("topP", "stopSequences", "topK")}
            )

        input_len = len(system_prompt) + len(user_prompt)
        label = kwargs.pop("_label", "invoke")
        logger.info(
            "bedrock_invoke_start label=%s model_id=%s input_chars=%s max_tokens=%s",
            label, self.model_id, input_len, max_tokens,
        )
        start = time.perf_counter()

        try:
            response = self._client.converse(**request_payload)
        except (ClientError, BotoCoreError) as e:
            error_code = ""
            if isinstance(e, ClientError):
                error_code = e.response.get("Error", {}).get("Code", "")

            # NOTE: Graceful throttle swallowing is intentionally commented out
            # so raw throttle errors are visible during model performance testing.
            # Uncomment the block below to restore silent-warning behaviour.
            # if error_code in ("ThrottlingException", "RequestLimitExceeded"):
            #     logger.warning(
            #         "bedrock_throttled label=%s model_id=%s error=%s (pipeline will continue)",
            #         label, self.model_id, str(e),
            #     )
            # else:

            logger.exception(
                "bedrock_invoke_error model_id=%s error_code=%s error=%s",
                self.model_id, error_code, str(e),
            )
            raise

        elapsed = time.perf_counter() - start
        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])
        text_parts = [
            block["text"]
            for block in content_blocks
            if isinstance(block, dict) and "text" in block
        ]
        output_text = "".join(text_parts)

        usage = response.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)

        logger.info(
            "bedrock_invoke_done label=%s elapsed_sec=%.2f input_tokens=%s output_tokens=%s output_chars=%s",
            label, elapsed, input_tokens, output_tokens, len(output_text),
        )
        logger.debug("[%s] RESPONSE RECEIVED:\n%s", label, output_text)
        return output_text


# ── GCP Vertex AI (Gemini 2.5 Flash) ─────────────────────────────

class VertexAIClient(LLMClient):
    """
    Client for invoking Gemini models on GCP Vertex AI.

    Authentication (Option B — inline JSON):
      Set VERTEX_CREDENTIALS_JSON to the full contents of a GCP service-account
      JSON key file. The credentials are deserialised from the string so that no
      key file needs to be written to disk, making it safe for containers and
      secrets managers.
    """

    def __init__(
        self,
        model_id: str | None = None,
        project: str | None = None,
        location: str | None = None,
    ):
        self.model_id = model_id or os.environ.get("VERTEX_MODEL_ID", config.VERTEX_MODEL_ID)
        self.project = project or os.environ.get("VERTEX_PROJECT_ID", config.VERTEX_PROJECT_ID)
        self.location = location or os.environ.get("VERTEX_LOCATION", config.VERTEX_LOCATION)

        if not self.project:
            raise ValueError(
                "VERTEX_PROJECT_ID is required for VertexAIClient. "
                "Set it in your .env file or environment."
            )

        credentials = self._build_credentials()
        self._init_vertexai(credentials)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_credentials(self):
        """
        Deserialise the inline service-account JSON string into a
        google.oauth2.service_account.Credentials object.
        Falls back to Application Default Credentials if the env var is empty
        (useful for local dev authenticated via `gcloud auth application-default login`).
        """
        creds_json_str = os.environ.get("VERTEX_CREDENTIALS_JSON", config.VERTEX_CREDENTIALS_JSON)
        if not creds_json_str:
            logger.info(
                "VERTEX_CREDENTIALS_JSON not set — falling back to Application Default Credentials"
            )
            return None  # vertexai.init() will use ADC automatically

        try:
            from google.oauth2 import service_account  # type: ignore

            creds_info = json.loads(creds_json_str)
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            credentials = service_account.Credentials.from_service_account_info(
                creds_info, scopes=scopes
            )
            logger.info("vertexai_credentials_loaded via inline JSON (service account: %s)",
                        creds_info.get("client_email", "unknown"))
            return credentials
        except Exception as exc:
            logger.exception("vertexai_credentials_error error=%s", str(exc))
            raise

    def _init_vertexai(self, credentials):
        """
        Initialise the vertexai SDK with project, location, and credentials.

        The api_endpoint is pinned explicitly to the regional endpoint
        (e.g. northamerica-northeast1-aiplatform.googleapis.com) so that
        API traffic is provably routed to the chosen region — data residency
        is enforced at the network level, not just inferred by the SDK.
        """
        try:
            import vertexai  # type: ignore

            # Pin to the regional API endpoint — critical for data residency.
            # Format: <location>-aiplatform.googleapis.com
            regional_endpoint = f"{self.location}-aiplatform.googleapis.com"

            vertexai.init(
                project=self.project,
                location=self.location,
                credentials=credentials,
                api_endpoint=regional_endpoint,
            )
            logger.info(
                "vertexai_init project=%s location=%s model_id=%s api_endpoint=%s",
                self.project, self.location, self.model_id, regional_endpoint,
            )
        except ImportError as exc:
            raise ImportError(
                "google-cloud-aiplatform is required for VertexAIClient. "
                "Install it with: pip install google-cloud-aiplatform"
            ) from exc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = 0,
        **kwargs: Any,
    ) -> str:
        """Send system + user prompt to Vertex AI Gemini and return the text response.

        Uses streaming (stream=True) to reduce time-to-first-token and
        avoid gRPC timeouts on large responses.
        """
        from vertexai.generative_models import (  # type: ignore
            GenerationConfig,
            GenerativeModel,
        )

        label = kwargs.pop("_label", "invoke")
        response_mime_type = kwargs.pop("response_mime_type", None)
        response_schema = kwargs.pop("response_schema", None)
        input_len = len(system_prompt) + len(user_prompt)
        logger.info(
            "vertexai_invoke_start label=%s model_id=%s input_chars=%s max_tokens=%s",
            label, self.model_id, input_len, max_tokens,
        )
        start = time.perf_counter()

        try:
            model = GenerativeModel(
                model_name=self.model_id,
                system_instruction=system_prompt,
            )

            # Thinking budget — set to 0 to disable, or a positive int to allow.
            try:
                from vertexai.generative_models import ThinkingConfig  # type: ignore
                thinking_cfg = {"thinking_config": ThinkingConfig(thinking_budget=1024)}
            except (ImportError, AttributeError):
                thinking_cfg = {}

            generation_config_kwargs: dict[str, Any] = {
                "max_output_tokens": max_tokens,
                "temperature": temperature,
                **thinking_cfg,
            }
            if response_mime_type:
                generation_config_kwargs["response_mime_type"] = response_mime_type
            if response_schema is not None:
                generation_config_kwargs["response_schema"] = response_schema

            try:
                generation_config = GenerationConfig(**generation_config_kwargs)
            except ValueError as schema_err:
                # Vertex schema support varies by SDK version; retry without schema constraints
                # instead of failing the entire inference call.
                if "Unknown field for Schema" in str(schema_err) and "response_schema" in generation_config_kwargs:
                    logger.warning(
                        "vertexai_schema_unsupported label=%s error=%s retrying_without_schema",
                        label,
                        schema_err,
                    )
                    generation_config_kwargs.pop("response_schema", None)
                    generation_config = GenerationConfig(**generation_config_kwargs)
                else:
                    raise

            # ── Streaming with Exponential Backoff Retry for 429 ─────────
            max_retries = 6
            backoff = 2.0
            for attempt in range(1, max_retries + 1):
                try:
                    chunks: list[str] = []
                    finish_reason = "unknown"
                    usage = None

                    for chunk in model.generate_content(
                        user_prompt,
                        generation_config=generation_config,
                        stream=True,
                    ):
                        # Each chunk may have text
                        try:
                            if chunk.text:
                                chunks.append(chunk.text)
                        except (ValueError, AttributeError):
                            pass  # Some chunks have no text (e.g. thinking-only)

                        # The last chunk carries finish_reason and usage
                        try:
                            finish_reason = chunk.candidates[0].finish_reason.name
                        except Exception:
                            pass
                        if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                            usage = chunk.usage_metadata

                    output_text = "".join(chunks)
                    break
                except Exception as stream_err:
                    err_msg = str(stream_err).lower()
                    is_rate_limit = (
                        "429" in err_msg
                        or "resourceexhausted" in err_msg
                        or "resource_exhausted" in err_msg
                        or "quota" in err_msg
                    )
                    if is_rate_limit and attempt < max_retries:
                        sleep_s = backoff * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                        logger.warning(
                            "vertexai_rate_limited label=%s attempt=%s/%s sleeping=%.1fs error=%s",
                            label, attempt, max_retries, sleep_s, str(stream_err),
                        )
                        time.sleep(sleep_s)
                    else:
                        raise

            if finish_reason not in ("STOP", "1"):
                logger.warning(
                    "vertexai_unexpected_finish label=%s finish_reason=%s "
                    "(JSON may be truncated)",
                    label, finish_reason,
                )

        except Exception as exc:
            logger.exception(
                "vertexai_invoke_error model_id=%s error=%s",
                self.model_id, str(exc),
            )
            raise

        elapsed = time.perf_counter() - start

        # Token usage (available on the last chunk's usage_metadata)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        logger.info(
            "vertexai_invoke_done label=%s elapsed_sec=%.2f input_tokens=%s output_tokens=%s output_chars=%s",
            label, elapsed, input_tokens, output_tokens, len(output_text),
        )
        logger.debug("[%s] RESPONSE RECEIVED:\n%s", label, output_text)
        return output_text

    def invoke_with_image(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = 0,
        **kwargs: Any,
    ) -> str:
        """Multimodal: one image + text prompts. Returns model text (e.g. JSON)."""
        from vertexai.generative_models import (  # type: ignore
            GenerationConfig,
            GenerativeModel,
            Part,
        )

        label = kwargs.pop("_label", "invoke_with_image")
        logger.info(
            "vertexai_invoke_with_image_start label=%s model_id=%s image_bytes=%s mime=%s",
            label,
            self.model_id,
            len(image_bytes),
            mime_type,
        )
        start = time.perf_counter()

        try:
            model = GenerativeModel(
                model_name=self.model_id,
                system_instruction=system_prompt,
            )
            try:
                from vertexai.generative_models import ThinkingConfig  # type: ignore

                thinking_cfg = {"thinking_config": ThinkingConfig(thinking_budget=1024)}
            except (ImportError, AttributeError):
                thinking_cfg = {}

            generation_config = GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
                **thinking_cfg,
            )

            image_part = Part.from_data(data=image_bytes, mime_type=mime_type)
            contents: list[Any] = [user_prompt, image_part]

            max_retries = 6
            backoff = 2.0
            for attempt in range(1, max_retries + 1):
                try:
                    chunks: list[str] = []
                    finish_reason = "unknown"
                    usage = None

                    for chunk in model.generate_content(
                        contents,
                        generation_config=generation_config,
                        stream=True,
                    ):
                        try:
                            if chunk.text:
                                chunks.append(chunk.text)
                        except (ValueError, AttributeError):
                            pass
                        try:
                            finish_reason = chunk.candidates[0].finish_reason.name
                        except Exception:
                            pass
                        if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                            usage = chunk.usage_metadata

                    output_text = "".join(chunks)
                    break
                except Exception as stream_err:
                    err_msg = str(stream_err).lower()
                    is_rate_limit = (
                        "429" in err_msg
                        or "resourceexhausted" in err_msg
                        or "resource_exhausted" in err_msg
                        or "quota" in err_msg
                    )
                    if is_rate_limit and attempt < max_retries:
                        sleep_s = backoff * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                        logger.warning(
                            "vertexai_invoke_with_image_rate_limited label=%s attempt=%s/%s sleeping=%.1fs error=%s",
                            label, attempt, max_retries, sleep_s, str(stream_err),
                        )
                        time.sleep(sleep_s)
                    else:
                        raise

            if finish_reason not in ("STOP", "1"):
                logger.warning(
                    "vertexai_invoke_with_image_finish label=%s finish_reason=%s",
                    label,
                    finish_reason,
                )
        except Exception as exc:
            logger.exception(
                "vertexai_invoke_with_image_error model_id=%s error=%s",
                self.model_id,
                str(exc),
            )
            raise

        elapsed = time.perf_counter() - start
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        logger.info(
            "vertexai_invoke_with_image_done label=%s elapsed_sec=%.2f in_tok=%s out_tok=%s out_chars=%s",
            label,
            elapsed,
            input_tokens,
            output_tokens,
            len(output_text),
        )
        return output_text


# ── Factory ───────────────────────────────────────────────────────

def get_llm_client(
    provider: str | None = None,
    model_id: str | None = None,
) -> LLMClient:
    """
    Return the appropriate LLM client based on the LLM_PROVIDER env var.

    Args:
        provider:  Override the env var. One of "bedrock" | "vertexai".
        model_id:  Optional model override (passed through to the client).

    Returns:
        BedrockClient  if provider is "bedrock"  (or not set)
        VertexAIClient if provider is "vertexai"

    Usage:
        from apis.services.ai.llm.client import get_llm_client
        client = get_llm_client()          # reads LLM_PROVIDER from env
        response = client.invoke(system_prompt=..., user_prompt=...)
    """
    resolved = (provider or os.environ.get("LLM_PROVIDER", config.LLM_PROVIDER)).lower().strip()
    logger.debug("get_llm_client provider=%s model_id=%s", resolved, model_id)

    from apis.services.ai.llm.load_test_stub import (
        LoadTestStubLLMClient,
        assert_stub_allowed,
        load_test_stub_enabled,
    )

    if load_test_stub_enabled():
        assert_stub_allowed()
        logger.info(
            "get_llm_client STUB ONLY provider=%s — no Vertex/Bedrock client, no provider API calls",
            resolved,
        )
        return LoadTestStubLLMClient(None)  # type: ignore[return-value]

    if resolved == "vertexai":
        return VertexAIClient(model_id=model_id)

    return BedrockClient(model_id=model_id)


# ── Quick smoke-test ──────────────────────────────────────────────

if __name__ == "__main__":
    resolved = os.environ.get("LLM_PROVIDER", config.LLM_PROVIDER)
    print(f"Testing provider (from env / config): {resolved}")

    client = get_llm_client()
    output = client.invoke(
        system_prompt="You are a helpful assistant.",
        user_prompt="What is the capital of India? Reply in one short sentence.",
        max_tokens=256,
        temperature=0.1,
    )
    print(output)