import uuid
import datetime
import logging
from typing import Optional
from asyncpg.connection import Connection
from asyncpg.exceptions import UndefinedColumnError

logger = logging.getLogger(__name__)

async def generate_compliance_report(
    db: Connection,
    review_id: str,
    user_id: str,
    role_name: str,
    ai_summary: Optional[str] = None
) -> str:
    """
    Generate or update a compliance report for a given content review when it is
    approved or rejected. It tallies findings and upserts the report record.
    Returns the report_id.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    
    # 1. Fetch review to get context and status
    review = await db.fetchrow(
        "SELECT id, content_type, compliance_status FROM content_reviews WHERE id=$1",
        review_id
    )
    if not review:
        logger.error("generate_compliance_report: Review %s not found", review_id)
        return None

    # 2. Tally finding risks (grouping claims like the UI does)
    findings_rows = await db.fetch(
        """
        SELECT 
            af.id, 
            af.risk_level, 
            af.claim_id, 
            af.claim_text, 
            af.title,
            COALESCE(afa.normalized_claim_hash, '') AS canonical_claim_hash
        FROM ai_findings af
        LEFT JOIN ai_finding_anchors afa ON afa.finding_id = af.id
        WHERE af.review_id=$1
        """,
        review_id
    )
    
    findings_by_claim = {}
    for row in findings_rows:
        chash = (row["canonical_claim_hash"] or "").strip()
        cid = (row["claim_id"] or "").strip()
        txt_part = str(row["claim_text"] or row["title"] or row["id"] or "")[:200].strip()
        
        fallback_key = f"h:{chash}" if chash else (f"cid:{cid}" if cid else f"txt:{txt_part}")
        if fallback_key not in findings_by_claim:
            findings_by_claim[fallback_key] = []
        findings_by_claim[fallback_key].append(row)

    total_flags = 0
    high_risk = 0
    med_risk = 0
    low_risk = 0
    
    severity_order = {"high": 3, "critical": 3, "medium": 2, "low": 1}

    for group in findings_by_claim.values():
        total_flags += 1
        
        highest_val = 0
        for f in group:
            r = (f["risk_level"] or "low").lower()
            val = severity_order.get(r, 1)
            if val > highest_val:
                highest_val = val
                
        if highest_val == 3:
            high_risk += 1
        elif highest_val == 2:
            med_risk += 1
        else:
            low_risk += 1

    # 3. Check if report already exists
    existing = await db.fetchrow("SELECT id FROM compliance_reports WHERE review_id=$1", review_id)
    
    if existing:
        report_id = str(existing["id"])
        await db.execute(
            """
            UPDATE compliance_reports
            SET compliance_status=$1, total_flags=$2, high_risk_flags=$3, medium_risk_flags=$4,
                low_risk_flags=$5, approval_authority=$6, approval_role=$7, approval_timestamp=$8,
                ai_summary=COALESCE($9, ai_summary)
            WHERE id=$10
            """,
            review["compliance_status"], total_flags, high_risk, med_risk, low_risk,
            user_id, role_name, now, ai_summary, report_id
        )
    else:
        report_id = str(uuid.uuid4())
        
        # Generate code using sequence to guarantee no race conditions
        seq_row = await db.fetchrow("SELECT nextval('compliance_report_code_seq') AS next_num")
        next_num = seq_row["next_num"]
        report_code = f"RPT-{next_num:03d}"
        
        await db.execute(
            """
            INSERT INTO compliance_reports (
                id, report_code, review_id, review_type, compliance_status, 
                total_flags, high_risk_flags, medium_risk_flags, low_risk_flags,
                approval_authority, approval_role, approval_timestamp, created_at, ai_summary
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
            report_id, report_code, review_id, review["content_type"], review["compliance_status"],
            total_flags, high_risk, med_risk, low_risk, user_id, role_name, now, now, ai_summary
        )

    return report_id
