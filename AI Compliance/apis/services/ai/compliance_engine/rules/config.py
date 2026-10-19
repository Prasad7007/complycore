"""
Rule metadata and thresholds. Phrase lists here support deterministic routing
and document metrics; claim kind labels come from the slim extraction schema.
"""

# Rule display names
RULE_NAMES: dict[int, str] = {
    1: "Marketing content must not be false or misleading",
    2: "Statements must be factually accurate and supportable",
    3: "Language must not exaggerate benefits or minimize risks",
    4: "Marketing must present fair and balanced information",
    5: "Important information must not be obscured by formatting or placement",
    6: "Overly promotional or absolute language",
    7: "Emotionally manipulative wording",
    8: "Forward-looking statements, projections, and hypotheticals",
}

# ----- Rule 5: Formatting (we don't get these from LLM; they come from HTML/metadata) -----
RULE_5_DISCLAIMER_DISTANCE_MAX_CHARS: int = 500
RULE_5_DISCLAIMER_FONT_RATIO_MIN: float = 0.5  # disclaimer font >= 50% of claim font

# ----- Rule 6: Absolutes + proximity (v2) -----
# Qualifier must appear within this many characters of an absolute to avoid auto-flag.
RULE_6_QUALIFIER_PROXIMITY_CHARS: int = 150

# Core red-flag phrases (deterministic routing, ≤20). Do not grow large.
CORE_ABSOLUTE_PHRASES: list[str] = [
    "risk-free",
    "guaranteed",
    "guarantee",
    "never fails",
    "never failed",
    "always delivers",
    "always profitable",
    "completely safe",
    "100% safe",
    "ensure returns",
    "cannot lose",
    "no risk",
    "regardless of market",
    "protect your capital in any market",
    "certain returns",
    "secure your financial future",
    "without risk",
    "without changing risk",
    "risk eliminated",
]

# ----- Risk-minimization routing (v2): leverage/derivative without risk → Route Rule 3 -----
LEVERAGE_DERIVATIVE_PHRASES: list[str] = [
    "leverage",
    "leveraged",
    "leveraging",
    "derivative",
    "derivatives",
    "options",
    "tactical overlay",
]

# Rule 3 deterministic HIGH: leverage/derivative + these phrases → risk minimization violation
RULE_3_RISK_MINIMIZATION_PHRASES: list[str] = [
    "without changing risk",
    "without increasing risk",
    "without adding risk",
    "no additional risk",
    "risk unchanged",
    "same risk",
    "without changing the risk",
]

# Rule 8: Forward-looking disclaimer (v2: proximity within this many chars)
RULE_8_DISCLAIMER_PROXIMITY_CHARS: int = 300

# Phrases that count as forward-looking disclaimer (structural).
# Kept as a fallback in case LLM doesn't extract any disclaimers but we need to check proximity.
RULE_8_DISCLAIMER_PHRASES: list[str] = [
    "forward-looking",
    "forward looking",
    "hypothetical",
    "illustrative",
]

# Fallback phrases to find "projection" spans in chunk when extraction has no forward_looking
RULE_8_FORWARD_PROJECTION_PHRASES: list[str] = [
    "expect",
    "forecast",
    "outlook",
    "anticipate",
    "predict",
    "target",
    "will deliver",
    "will benefit",
    "future returns",
    "potential annual returns",
    "projections indicate",
    "projection",
]

# Rule 5 uses HTML/metadata only; claim rules 1-3 and 6-8 are LLM-evaluated in pipeline.
DETERMINISTIC_RULES: set[int] = {5}
LLM_CLAIM_RULES: set[int] = {1, 2, 3, 6, 7, 8}
LLM_RULES: set[int] = {1, 2, 3, 4, 6, 7, 8}

# Claim-type → applicable rules (avoid over-routing; e.g. risk-only claims don't need Rule 2/8)
CLAIM_TYPE_TO_RULES: dict[str, list[int]] = {
    "performance": [1, 2, 3, 4, 8],
    "risk": [1, 3, 4],
    "comparison": [1, 2, 3, 4, 7],
    "emotional": [1, 6, 7],
    "forward_looking": [1, 2, 3, 4, 8],
    "benefits": [1, 2, 3, 4],
}
# Default when claim type unknown or chunk-level only
DEFAULT_APPLICABLE_RULES: list[int] = [1, 2, 3, 4]


# Rule 5: uses ChunkMetadata only (font size, distance).
# Rules 1, 2, 3, 6, 7, 8: always LLM on extracted claims (see pipeline.LLM_CLAIM_RULES).