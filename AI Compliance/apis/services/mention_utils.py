"""Parse @mentions in comment text (UUID or email) and resolve to user ids."""
import re
from typing import List, Optional, Set, Tuple

# @550e8400-e29b-41d4-a716-446655440000
_UUID_RE = re.compile(
    r"@([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)
# @user@example.com (leading @ + email)
_EMAIL_RE = re.compile(
    r"@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
)


def extract_mention_tokens(content: str) -> Tuple[Set[str], Set[str]]:
    """Return (uuid_strings, email_strings) found in content."""
    uuids: Set[str] = set()
    emails: Set[str] = set()
    for m in _UUID_RE.finditer(content or ""):
        uuids.add(m.group(1).lower())
    for m in _EMAIL_RE.finditer(content or ""):
        emails.add(m.group(1).strip().lower())
    return uuids, emails


async def resolve_mentioned_user_ids(
    db,
    *,
    content: str,
    explicit_ids: Optional[List[str]],
    author_id: str,
) -> List[str]:
    """
    Merge explicit client ids with tokens parsed from content.
    Returns distinct existing user UUID strings, excluding the comment author (no self-tags).
    """
    uuids, emails = extract_mention_tokens(content)
    out: Set[str] = set()

    if explicit_ids:
        for x in explicit_ids:
            if x:
                out.add(str(x))

    for u in uuids:
        row = await db.fetchrow("SELECT id FROM user_profiles WHERE id::text = $1", u)
        if row:
            out.add(str(row["id"]))

    for em in emails:
        row = await db.fetchrow(
            "SELECT id FROM user_profiles WHERE lower(email) = lower($1) AND is_active = TRUE",
            em,
        )
        if row:
            out.add(str(row["id"]))

    author_norm = str(author_id).strip().lower()
    out = {uid for uid in out if str(uid).strip().lower() != author_norm}
    return list(out)
