"""
LLM evaluator: for rules that need judgment (1, 2, 3, 4, 6, 7, 8), call LLM and parse violations.
"""

import json
import logging
from typing import Any, Protocol

try:
    from json_repair import repair_json
except ImportError:
    repair_json = None  # Graceful fallback if library not installed

from apis.services.ai.core import config
from .models import Violation
from .rules.config import RULE_NAMES
from .rules.prompts import (
    RULE_1_SYSTEM, RULE_1_USER,
    RULE_2_SYSTEM, RULE_2_USER,
    RULE_3_SYSTEM, RULE_3_USER,
    RULE_4_SYSTEM, RULE_4_USER,
    RULE_6_SYSTEM, RULE_6_USER,
    RULE_7_SYSTEM, RULE_7_USER,
    RULE_8_SYSTEM, RULE_8_USER,
    COMBINED_SUGGESTION_SYSTEM, COMBINED_SUGGESTION_USER,
    STRUCTURAL_SUGGESTION_SYSTEM, STRUCTURAL_SUGGESTION_USER,
)

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Any client with invoke(system_prompt, user_prompt) -> str."""

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> str: ...


def _strip_json_block(raw: str) -> str:
    """Extract JSON object or array from text, ignoring markdown and conversational filler."""
    text = raw.strip()
    
    start_obj = text.find("{")
    start_arr = text.find("[")
    
    start_idx = -1
    if start_obj != -1 and start_arr != -1:
        start_idx = min(start_obj, start_arr)
    elif start_obj != -1:
        start_idx = start_obj
    else:
        start_idx = start_arr
        
    if start_idx != -1:
        is_array = text[start_idx] == "["
        end_char = "]" if is_array else "}"
        end_idx = text.rfind(end_char)
        if end_idx != -1 and end_idx > start_idx:
            return text[start_idx:end_idx + 1]
            
    return text


def _parse_rule_response(raw: str) -> Any:
    """Parse JSON response, expecting a list or dict."""
    text = _strip_json_block(raw)
    try:
        return json.loads(text)
    except Exception as e:
        if repair_json is not None:
            try:
                repaired = repair_json(text)
                data = json.loads(repaired)
                logger.info("json_repair_success rule_response recovered")
                return data
            except Exception as repair_err:
                logger.warning("json_repair also failed: %s", repair_err)
        logger.warning("rule json decode error: %s - raw: %s", e, raw[:200])
        return None


def _create_violation_from_rule(
    rule_num: int,
    data: dict[str, Any],
    claim_text: str,
    claim_id: str,
    chunk_index: int,
    problematic_phrase_override: str = ""
) -> Violation | None:
    """Convert parsed rule evaluation into a Violation object if violation is true."""
    if not isinstance(data, dict):
        return None

    # Handle v2 format
    is_violation = data.get("violation", False)
    # Support backward compatibility if needed
    if "violation" not in data and "status" in data:
        is_violation = str(data["status"]).upper() == "REJECT"

    if not is_violation:
        return None

    severity = str(data.get("severity", "MEDIUM")).upper()
    if severity not in ("HIGH", "MEDIUM", "LOW"):
        severity = "MEDIUM"

    trigger = data.get("trigger_phrase")
    if trigger is not None and str(trigger).lower() in ("null", "none", ""):
        trigger = None
    prob_phrase = str(
        trigger
        or data.get("problematic_phrase")
        or problematic_phrase_override
        or claim_text
    )

    # Capture enhanced fields for social media UI
    reasoning = str(data.get("reason", data.get("reasoning", "")))
    would_break = str(data.get("would_break_compliance", ""))
    what_checked = str(data.get("what_was_checked", ""))

    return Violation(
        rule=rule_num,
        rule_name=RULE_NAMES.get(rule_num, ""),
        claim_text=claim_text,
        claim_id=claim_id,
        chunk_index=chunk_index,
        problematic_phrase=prob_phrase,
        status="REJECT",
        compliant=False,
        reasoning=reasoning,
        severity=severity,
        method="llm",
        suggested_alternative=str(data.get("fix", data.get("suggested_alternative", ""))),
        would_break_compliance=would_break,
        what_was_checked=what_checked
    )


def _evaluate_single_rule(
    rule_num: int,
    claims_json_str: str,
    claims_context_list: list[dict],
    chunk_text: str,
    chunk_index: int,
    llm_client: LLMClient,
    max_tokens: int,
    temperature: float,
    global_citations: list[str] | None,
    visual_evidence: list[dict[str, Any]] | None,
    prompts: tuple[str, str],
) -> tuple[int, list[Violation], str]:
    """
    Evaluate a single rule against all claims — designed to run in a thread.
    Returns (rule_num, violations, raw_response).
    """
    system_prompt, user_prompt_template = prompts

    user_prompt = user_prompt_template.replace("{claims_json}", claims_json_str)
    user_prompt = user_prompt.replace("{chunk_text}", chunk_text)

    citations_str = json.dumps(global_citations or [], ensure_ascii=False)
    user_prompt = user_prompt.replace("{global_citations}", citations_str)
    visual_evidence_str = json.dumps(visual_evidence or [], ensure_ascii=False)
    user_prompt = user_prompt.replace("{visual_evidence}", visual_evidence_str)

    raw_resp = llm_client.invoke(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        _label=f"rule_{rule_num}_eval",
    )

    violations: list[Violation] = []
    parsed = _parse_rule_response(raw_resp)

    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            claim_id = item.get("claim_id")
            claim_text = next(
                (c.get("claim_text", "") for c in claims_context_list if c.get("claim_id") == claim_id), ""
            )
            v = _create_violation_from_rule(
                rule_num, item, claim_text, str(claim_id) if claim_id else "", chunk_index
            )
            if v:
                violations.append(v)
    elif isinstance(parsed, dict):
        claim_id = parsed.get("claim_id")
        claim_text = next(
            (c.get("claim_text", "") for c in claims_context_list if c.get("claim_id") == claim_id), ""
        )
        v = _create_violation_from_rule(
            rule_num, parsed, claim_text, str(claim_id) if claim_id else "", chunk_index
        )
        if v:
            violations.append(v)

    return rule_num, violations, raw_resp


def evaluate_claims_for_rules(
    claims_context_list: list[dict],
    rules_to_run: list[int],
    llm_client: LLMClient,
    chunk_text: str = "",
    chunk_index: int = 0,
    max_tokens: int = config.LLM_MAX_TOKENS,
    temperature: float = 0.2,
    global_citations: list[str] | None = None,
    visual_evidence: list[dict[str, Any]] | None = None,
    prompts_map: dict[int, tuple[str, str]] | None = None,
) -> tuple[list[Violation], dict[str, str]]:
    """
    Evaluate all claims in a chunk against multiple rules (1, 2, 3, 6, 7, 8).

    Rules are evaluated **in parallel** using a ThreadPoolExecutor since each
    rule evaluation is an independent LLM call with no data dependencies.
    This cuts per-chunk evaluation from sum(rule latencies) to max(rule latency).

    Returns (violations, raw_responses_dict).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    violations: list[Violation] = []
    responses: dict[str, str] = {}

    if not claims_context_list:
        return violations, responses

    # Use default prompts if none provided
    if prompts_map is None:
        prompts_map = {
            1: (RULE_1_SYSTEM, RULE_1_USER),
            2: (RULE_2_SYSTEM, RULE_2_USER),
            3: (RULE_3_SYSTEM, RULE_3_USER),
            4: (RULE_4_SYSTEM, RULE_4_USER),
            6: (RULE_6_SYSTEM, RULE_6_USER),
            7: (RULE_7_SYSTEM, RULE_7_USER),
            8: (RULE_8_SYSTEM, RULE_8_USER),
        }

    # Only keep fields needed to save prompt space
    minimal_claims = []
    for c in claims_context_list:
        mc = {"claim_id": c["claim_id"], "claim_text": c["claim_text"]}
        if "context_before" in c and c["context_before"]:
            mc["context_before"] = c["context_before"]
        if "context_after" in c and c["context_after"]:
            mc["context_after"] = c["context_after"]
        minimal_claims.append(mc)

    claims_json_str = json.dumps(minimal_claims, ensure_ascii=False)

    # Filter to rules we actually have prompts for
    valid_rules = [r for r in rules_to_run if r in prompts_map]

    if not valid_rules:
        return violations, responses

    # ── Parallel execution ────────────────────────────────────────
    # Each rule is an independent LLM call, so we fire them all simultaneously.
    # max_workers is capped at the number of rules (typically 3-6).
    with ThreadPoolExecutor(max_workers=len(valid_rules)) as executor:
        futures = {
            executor.submit(
                _evaluate_single_rule,
                rule_num,
                claims_json_str,
                claims_context_list,
                chunk_text,
                chunk_index,
                llm_client,
                max_tokens,
                temperature,
                global_citations,
                visual_evidence,
                prompts_map[rule_num],
            ): rule_num
            for rule_num in valid_rules
        }

        for future in as_completed(futures):
            rule_num = futures[future]
            try:
                _rule, rule_violations, raw_resp = future.result()
                responses[f"rule_{_rule}"] = raw_resp
                violations.extend(rule_violations)
            except Exception as e:
                logger.exception("parallel_rule_eval_error rule=%s chunk=%s error=%s", rule_num, chunk_index, e)

    return violations, responses


def evaluate_balance_v2(
    *,
    document_context: str,
    performance_count: int,
    risk_count: int,
    other_count: int,
    performance_to_risk_ratio: float,
    sample_performance_claims: list[dict[str, str]],
    sample_risk_claims: list[dict[str, str]],
    repeated_phrases: list[dict[str, Any]],
    llm_client: LLMClient,
    chunk_index: int = -1,
    max_tokens: int = config.LLM_MAX_TOKENS,
    temperature: float = 0.2,
) -> tuple[list[Violation], str]:
    """Rule 4 document-level balance evaluation using kind counts + sample claims."""
    user_prompt = (
        RULE_4_USER.replace("{document_context}", document_context)
        .replace("{performance_count}", str(performance_count))
        .replace("{risk_count}", str(risk_count))
        .replace("{other_count}", str(other_count))
        .replace("{performance_to_risk_ratio}", str(performance_to_risk_ratio))
        .replace(
            "{sample_performance_claims}",
            json.dumps(sample_performance_claims, ensure_ascii=False, indent=2),
        )
        .replace(
            "{sample_risk_claims}",
            json.dumps(sample_risk_claims, ensure_ascii=False, indent=2),
        )
        .replace(
            "{repeated_phrases}",
            json.dumps(repeated_phrases, ensure_ascii=False, indent=2),
        )
    )

    raw_response = llm_client.invoke(
        system_prompt=RULE_4_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        _label="rule_4_eval",
    )

    parsed = _parse_rule_response(raw_response)
    if isinstance(parsed, dict):
        v = _create_violation_from_rule(4, parsed, "Document balance", "", chunk_index)
        return [v] if v else [], raw_response
    return [], raw_response


def get_combined_suggestion(
    claim_text: str,
    violations: list[Violation],
    llm_client: LLMClient,
    max_tokens: int = config.LLM_MAX_TOKENS,
    temperature: float = 0.2,
) -> str:
    """
    If a claim violates multiple rules, synthesize one cohesive suggested alternative.
    """
    if not violations:
        return ""

    v_summaries = []
    for v in violations:
        v_summaries.append(f"- Rule {v.rule} ({v.rule_name}): {v.reasoning}")
    
    violations_summary = "\n".join(v_summaries)

    is_structural = (
        violations[0].method == "document_level"
        or getattr(violations[0], "chunk_index", 0) == -1
    )
    system_prompt, user_prompt_template = (STRUCTURAL_SUGGESTION_SYSTEM, STRUCTURAL_SUGGESTION_USER) if is_structural else (COMBINED_SUGGESTION_SYSTEM, COMBINED_SUGGESTION_USER)
    user_prompt = user_prompt_template.replace("{claim_text}", claim_text)
    user_prompt = user_prompt.replace("{violations_summary}", violations_summary)

    try:
        raw_response = llm_client.invoke(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            _label="combined_suggestion",
        )
        parsed = _parse_rule_response(raw_response)
        if isinstance(parsed, dict):
            return parsed.get("combined_suggestion", "")
        return ""
    except Exception as e:
        logger.warning("failed to generate combined suggestion: %s", e)
        return ""