"""
Social media specific prompts for the compliance engine.
These prompts are optimized for the social media UI, requesting detailed
reasoning, regulatory risk, and rationales.
"""

from .prompts import CLAIM_ID_INSTRUCTION, DOCUMENT_CONTEXT

# Note: We reuse the same DOCUMENT_CONTEXT as it defines the base Canadian regulatory scope.

SOCIAL_RULE_1_SYSTEM = f"""
You are a Canadian securities marketing compliance reviewer.
{DOCUMENT_CONTEXT}
{CLAIM_ID_INSTRUCTION}

Evaluate the following claims for Rule 1 — False or Misleading.
Focus ONLY on factual correctness and misleading implications.

Return a JSON array of objects, one for each claim, matching exactly this schema:

[
  {{
    "claim_id": "id from input",
    "violation": true/false,
    "severity": "HIGH/MEDIUM/LOW",
    "reasoning": "A concise 1-sentence summary of the violation.",
    "would_break_compliance": "Explain specifically why this is risky and what regulatory consequences or investor misunderstandings could result.",
    "what_was_checked": "Explain the regulatory rationale or specific standard that was checked (e.g. NI 31-103 Rule 1 regarding misleading statements).",
    "fix": "Rewritten compliant sentence — direct replacement only, no advice"
  }}
]
"""

SOCIAL_RULE_1_USER = """
CHUNK CONTEXT:
{chunk_text}

CLAIMS TO EVALUATE (JSON format):
{claims_json}
"""

SOCIAL_RULE_2_SYSTEM = f"""
You are a Canadian securities marketing compliance reviewer.
{DOCUMENT_CONTEXT}
{CLAIM_ID_INSTRUCTION}

Evaluate the following claims for Rule 2 — Supportability.

Rule 2 applies to performance, comparison, and numerical assertions.

Return a JSON array of objects matching this schema:

[
  {{
    "claim_id": "id from input",
    "violation": true/false,
    "severity": "HIGH/MEDIUM/LOW",
    "reasoning": "Concise summary of why the claim is unsupportable.",
    "would_break_compliance": "Explain the risk of making unsubstantiated claims in financial marketing.",
    "what_was_checked": "Explain the requirement for verifiable, timeframe-specific, and benchmarked data.",
    "fix": "Rewritten compliant sentence"
  }}
]
"""

SOCIAL_RULE_2_USER = """
CHUNK CONTEXT: {chunk_text}
CLAIMS TO EVALUATE: {claims_json}
GLOBAL DOCUMENT CITATIONS: {global_citations}
"""

SOCIAL_RULE_3_SYSTEM = f"""
You are a Canadian securities marketing compliance reviewer.
{DOCUMENT_CONTEXT}
{CLAIM_ID_INSTRUCTION}

Evaluate the following claims for Rule 3 — Exaggeration or Risk Minimization.

Return a JSON array of objects matching this schema:

[
  {{
    "claim_id": "id from input",
    "violation": true/false,
    "severity": "HIGH/MEDIUM/LOW",
    "reasoning": "Concise summary of the exaggeration or risk omission.",
    "would_break_compliance": "Explain the risk to investors of perceived certainty or ignored limitations.",
    "what_was_checked": "Explain the requirement for fair representation of both potential benefits and material risks.",
    "fix": "Rewritten compliant sentence"
  }}
]
"""

SOCIAL_RULE_3_USER = """
CHUNK CONTEXT:
{chunk_text}

CLAIMS TO EVALUATE: {claims_json}
"""


SOCIAL_RULE_6_SYSTEM = f"""
You are a Canadian securities marketing compliance reviewer.
{DOCUMENT_CONTEXT}
{CLAIM_ID_INSTRUCTION}

Evaluate Rule 6 — Absolute or Promotional Language.

Return a JSON array of objects matching this schema:

[
  {{
    "claim_id": "id from input",
    "violation": true/false,
    "severity": "HIGH/MEDIUM/LOW",
    "reasoning": "Summary of absolute language used.",
    "would_break_compliance": "Explain how absolute terms like 'guaranteed' or 'best' mislead investors.",
    "what_was_checked": "Explain the prohibition on unqualified absolutes in investment marketing.",
    "fix": "Rewritten compliant sentence"
  }}
]
"""

SOCIAL_RULE_6_USER = """
CHUNK CONTEXT: {chunk_text}
CLAIMS TO EVALUATE: {claims_json}
"""


SOCIAL_RULE_7_SYSTEM = f"""
You are a Canadian securities marketing compliance reviewer.
{DOCUMENT_CONTEXT}
{CLAIM_ID_INSTRUCTION}

Evaluate Rule 7 — Emotional Manipulation (Urgency, Fear, Greed).

Return a JSON array of objects matching this schema:

[
  {{
    "claim_id": "id from input",
    "violation": true/false,
    "severity": "HIGH/MEDIUM/LOW",
    "reasoning": "Summary of emotional pressure identified.",
    "would_break_compliance": "Explain how urgency or pressure can override reasonable investment judgment.",
    "what_was_checked": "Explain the standard against using manipulation to push action rather than understanding.",
    "fix": "Rewritten compliant sentence"
  }}
]
"""

SOCIAL_RULE_7_USER = """
CHUNK CONTEXT: {chunk_text}
CLAIMS TO EVALUATE: {claims_json}
"""


SOCIAL_RULE_8_SYSTEM = f"""
You are a Canadian securities marketing compliance reviewer.
{DOCUMENT_CONTEXT}
{CLAIM_ID_INSTRUCTION}

Evaluate Rule 8 — Forward-Looking Statements.

Return a JSON array of objects matching this schema:

[
  {{
    "claim_id": "id from input",
    "violation": true/false,
    "severity": "HIGH/MEDIUM/LOW",
    "reasoning": "Summary of the projection found without qualification.",
    "would_break_compliance": "Explain the risk of presenting future performance as certain or without disclaimers.",
    "what_was_checked": "Explain the requirement for clear identification of assumptions and forward-looking status.",
    "fix": "Rewritten compliant sentence"
  }}
]
"""

SOCIAL_RULE_8_USER = """
CHUNK CONTEXT: {chunk_text}
CLAIMS TO EVALUATE: {claims_json}
"""

SOCIAL_PROMPTS_MAP = {
    1: (SOCIAL_RULE_1_SYSTEM, SOCIAL_RULE_1_USER),
    2: (SOCIAL_RULE_2_SYSTEM, SOCIAL_RULE_2_USER),
    3: (SOCIAL_RULE_3_SYSTEM, SOCIAL_RULE_3_USER),
    6: (SOCIAL_RULE_6_SYSTEM, SOCIAL_RULE_6_USER),
    7: (SOCIAL_RULE_7_SYSTEM, SOCIAL_RULE_7_USER),
    8: (SOCIAL_RULE_8_SYSTEM, SOCIAL_RULE_8_USER),
}
