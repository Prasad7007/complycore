#!/usr/bin/env python3
"""
Standalone orchestration runner: existing compliance pipeline + Langfuse traces.

Does NOT modify application code. Reuses Chunker, ClassifierService, run_pipeline,
and (optionally) visual extraction from the AI Compliance package.

Usage (from repo root, venv active):

  # One Docling folder under 3.5_Migration/docling_outputs/
  python langfuse_runner.py --doc "BLOG - Data & Measurement"

  # Explicit path to output.html (or its parent folder)
  python langfuse_runner.py --doc "/path/to/.../output.html"

  # All folders that contain output.html
  python langfuse_runner.py --all

  # Limit chunks / include chart vision merge / force pipeline even if out-of-scope
  python langfuse_runner.py --doc "..." --max-chunks 3 --with-visual --force-pipeline

  # Extraction only (no rules / no classifier gate)
  python langfuse_runner.py --doc "..." --extraction-only

  Extraction JSON is always written under:
    3.5_Migration/extraction_outputs/<doc_name>/chunk_000.json ...

  # Model (default: gemini-3.5-flash — overrides VERTEX_MODEL_ID from .env for this run)
  python langfuse_runner.py --doc "..." --model gemini-3.5-flash

  # Save final UI-shaped analysis JSON (for comparing against 3.5_Migration/analysis_results)
  python langfuse_runner.py --doc "..." --save-to
  python langfuse_runner.py --doc "..." --save-to 3.5_Migration/analysis_results_2.0

  # New document: Docling parse → save under docling_outputs → run full pipeline
  python langfuse_runner.py --from-source "/path/to/blog.pdf" --save-to
  python langfuse_runner.py --from-source "/path/to/blog.docx" --doc-name "My Blog Title" --save-to

Requires LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL (or
LANGFUSE_HOST) in the repo .env, plus the usual LLM_* / VERTEX_* vars in
AI Compliance/.env.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_SOURCE_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
_OFFICE_CONVERT_EXTENSIONS = {".doc", ".ppt"}

from dotenv import load_dotenv

# ── Paths & env (must load before importing Langfuse / app) ───────────────────
_REPO_ROOT = Path(__file__).resolve().parent
_AI_ROOT = _REPO_ROOT / "AI Compliance"
_DEFAULT_DOCLING = _REPO_ROOT / "3.5_Migration" / "docling_outputs"
_DEFAULT_EXTRACTION_OUT = _REPO_ROOT / "3.5_Migration" / "extraction_outputs"
_DEFAULT_ANALYSIS_RESULTS_OUT = _REPO_ROOT / "3.5_Migration" / "analysis_results_2.0"
_DEFAULT_MODEL = "gemini-3.5-flash"

load_dotenv(_REPO_ROOT / ".env", override=False)
load_dotenv(_AI_ROOT / ".env", override=False)
load_dotenv(_AI_ROOT / ".env.docker", override=False)

# SDK accepts LANGFUSE_HOST or base_url; project .env uses LANGFUSE_BASE_URL
if not os.getenv("LANGFUSE_HOST") and os.getenv("LANGFUSE_BASE_URL"):
    os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]

# Force runner model before app config is imported (classifier + pipeline read these).
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument(
    "--model",
    default=os.getenv("LANGFUSE_RUNNER_MODEL", _DEFAULT_MODEL),
    help=f"Vertex model id (default: {_DEFAULT_MODEL})",
)
_early_args, _ = _pre.parse_known_args()
_RUNNER_MODEL = (_early_args.model or _DEFAULT_MODEL).strip()
os.environ["VERTEX_MODEL_ID"] = _RUNNER_MODEL
os.environ["CLASSIFIER_MODEL_ID"] = _RUNNER_MODEL
os.environ["VERTEX_CLASSIFIER_MODEL_ID"] = _RUNNER_MODEL
os.environ.setdefault("LLM_PROVIDER", "vertexai")

if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from langfuse import get_client, propagate_attributes  # noqa: E402

from apis.services.ai.compliance_engine.claim_ids import (  # noqa: E402
    normalize_extraction_claim_ids,
    sanitize_document_id,
)
from apis.services.ai.compliance_engine.classifier import ClassifierService  # noqa: E402
from apis.services.ai.compliance_engine.extractor import extract_chunk  # noqa: E402
from apis.services.ai.compliance_engine.models import DocumentResult, Violation  # noqa: E402
from apis.services.ai.compliance_engine.pipeline import run_pipeline  # noqa: E402
from apis.services.ai.llm.client import get_llm_client  # noqa: E402
from apis.services.ai.processing.chunking import Chunker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("langfuse_runner")

_MAX_IO_CHARS = None  # None = never truncate Langfuse I/O


def _truncate(value: Any, limit: int | None = _MAX_IO_CHARS) -> Any:
    """Pass-through for Langfuse payloads (full traces). limit ignored unless set."""
    if value is None:
        return None
    if limit is None:
        if isinstance(value, (dict, list)):
            return value
        return value if isinstance(value, (str, int, float, bool)) else str(value)
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= limit:
            return value
        return text[:limit] + f"… [truncated {len(text) - limit} chars]"
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [truncated {len(text) - limit} chars]"


def _serialize_result(result: Any) -> dict[str, Any]:
    """Compact DocumentResult (or similar) for Langfuse output."""
    if result is None:
        return {}
    if hasattr(result, "model_dump"):
        data = result.model_dump()
    elif isinstance(result, dict):
        data = result
    else:
        return {"repr": _truncate(result)}

    violations = data.get("violations") or []
    compact_violations = [
        {
            "rule": v.get("rule"),
            "rule_name": v.get("rule_name"),
            "severity": v.get("severity"),
            "chunk_index": v.get("chunk_index"),
            "claim_id": v.get("claim_id"),
            "claim_text": _truncate(v.get("claim_text"), 400),
            "problematic_phrase": _truncate(v.get("problematic_phrase"), 200),
            "reasoning": _truncate(v.get("reasoning"), 500),
            "method": v.get("method"),
        }
        for v in violations
    ]
    chunk_summaries = []
    for cr in data.get("chunk_results") or []:
        ext = cr.get("extraction") or {}
        claims = ext.get("claims") or []
        chunk_summaries.append(
            {
                "chunk_index": cr.get("chunk_index"),
                "error": cr.get("error"),
                "n_claims": len(claims),
                "n_violations": len(cr.get("violations") or []),
                "llm_response_keys": list((cr.get("llm_responses") or {}).keys()),
                "claims_preview": [
                    {
                        "claim_id": c.get("claim_id"),
                        "claim_text": _truncate(c.get("claim_text"), 300),
                        "kind": c.get("kind"),
                    }
                    for c in claims[:8]
                ],
            }
        )
    return {
        "chunks_processed": data.get("chunks_processed"),
        "n_violations": len(violations),
        "violations": compact_violations,
        "document_metrics": data.get("document_metrics"),
        "chunk_summaries": chunk_summaries,
    }


class TracingLLMClient:
    """
    Thin proxy around the real LLM client.

    Each invoke() / invoke_with_image() becomes a Langfuse *generation* child of
    the active pipeline span (works across ThreadPoolExecutor threads because
    children are created via parent.start_observation, not OTEL context alone).
    """

    def __init__(self, inner: Any, parent_span: Any):
        self._inner = inner
        self._parent = parent_span
        # Preserve attributes used by the pipeline / documents router
        self.MAX_CHUNKS = getattr(inner, "MAX_CHUNKS", None)
        self.model_id = getattr(inner, "model_id", None)

    def _start_generation(self, name: str, input_payload: Any):
        return self._parent.start_observation(
            name=name,
            as_type="generation",
            model=str(self.model_id or os.getenv("VERTEX_MODEL_ID") or os.getenv("LLM_PROVIDER") or "llm"),
            input=_truncate(input_payload),
        )

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
        label = str(kwargs.pop("_label", None) or "llm_invoke")
        # ChatML message list so Langfuse "Test in LLM Playground" works
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        gen = self._start_generation(label, messages)
        try:
            out = self._inner.invoke(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                **kwargs,
            )
            text_out = out if isinstance(out, str) else str(out)
            gen.update(output=text_out)
            return out
        except Exception as e:
            gen.update(level="ERROR", status_message=str(e))
            raise
        finally:
            gen.end()

    def invoke_with_image(self, *args: Any, **kwargs: Any) -> Any:
        if not hasattr(self._inner, "invoke_with_image"):
            raise AttributeError("inner LLM client has no invoke_with_image")
        label = str(kwargs.pop("_label", None) or "visual_extraction")
        # Avoid dumping raw image bytes into Langfuse
        safe_kwargs = {
            k: ("<bytes>" if isinstance(v, (bytes, bytearray)) else v)
            for k, v in kwargs.items()
        }
        gen = self._start_generation(label, {"args_len": len(args), "kwargs": safe_kwargs})
        try:
            out = self._inner.invoke_with_image(*args, **kwargs)
            gen.update(output=out if isinstance(out, str) else str(out))
            return out
        except Exception as e:
            gen.update(level="ERROR", status_message=str(e))
            raise
        finally:
            gen.end()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def resolve_html_path(doc_arg: str, docling_root: Path) -> Path:
    """Resolve --doc to an output.html path."""
    p = Path(doc_arg).expanduser()
    if p.is_file() and p.name == "output.html":
        return p.resolve()
    if p.is_dir() and (p / "output.html").is_file():
        return (p / "output.html").resolve()

    candidate = docling_root / doc_arg
    if candidate.is_dir() and (candidate / "output.html").is_file():
        return (candidate / "output.html").resolve()
    if candidate.is_file():
        return candidate.resolve()

    raise FileNotFoundError(
        f"Could not find Docling HTML for {doc_arg!r}. "
        f"Expected a folder under {docling_root} with output.html, "
        f"or a direct path to output.html."
    )


def list_docling_docs(docling_root: Path) -> list[Path]:
    if not docling_root.is_dir():
        raise FileNotFoundError(f"Docling outputs dir not found: {docling_root}")
    docs: list[Path] = []
    for child in sorted(docling_root.iterdir()):
        html = child / "output.html"
        if child.is_dir() and html.is_file():
            docs.append(html)
    return docs


def _prepare_docling_input(source_path: Path) -> tuple[Path, Any | None]:
    """Return a path Parsing can read; convert legacy .doc/.ppt to PDF when needed."""
    suffix = source_path.suffix.lower()
    if suffix not in _SOURCE_EXTENSIONS:
        supported = ", ".join(sorted(_SOURCE_EXTENSIONS))
        raise ValueError(f"Unsupported source type {suffix!r}. Supported: {supported}")

    if suffix not in _OFFICE_CONVERT_EXTENSIONS:
        return source_path, None

    from apis.v1.routers.documents import _convert_office_to_pdf_bytes  # noqa: E402

    pdf_bytes, _ = _convert_office_to_pdf_bytes(source_path.read_bytes(), source_path.name)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    pdf_path = Path(tmp.name) / "input.pdf"
    pdf_path.write_bytes(pdf_bytes)
    return pdf_path, tmp


def ingest_source_to_docling(
    source_path: Path,
    *,
    docling_root: Path,
    doc_name: str,
    force: bool = False,
) -> Path:
    """
    Parse a source file with Docling and persist under:
      <docling_root>/<doc_name>/output.html
      <docling_root>/<doc_name>/output_artifacts/...
    """
    from apis.services.ai.processing.parsing import Parsing  # noqa: E402

    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    name = doc_name.strip()
    if not name:
        raise ValueError("doc_name must be non-empty")

    out_dir = docling_root / name
    html_path = out_dir / "output.html"
    if html_path.is_file() and not force:
        logger.info(
            "Docling output already exists at %s — skipping parse (use --force-docling to re-run)",
            html_path,
        )
        return html_path.resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    parse_input, tmp = _prepare_docling_input(source_path)
    try:
        logger.info("Running Docling on %s → %s", source_path, out_dir)
        parser = Parsing(parse_input)
        written = parser.add_metadata_to_file(out_dir, "output.html")
        logger.info("Saved docling output → %s", written)
        return Path(written).resolve()
    finally:
        if tmp is not None:
            tmp.cleanup()


def _extraction_doc_dir(doc_name: str, root: Path | None = None) -> Path:
    base = root or _DEFAULT_EXTRACTION_OUT
    return base / doc_name


def save_extraction_outputs(
    doc_name: str,
    chunk_payloads: list[dict[str, Any]],
    *,
    root: Path | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    """
    Persist per-chunk extraction JSON under:
      3.5_Migration/extraction_outputs/<doc_name>/chunk_000.json ...
    """
    from datetime import datetime, timezone

    out_dir = _extraction_doc_dir(doc_name, root)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for payload in chunk_payloads:
        idx = int(payload.get("chunk_index", len(written)))
        path = out_dir / f"chunk_{idx:03d}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        written.append(path.name)

    meta = {
        "document": doc_name,
        "model": _RUNNER_MODEL,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "n_chunks": len(chunk_payloads),
        "n_claims_total": sum(int(p.get("n_claims") or 0) for p in chunk_payloads),
        "files": written,
        **(extra_meta or {}),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Saved extraction outputs → %s (%s chunks)", out_dir, len(written))
    return out_dir


def _violation_to_analysis_dict(v: Violation) -> dict[str, Any]:
    """Shape aligned with 3.5_Migration/analysis_results/*.json (UI findings fields)."""
    return {
        "rule": v.rule,
        "rule_name": v.rule_name,
        "severity": v.severity,
        "reasoning": v.reasoning,
        "would_break_compliance": v.would_break_compliance or "",
        "problematic_phrase": v.problematic_phrase,
        "suggested_alternative": v.suggested_alternative,
        "chunk_index": v.chunk_index,
        "claim_text": v.claim_text,
        "claim_id": v.claim_id,
    }


def build_analysis_result_payload(
    *,
    document_name: str,
    model: str,
    classification: dict[str, Any] | None,
    pipeline_result: DocumentResult | None,
    chunks_processed: int,
    elapsed_sec: float,
    trace_id: str | None = None,
    skipped: bool = False,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    """Final document output — same core schema as legacy analysis_results JSON."""
    violations: list[Violation] = []
    projection_count = 0
    document_metrics: dict[str, Any] | None = None

    if pipeline_result:
        violations = list(pipeline_result.violations or [])
        projection_count = int(pipeline_result.projection_without_disclaimer_count or 0)
        if projection_count == 0 and pipeline_result.chunk_results:
            projection_count = sum(
                1 for cr in pipeline_result.chunk_results if cr.projection_without_disclaimer
            )
        if pipeline_result.document_metrics is not None:
            document_metrics = pipeline_result.document_metrics.model_dump()

    payload: dict[str, Any] = {
        "document_name": document_name,
        "model": model,
        "classification": classification or {},
        "chunks_processed": chunks_processed,
        "violations_count": len(violations),
        "violations": [_violation_to_analysis_dict(v) for v in violations],
        "projection_without_disclaimer_count": projection_count,
        "elapsed_sec": round(elapsed_sec, 2),
    }
    if skipped:
        payload["skipped"] = True
        if skip_reason:
            payload["skip_reason"] = skip_reason
    if trace_id:
        payload["trace_id"] = trace_id
    if document_metrics is not None:
        payload["document_metrics"] = document_metrics
    return payload


def save_analysis_result(
    doc_name: str,
    payload: dict[str, Any],
    *,
    root: Path,
    model: str,
) -> Path:
    """Write <doc_name>_<model>.json under root (analysis_results-compatible)."""
    root.mkdir(parents=True, exist_ok=True)
    safe_doc = doc_name.replace("/", "_").strip()
    safe_model = model.replace("/", "-").strip()
    path = root / f"{safe_doc}_{safe_model}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Saved analysis result → %s", path)
    return path


def _payload_from_extraction_result(
    chunk_index: int,
    chunk_text: str,
    result: Any,
    raw: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    if error:
        return {
            "chunk_index": chunk_index,
            "chunk_text": chunk_text,
            "error": error,
            "model": _RUNNER_MODEL,
            "n_claims": 0,
        }
    return {
        "chunk_index": chunk_index,
        "chunk_text": chunk_text,
        "model": _RUNNER_MODEL,
        "n_claims": len(result.claims) if result else 0,
        "claims": [
            {
                "claim_id": c.claim_id,
                "claim_text": c.claim_text,
                "kind": c.kind,
            }
            for c in (result.claims if result else [])
        ],
        "raw": result.raw if result else None,
        "llm_raw_response": raw,
    }


def run_one_document(
    html_path: Path,
    *,
    max_chunks: int | None,
    with_visual: bool,
    force_pipeline: bool,
    extraction_only: bool = False,
    save_to: Path | None = None,
) -> dict[str, Any]:
    langfuse = get_client()
    doc_name = html_path.parent.name
    document_id = sanitize_document_id(doc_name)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    started = time.perf_counter()

    with langfuse.start_as_current_observation(
        as_type="span",
        name="document-extraction-only" if extraction_only else "document-compliance-pipeline",
        input={
            "document": doc_name,
            "html_path": str(html_path),
            "html_chars": len(html),
            "max_chunks": max_chunks,
            "with_visual": with_visual,
            "extraction_only": extraction_only,
            "model": _RUNNER_MODEL,
        },
    ) as root_span:
        with propagate_attributes(
            session_id=f"docling:{doc_name}",
            tags=[
                "langfuse-runner",
                "docling-html",
                _RUNNER_MODEL,
                *(["extraction-only"] if extraction_only else []),
            ],
            metadata={
                "source": "langfuse_runner",
                "document": doc_name,
                "model": _RUNNER_MODEL,
                "extraction_only": str(extraction_only),
            },
            trace_name=f"{'extraction' if extraction_only else 'compliance'}:{doc_name}",
        ):
            # 1) Chunking (no Docling — HTML already prepared)
            with langfuse.start_as_current_observation(
                as_type="span",
                name="chunking",
                input={"html_chars": len(html)},
            ) as chunk_span:
                chunker = Chunker()
                chunks_raw = chunker.chunk_html_with_media(html)
                chunk_texts = [
                    c.get("text", "") for c in chunks_raw if (c.get("text") or "").strip()
                ]
                chunk_metadatas = [
                    c.get("metadata", []) for c in chunks_raw if (c.get("text") or "").strip()
                ]
                if max_chunks is not None and max_chunks > 0:
                    chunk_texts = chunk_texts[:max_chunks]
                    chunk_metadatas = chunk_metadatas[:max_chunks]
                chunk_span.update(
                    output={
                        "n_chunks": len(chunk_texts),
                        "chunk_previews": [
                            {"index": i, "chars": len(t), "preview": _truncate(t, 240)}
                            for i, t in enumerate(chunk_texts)
                        ],
                    }
                )

            # Extraction-only: chunk → extract_chunk per chunk (no classifier / rules)
            if extraction_only:
                with langfuse.start_as_current_observation(
                    as_type="span",
                    name="extraction",
                    input={"n_chunks": len(chunk_texts)},
                ) as ext_span:
                    base_llm = get_llm_client(model_id=_RUNNER_MODEL)
                    traced_llm = TracingLLMClient(base_llm, ext_span)
                    extractions: list[dict[str, Any]] = []
                    for i, text in enumerate(chunk_texts):
                        with ext_span.start_as_current_observation(
                            as_type="span",
                            name=f"extract_chunk_{i}",
                            input={
                                "chunk_index": i,
                                "chars": len(text),
                                "preview": text[:400],
                            },
                        ) as ch_span:
                            try:
                                result, raw = extract_chunk(text, traced_llm)
                                result = normalize_extraction_claim_ids(result, document_id, i)
                                payload = _payload_from_extraction_result(
                                    i, text, result, raw=raw
                                )
                                ch_span.update(output=payload)
                                extractions.append(payload)
                                logger.info(
                                    "extraction_only chunk=%s claims=%s",
                                    i,
                                    payload["n_claims"],
                                )
                            except Exception as e:
                                logger.exception("extraction_only chunk=%s failed", i)
                                err = _payload_from_extraction_result(
                                    i, text, None, error=str(e)
                                )
                                ch_span.update(
                                    level="ERROR", status_message=str(e), output=err
                                )
                                extractions.append(err)

                    summary = {
                        "n_chunks": len(chunk_texts),
                        "n_claims_total": sum(e.get("n_claims", 0) for e in extractions),
                        "extractions": extractions,
                    }
                    ext_span.update(output=summary)

                saved_dir = save_extraction_outputs(
                    doc_name,
                    extractions,
                    extra_meta={"mode": "extraction_only", "document_id": document_id},
                )

                out = {
                    "document": doc_name,
                    "skipped": False,
                    "extraction_only": True,
                    "n_chunks": len(chunk_texts),
                    "extraction": summary,
                    "extraction_dir": str(saved_dir),
                    "trace_id": langfuse.get_current_trace_id(),
                }
                root_span.update(output=out)
                logger.info(
                    "DONE extraction-only %s chunks=%s claims=%s trace=%s",
                    doc_name,
                    len(chunk_texts),
                    summary["n_claims_total"],
                    out.get("trace_id"),
                )
                return out

            # 2) Classification
            with langfuse.start_as_current_observation(
                as_type="span",
                name="classification",
                input={"sample_chars": min(2500, len(html))},
            ) as class_span:
                classifier = ClassifierService()
                classification = classifier.classify_document(html)
                class_span.update(output=classification)

            is_in_scope = bool(classification.get("is_in_scope", True))
            detected = classification.get("detected_type")
            skip = (not is_in_scope) and not force_pipeline

            if skip:
                elapsed = time.perf_counter() - started
                out = {
                    "document": doc_name,
                    "skipped": True,
                    "reason": "classification_out_of_scope",
                    "classification": classification,
                    "n_chunks": len(chunk_texts),
                    "trace_id": langfuse.get_current_trace_id(),
                }
                if save_to is not None:
                    analysis_path = save_analysis_result(
                        doc_name,
                        build_analysis_result_payload(
                            document_name=doc_name,
                            model=_RUNNER_MODEL,
                            classification=classification,
                            pipeline_result=None,
                            chunks_processed=len(chunk_texts),
                            elapsed_sec=elapsed,
                            trace_id=out.get("trace_id"),
                            skipped=True,
                            skip_reason="classification_out_of_scope",
                        ),
                        root=save_to,
                        model=_RUNNER_MODEL,
                    )
                    out["analysis_result_path"] = str(analysis_path)
                root_span.update(output=out)
                logger.info("SKIP %s classification=%s", doc_name, detected)
                return out

            # 3) Optional visual merge (uses output_artifacts next to output.html)
            visual_merge = None
            if with_visual:
                with langfuse.start_as_current_observation(
                    as_type="span",
                    name="visual_extraction",
                    input={"html_path": str(html_path)},
                ) as vis_span:
                    try:
                        from apis.services.ai.processing.visual_document import (
                            extract_visual_extractions_from_html_workspace,
                        )

                        base_llm = get_llm_client(model_id=_RUNNER_MODEL)
                        traced_for_visual = TracingLLMClient(base_llm, vis_span)
                        visual_merge = extract_visual_extractions_from_html_workspace(
                            html_path, traced_for_visual
                        )
                        n_claims = len(visual_merge.claims) if visual_merge else 0
                        vis_span.update(
                            output={
                                "n_visual_claims": n_claims,
                                "claims_preview": [
                                    _truncate(c.claim_text, 200)
                                    for c in (visual_merge.claims if visual_merge else [])[:10]
                                ],
                            }
                        )
                    except Exception as e:
                        logger.warning("visual_extraction failed: %s", e)
                        vis_span.update(level="ERROR", status_message=str(e), output={"error": str(e)})

            # 4) Full pipeline — each LLM call is a nested generation via TracingLLMClient
            with langfuse.start_as_current_observation(
                as_type="span",
                name="compliance_pipeline",
                input={
                    "n_chunks": len(chunk_texts),
                    "has_visual_merge": bool(visual_merge and getattr(visual_merge, "claims", None)),
                },
            ) as pipe_span:
                base_llm = get_llm_client(model_id=_RUNNER_MODEL)
                traced_llm = TracingLLMClient(base_llm, pipe_span)
                result = run_pipeline(
                    chunks=chunk_texts,
                    llm_client=traced_llm,
                    document_id=document_id,
                    metadata_dicts=chunk_metadatas,
                    visual_extraction_merge=visual_merge,
                )
                summary = _serialize_result(result)
                pipe_span.update(output=summary)

                # Persist extraction per chunk (same layout as --extraction-only)
                pipeline_extractions: list[dict[str, Any]] = []
                for cr in result.chunk_results or []:
                    raw_ext = ""
                    if cr.llm_responses:
                        raw_ext = str(cr.llm_responses.get("extraction") or "")
                    chunk_text = cr.chunk_text or (
                        chunk_texts[cr.chunk_index]
                        if 0 <= cr.chunk_index < len(chunk_texts)
                        else ""
                    )
                    if cr.error:
                        pipeline_extractions.append(
                            _payload_from_extraction_result(
                                cr.chunk_index,
                                chunk_text,
                                None,
                                error=cr.error,
                            )
                        )
                    else:
                        pipeline_extractions.append(
                            _payload_from_extraction_result(
                                cr.chunk_index,
                                chunk_text,
                                cr.extraction,
                                raw=raw_ext,
                            )
                        )
                saved_dir = save_extraction_outputs(
                    doc_name,
                    pipeline_extractions,
                    extra_meta={"mode": "full_pipeline", "document_id": document_id},
                )

                # Extra spans per chunk so the UI shows extraction I/O clearly
                for cr in result.chunk_results or []:
                    with pipe_span.start_as_current_observation(
                        as_type="span",
                        name=f"chunk_{cr.chunk_index}_summary",
                        input={"chunk_preview": cr.chunk_text},
                    ) as ch_span:
                        ext = cr.extraction
                        ch_span.update(
                            output={
                                "error": cr.error,
                                "n_claims": len(ext.claims) if ext else 0,
                                "extraction_raw": ext.raw if ext else None,
                                "llm_responses": dict(cr.llm_responses or {}),
                                "violations": [
                                    {
                                        "rule": v.rule,
                                        "severity": v.severity,
                                        "phrase": v.problematic_phrase,
                                    }
                                    for v in (cr.violations or [])
                                ],
                            }
                        )

            elapsed = time.perf_counter() - started
            trace_id = langfuse.get_current_trace_id()
            out = {
                "document": doc_name,
                "skipped": False,
                "classification": classification,
                "n_chunks": len(chunk_texts),
                "pipeline": summary,
                "extraction_dir": str(saved_dir),
                "trace_id": trace_id,
            }
            if save_to is not None:
                analysis_path = save_analysis_result(
                    doc_name,
                    build_analysis_result_payload(
                        document_name=doc_name,
                        model=_RUNNER_MODEL,
                        classification=classification,
                        pipeline_result=result,
                        chunks_processed=result.chunks_processed,
                        elapsed_sec=elapsed,
                        trace_id=trace_id,
                    ),
                    root=save_to,
                    model=_RUNNER_MODEL,
                )
                out["analysis_result_path"] = str(analysis_path)
            root_span.update(output=out)
            logger.info(
                "DONE %s chunks=%s violations=%s trace=%s",
                doc_name,
                len(chunk_texts),
                summary.get("n_violations"),
                out.get("trace_id"),
            )
            return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run compliance pipeline on Docling HTML with Langfuse tracing."
    )
    parser.add_argument(
        "--doc",
        help="Docling folder name under docling_outputs, or path to output.html / its folder",
    )
    parser.add_argument(
        "--from-source",
        metavar="PATH",
        help=(
            "New document: parse PDF/DOC/DOCX/PPT/PPTX with Docling, save under "
            "--docling-dir, then run the pipeline"
        ),
    )
    parser.add_argument(
        "--doc-name",
        help=(
            "Folder name under docling_outputs (default: source file stem). "
            "Use with --from-source."
        ),
    )
    parser.add_argument(
        "--force-docling",
        action="store_true",
        help="Re-run Docling even if output.html already exists (--from-source only)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every folder under --docling-dir that contains output.html",
    )
    parser.add_argument(
        "--docling-dir",
        default=str(_DEFAULT_DOCLING),
        help=f"Root of Docling HTML outputs (default: {_DEFAULT_DOCLING})",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=5,
        help="Cap chunks per document (default 5; use 0 for no cap)",
    )
    parser.add_argument(
        "--with-visual",
        action="store_true",
        help="Also run chart/image visual extraction from output_artifacts",
    )
    parser.add_argument(
        "--force-pipeline",
        action="store_true",
        help="Run analysis even if classifier marks document out of scope",
    )
    parser.add_argument(
        "--extraction-only",
        action="store_true",
        help="Only chunk + extract claims (skip classifier and all rule evals)",
    )
    parser.add_argument(
        "--model",
        default=_RUNNER_MODEL,
        help=f"Vertex model id for this run (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--save-to",
        nargs="?",
        const=str(_DEFAULT_ANALYSIS_RESULTS_OUT),
        default=None,
        metavar="DIR",
        help=(
            "Write final analysis JSON (UI/analysis_results shape) to DIR. "
            f"Omit DIR to use {_DEFAULT_ANALYSIS_RESULTS_OUT}. "
            "Ignored with --extraction-only."
        ),
    )
    args = parser.parse_args()
    # Early parser already applied --model; log what we use
    logger.info("Using model=%s provider=%s", _RUNNER_MODEL, os.getenv("LLM_PROVIDER"))

    if not args.doc and not args.all and not args.from_source:
        parser.error("Provide --doc NAME, --from-source PATH, or --all")
    if args.from_source and args.all:
        parser.error("--from-source cannot be used with --all")
    if args.doc_name and not args.from_source:
        parser.error("--doc-name is only valid with --from-source")

    # Credential check
    missing = [
        k
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
        if not (os.getenv(k) or "").strip()
    ]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}", file=sys.stderr)
        print("Set them in the repo .env (LANGFUSE_BASE_URL optional).", file=sys.stderr)
        return 1

    docling_root = Path(args.docling_dir).expanduser().resolve()
    max_chunks = None if args.max_chunks == 0 else args.max_chunks
    save_to: Path | None = None
    if args.save_to is not None and not args.extraction_only:
        save_to = Path(args.save_to).expanduser().resolve()
    elif args.save_to is not None and args.extraction_only:
        logger.warning("--save-to ignored when --extraction-only is set")

    if args.from_source:
        source_path = Path(args.from_source).expanduser().resolve()
        doc_name = (args.doc_name or source_path.stem).strip()
        try:
            html_paths = [
                ingest_source_to_docling(
                    source_path,
                    docling_root=docling_root,
                    doc_name=doc_name,
                    force=args.force_docling,
                )
            ]
        except Exception as e:
            print(f"ERROR: Docling ingest failed: {e}", file=sys.stderr)
            return 1
    elif args.all:
        html_paths = list_docling_docs(docling_root)
        if not html_paths:
            print(f"No output.html folders under {docling_root}", file=sys.stderr)
            return 1
    else:
        html_paths = [resolve_html_path(args.doc, docling_root)]

    langfuse = get_client()
    try:
        if not langfuse.auth_check():
            print("ERROR: Langfuse auth_check failed — verify keys / BASE_URL", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"ERROR: Langfuse auth_check error: {e}", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    for html_path in html_paths:
        print(f"\n=== {html_path.parent.name} ===")
        try:
            results.append(
                run_one_document(
                    html_path,
                    max_chunks=max_chunks,
                    with_visual=args.with_visual,
                    force_pipeline=args.force_pipeline,
                    extraction_only=args.extraction_only,
                    save_to=save_to,
                )
            )
        except Exception as e:
            logger.exception("Failed on %s: %s", html_path, e)
            results.append({"document": html_path.parent.name, "error": str(e)})

    langfuse.flush()

    print("\n=== Summary ===")
    for r in results:
        if r.get("error"):
            print(f"  FAIL  {r.get('document')}: {r['error']}")
        elif r.get("skipped"):
            print(f"  SKIP  {r.get('document')}: {r.get('classification')}")
        elif r.get("extraction_only"):
            n_c = (r.get("extraction") or {}).get("n_claims_total")
            print(f"  OK    {r.get('document')}: extraction-only claims={n_c} trace={r.get('trace_id')}")
        else:
            n_v = (r.get("pipeline") or {}).get("n_violations")
            saved = r.get("analysis_result_path")
            suffix = f" saved={saved}" if saved else ""
            print(
                f"  OK    {r.get('document')}: violations={n_v} "
                f"trace={r.get('trace_id')}{suffix}"
            )

    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "http://localhost:8035"
    print(f"\nInspect traces in Langfuse: {host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
