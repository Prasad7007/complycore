import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from apis.core.database import get_db
from apis.core.encrypted_fields import decode_extracted_text
from apis.core.security import require_app_access_ready, require_tenant_context
from apis.core.tenant_resources import assert_review_in_organization
from apis.models.reviews import WorkflowOut, WorkflowTransitionCreate
from apis.services.ai.compliance_engine.pipeline import run_pipeline
from apis.services.ai.llm.client import get_llm_client
from apis.services.ai.processing.chunking import Chunker
from apis.services.ai.compliance_engine.classifier import ClassifierService  # [Branch 2] document classifier
from apis.v1.routers.audit import log_audit_event

router = APIRouter(prefix="/workflows", tags=["workflows"])

chunker = Chunker()
llm_client = get_llm_client()
classifier_service = ClassifierService()  # [Branch 2] document classifier instance


async def _run_ai_analysis_for_review(db, review_id: str, triggered_by_user_id: Optional[str] = None):
    """
    Generate/update AI findings for a document review.
    SME should never see these, but we may generate them after SME approval for marketing/compliance.
    """
    review_row = await db.fetchrow(
        """
        SELECT cr.id as review_id, cr.document_version_id, dv.extracted_text, d.id as document_id
        FROM content_reviews cr
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE cr.id=$1
        """,
        review_id,
    )
    if not review_row:
        return

    rr = dict(review_row)
    version_id = rr.get("document_version_id")
    html_content = decode_extracted_text(rr.get("extracted_text")) or ""
    if not version_id or not html_content.strip():
        return

    chunks_raw = chunker.chunk_html_with_media(html_content)
    chunk_texts = [c.get("text", "") for c in chunks_raw if (c.get("text") or "").strip()]
    chunk_metadatas = [c.get("metadata", []) for c in chunks_raw if (c.get("text") or "").strip()]

    max_chunks = getattr(llm_client, "MAX_CHUNKS", 5)
    if max_chunks:
        chunk_texts = chunk_texts[:max_chunks]
        chunk_metadatas = chunk_metadatas[:max_chunks]

    # [Branch 2] 1. Document Classification (Llama 3 8B) — skip pipeline for non-educational content
    classification = classifier_service.classify_document(html_content)
    is_educational = classification.get("detected_type") == "educational_content"

    pipeline_result = None
    skip_analysis = False

    if not is_educational:
        skip_analysis = True
    else:
        # Run synchronous pipeline in a thread to avoid blocking the async event loop
        document_id = str(rr.get("document_id") or review_id)
        pipeline_result = await asyncio.to_thread(
            lambda: run_pipeline(
                chunks=chunk_texts,
                llm_client=llm_client,
                document_id=document_id,
                metadata_dicts=chunk_metadatas,
            )
        )

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    compliance_status = "pass"
    if not skip_analysis and pipeline_result:
        highest_severity = "low"
        for violation in pipeline_result.violations:
            if violation.severity.lower() == "high":
                highest_severity = "high"
            elif violation.severity.lower() == "medium" and highest_severity != "high":
                highest_severity = "medium"

        compliance_status = "conditional" if pipeline_result.violations else "pass"
        if highest_severity == "high":
            compliance_status = "fail"

    rules_rows = await db.fetch("SELECT id, rule_code FROM compliance_rules")
    rule_map = {row["rule_code"]: row["id"] for row in rules_rows}

    async with db.transaction():
        try:
            await db.execute(
                "UPDATE content_reviews SET compliance_status=$1, updated_at=$2 WHERE id=$3",
                compliance_status,
                now_utc,
                review_id,
            )
        except asyncpg.UndefinedColumnError:
            await db.execute(
                "UPDATE content_reviews SET updated_at=$1 WHERE id=$2",
                now_utc,
                review_id,
            )

        await db.execute("DELETE FROM ai_findings WHERE review_id=$1", review_id)

        if skip_analysis:
            # [Branch 2] Insert a professional "out of scope" notice so the UI shows something meaningful
            rule_id = list(rule_map.values())[0] if rule_map else None
            if rule_id:
                await db.execute(
                    """
                    INSERT INTO ai_findings (
                        id, finding_code, review_id, rule_id, title, risk_level, description,
                        why_risky, rationale, ai_suggestion, location, status, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', $12)
                    """,
                    str(uuid.uuid4()),
                    f"FIND-{int(now_utc.timestamp())}-SKIP",
                    review_id,
                    rule_id,
                    "Document Out of Scope",
                    "LOW",
                    "Compliance analysis skipped: This document was identified as non-educational content and is out of scope.",
                    "N/A - This content does not fall under standard compliance review requirements.",
                    "The internal AI classifier determined that this document is not 'Educational Content'.",
                    "No compliance action needed.",
                    "Document Level",
                    now_utc,
                )
        elif pipeline_result:
            for idx, violation in enumerate(pipeline_result.violations):
                finding_id = str(uuid.uuid4())
                rule_id = None
                for rule_code, mapped_rule_id in rule_map.items():
                    if rule_code.endswith(f"0{violation.rule}") or rule_code.endswith(str(violation.rule)):
                        rule_id = mapped_rule_id
                        break

                # These must stay inside the for loop (bug-fix applied to Branch 2)
                if not rule_id and rule_map:
                    rule_id = list(rule_map.values())[0]
                if not rule_id:
                    continue

                # Map AI response fields correctly
                why_risky = getattr(violation, "would_break_compliance", "").strip()
                if not why_risky and violation.reasoning:
                    why_risky = violation.reasoning.strip()

                rationale = getattr(violation, "what_was_checked", "").strip()
                if not rationale:
                    rationale = (
                        f"NI 31-103 Rule {violation.rule} ({violation.rule_name}) prohibits {violation.rule_name.lower()}. "
                        f"The evaluation checked whether the claim complies with this requirement."
                    )

                await db.execute(
                    """
                    INSERT INTO ai_findings (
                        id, finding_code, review_id, rule_id, title, risk_level, description,
                        why_risky, rationale, ai_suggestion, location, status, claim_id, claim_text, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', $12, $13, $14)
                    """,
                    finding_id,
                    f"FIND-{int(now_utc.timestamp())}-{idx}",
                    review_id,
                    rule_id,
                    f"Violation of Rule {violation.rule}: {violation.rule_name}",
                    violation.severity.upper(),
                    violation.reasoning[:200] + "..." if len(violation.reasoning) > 200 else violation.reasoning,
                    why_risky,
                    rationale,
                    violation.suggested_alternative or "No alternative provided.",
                    f"Chunk {violation.chunk_index}" if violation.chunk_index != -1 else "Document Level",  # [Branch 1] "Chunk X" label
                    getattr(violation, "claim_id", "") or "",
                    getattr(violation, "claim_text", "") or "",
                    now_utc,
                )

    # Log AI analysis completed
    # [Bug-fix] Guard against pipeline_result being None when skip_analysis=True
    findings_saved = len(pipeline_result.violations) if pipeline_result else 0
    if triggered_by_user_id:
        await log_audit_event(
            db,
            review_id=review_id,
            event_type="ai_analysis_completed",
            description=f"AI compliance analysis completed - {findings_saved} findings identified",
            is_ai=True,
            details=f"Total violations: {findings_saved}, Findings saved: {findings_saved}",
            triggered_by_user_id=triggered_by_user_id,
        )


@router.get("/{review_id}", response_model=WorkflowOut)
async def get_workflow_for_review(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Returns the workflow container and all historical steps for a specific review.
    """
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    workflow_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_id)
    if not workflow_row:
        raise HTTPException(status_code=404, detail="Workflow not found for this review")

    workflow = dict(workflow_row)
    if workflow.get("current_stage") == "sme_approved":
        workflow["current_stage"] = "marketing_review"
    elif workflow.get("current_stage") == "compliance_approved":
        workflow["current_stage"] = "approved"
    step_rows = await db.fetch(
        """
        SELECT ws.*,
               cb.full_name as completed_by_name,
               clb.full_name as claimed_by_name
        FROM workflow_steps ws
        LEFT JOIN user_profiles cb ON ws.completed_by = cb.id
        LEFT JOIN user_profiles clb ON ws.claimed_by = clb.id
        WHERE ws.workflow_id=$1
        ORDER BY ws.step_order ASC, ws.created_at ASC
        """,
        workflow_row["id"],
    )
    steps = []
    for step in step_rows:
        sd = dict(step)
        # Attach human-readable user name for the frontend
        sd["user_name"] = sd.get("completed_by_name") or sd.get("claimed_by_name") or "System"
        steps.append(sd)
    workflow["steps"] = steps
    return WorkflowOut(**workflow)


@router.post("/{review_id}/transition", response_model=WorkflowOut)
async def transition_workflow(
    review_id: str,
    payload: WorkflowTransitionCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Moves a review to the next workflow stage based on the action provided.
    Records the interaction in `workflow_steps`.
    """
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    user_id = (current_user or {}).get("id")
    roles = set((current_user or {}).get("roles") or [])
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    workflow_row = await db.fetchrow(
        "SELECT id, current_stage, assigned_to, assigned_role FROM workflows WHERE review_id=$1",
        review_id,
    )
    if not workflow_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow = dict(workflow_row)
    workflow_id = workflow["id"]
    previous_stage = workflow["current_stage"]
    # Normalize legacy stage names so old records still follow current workflow.
    if previous_stage == "sme_approved":
        previous_stage = "marketing_review"
    elif previous_stage == "compliance_approved":
        previous_stage = "approved"
    assigned_to = workflow.get("assigned_to")
    action = payload.action.lower()
    next_stage = previous_stage

    def require_any(required: set[str]):
        if not roles.intersection(required):
            raise HTTPException(status_code=403, detail="Permission denied for this action")

    def require_assigned_reviewer():
        if assigned_to and str(assigned_to) != str(user_id):
            raise HTTPException(status_code=403, detail="This review is assigned to another user")
        if not assigned_to:
            raise HTTPException(status_code=409, detail="You must claim this review before taking action")

    if previous_stage == "sme_review":
        if action == "claim":
            require_any({"sme"})
            if assigned_to and str(assigned_to) != str(user_id):
                raise HTTPException(status_code=409, detail="Already claimed by another reviewer")
            next_stage = "sme_review"
        elif action in {"approve", "sme_approve"}:
            require_any({"sme"})
            require_assigned_reviewer()
            next_stage = "marketing_review"
        elif action in {"request_changes", "needs_revision"}:
            require_any({"sme"})
            require_assigned_reviewer()
            next_stage = "marketing_review"
        elif action == "reject":
            require_any({"sme"})
            require_assigned_reviewer()
            next_stage = "rejected"
        elif action in {"assign", "assign_sme"}:
            require_any({"marketing"})
            next_stage = "sme_review"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action '{payload.action}' for stage '{previous_stage}'")

    elif previous_stage == "marketing_review":
        if action in {"approve", "submit_to_compliance"}:
            require_any({"marketing"})
            next_stage = "compliance_review"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action '{payload.action}' for stage '{previous_stage}'")

    elif previous_stage == "compliance_review":
        if action == "claim":
            require_any({"compliance"})
            if assigned_to and str(assigned_to) != str(user_id):
                raise HTTPException(status_code=409, detail="Already claimed by another reviewer")
            next_stage = "compliance_review"
        elif action in {"approve_and_lock", "lock"}:
            require_any({"compliance"})
            require_assigned_reviewer()
            next_stage = "approved"
        elif action == "reject":
            require_any({"compliance"})
            require_assigned_reviewer()
            next_stage = "rejected"
        elif action in {"request_changes", "needs_revision"}:
            require_any({"compliance"})
            require_assigned_reviewer()
            next_stage = "marketing_review"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action '{payload.action}' for stage '{previous_stage}'")

    elif previous_stage == "approved":
        if action == "publish":
            require_any({"marketing"})
            require_assigned_reviewer()
            next_stage = "published"
        elif action in {"keep", "hold"}:
            require_any({"marketing"})
            next_stage = "approved"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action '{payload.action}' for stage '{previous_stage}'")

    elif previous_stage == "needs_revision":
        if action in {"resubmit", "resubmit_to_sme"}:
            require_any({"marketing"})
            next_stage = "sme_review"
        elif action == "resubmit_to_compliance":
            require_any({"marketing"})
            next_stage = "compliance_review"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action '{payload.action}' for stage '{previous_stage}'")

    elif previous_stage in {"rejected", "published"}:
        raise HTTPException(status_code=409, detail=f"Workflow is already in terminal stage '{previous_stage}'")

    else:
        raise HTTPException(status_code=400, detail=f"Unknown workflow stage '{previous_stage}'")

    latest_step_order = await db.fetchval("SELECT MAX(step_order) FROM workflow_steps WHERE workflow_id=$1", workflow_id)
    step_order = (latest_step_order or 0) + 1

    async with db.transaction():
        stage_changed = next_stage != previous_stage
        new_assignee = assigned_to
        new_assigned_role = workflow.get("assigned_role")

        if action in {"assign", "assign_sme", "submit_to_sme", "resubmit_to_sme", "send_to_sme"}:
            new_assignee = str(payload.assign_to) if payload.assign_to else None
        elif action in {"approve", "submit_to_compliance", "resubmit_to_compliance"} and next_stage == "compliance_review":
            new_assignee = str(payload.assign_to) if payload.assign_to else None
        elif action in {"approve_and_lock", "lock"} and next_stage == "approved":
            # Assign back to original submitter for publishing
            submitted_by = await db.fetchval(
                """
                SELECT d.submitted_by
                FROM content_reviews cr
                JOIN document_versions dv ON cr.document_version_id = dv.id
                JOIN documents d ON dv.document_id = d.id
                WHERE cr.id = $1
                """,
                review_id
            )
            new_assignee = str(payload.assign_to) if payload.assign_to else (str(submitted_by) if submitted_by else None)
        elif stage_changed:
            new_assignee = None

        if next_stage == "sme_review":
            new_assigned_role = "sme"
        elif next_stage in {"marketing_review", "approved", "published"}:
            new_assigned_role = "marketing"
        elif next_stage == "compliance_review":
            new_assigned_role = "compliance"

        result = await db.execute(
            """
            UPDATE workflows
            SET current_stage = $1,
                assigned_to = $2,
                assigned_role = $3,
                updated_at = $4
            WHERE id = $5 AND current_stage = $6
            """,
            next_stage,
            new_assignee,
            new_assigned_role,
            now_utc,
            workflow_id,
            workflow["current_stage"],
        )

        if result == "UPDATE 0":
            raise HTTPException(
                status_code=409,
                detail="Workflow state changed concurrently. Please refresh and try again."
            )

        if previous_stage == "compliance_review" and action in {"approve_and_lock", "lock"}:
            await db.execute(
                """
                UPDATE content_reviews
                SET is_locked = TRUE,
                    locked_at = $1,
                    locked_by = $2,
                    review_status = 'locked',
                    updated_at = $1
                WHERE id = $3
                """,
                now_utc,
                user_id,
                review_id,
            )
            try:
                await db.execute(
                    "UPDATE workflows SET locked=TRUE, locked_by=$1, locked_at=$2 WHERE id=$3",
                    user_id,
                    now_utc,
                    workflow_id,
                )
            except asyncpg.UndefinedColumnError:
                pass

        if next_stage == "published":
            version_id = await db.fetchval(
                "SELECT document_version_id FROM content_reviews WHERE id=$1",
                review_id,
            )
            if version_id:
                await db.execute("UPDATE document_versions SET status='published' WHERE id=$1", version_id)

            await db.execute(
                "UPDATE content_reviews SET review_status='approved', updated_at=$1 WHERE id=$2",
                now_utc,
                review_id,
            )

            try:
                await db.execute(
                    "UPDATE workflows SET published=TRUE, published_by=$1, published_at=$2 WHERE id=$3",
                    user_id,
                    now_utc,
                    workflow_id,
                )
            except asyncpg.UndefinedColumnError:
                pass
        elif next_stage == "rejected":
            await db.execute(
                "UPDATE content_reviews SET review_status='rejected', updated_at=$1 WHERE id=$2",
                now_utc,
                review_id,
            )
        elif next_stage in {"sme_review", "marketing_review", "compliance_review"}:
            await db.execute(
                "UPDATE content_reviews SET review_status='pending', updated_at=$1 WHERE id=$2",
                now_utc,
                review_id,
            )

        await db.execute(
            """
            INSERT INTO workflow_steps (
                id, workflow_id, stage, action, comment,
                claimed_by, claimed_at,
                completed_by, completed_at,
                previous_stage, step_order, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            str(uuid.uuid4()),
            workflow_id,
            next_stage,
            payload.action,
            payload.comment,
            user_id if action == "claim" else None,
            now_utc if action == "claim" else None,
            user_id if action != "claim" else None,
            now_utc if action != "claim" else None,
            previous_stage,
            step_order,
            now_utc,
        )

        # Get user role for audit logging
        role_row = await db.fetchrow(
            "SELECT string_agg(r.name, ', ' ORDER BY r.name) as names FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = $1",
            user_id,
        )
        user_role = role_row["names"] if role_row and role_row["names"] else "unknown"

        # Log audit events based on action type
        if action == "claim":
            await log_audit_event(
                db,
                review_id=review_id,
                event_type="review_claimed",
                description=f"Review claimed in {next_stage} stage",
                user_id=user_id,
                user_role=user_role,
                workflow_stage=next_stage,
            )
        elif stage_changed:
            # Log workflow stage change
            await log_audit_event(
                db,
                review_id=review_id,
                event_type="workflow_stage_changed",
                description=f"Workflow moved from {previous_stage} to {next_stage}",
                user_id=user_id,
                user_role=user_role,
                workflow_stage=next_stage,
                details=f"Previous stage: {previous_stage}, New stage: {next_stage}",
            )

            # Log specific action events
            if action in {"approve", "sme_approve"}:
                await log_audit_event(
                    db,
                    review_id=review_id,
                    event_type="review_completed",
                    description=f"Review approved and moved to {next_stage}",
                    user_id=user_id,
                    user_role=user_role,
                    workflow_stage=next_stage,
                    details=payload.comment,
                )
            elif action == "reject":
                await log_audit_event(
                    db,
                    review_id=review_id,
                    event_type="review_completed",
                    description="Review rejected",
                    user_id=user_id,
                    user_role=user_role,
                    workflow_stage=next_stage,
                    details=payload.comment,
                )
            elif action in {"request_changes", "needs_revision"}:
                await log_audit_event(
                    db,
                    review_id=review_id,
                    event_type="changes_requested",
                    description="Changes requested",
                    user_id=user_id,
                    user_role=user_role,
                    workflow_stage=next_stage,
                    details=payload.comment,
                )
            elif action in {"approve_and_lock", "lock"}:
                await log_audit_event(
                    db,
                    review_id=review_id,
                    event_type="document_locked",
                    description="Document approved and locked",
                    user_id=user_id,
                    user_role=user_role,
                    workflow_stage=next_stage,
                    details=payload.comment,
                )
            elif action == "publish":
                await log_audit_event(
                    db,
                    review_id=review_id,
                    event_type="document_published",
                    description="Document published",
                    user_id=user_id,
                    user_role=user_role,
                    workflow_stage=next_stage,
                    details=payload.comment,
                )

    workflow_out = await get_workflow_for_review(review_id, db)

    # [Branch 1] Generate compliance report after compliance_review approve/lock or reject
    if previous_stage == "compliance_review" and action in {"approve_and_lock", "lock", "reject"}:
        status = "compliant" if action in {"approve_and_lock", "lock"} else "non_compliant"
        await db.execute("UPDATE content_reviews SET compliance_status=$1 WHERE id=$2", status, review_id)
        from apis.services.reports import generate_compliance_report
        await generate_compliance_report(db, review_id, str(user_id), user_role)

    # [Branch 2] Trigger AI analysis (with classifier gating) after SME approval
    if previous_stage == "sme_review" and action in {"approve", "sme_approve"}:
        background_tasks.add_task(_run_ai_analysis_for_review, db, review_id, user_id)

    try:
        from apis.services.realtime_streams import publish_review_comment
        doc_id = await db.fetchval(
            "SELECT d.id FROM documents d JOIN document_versions dv ON d.id = dv.document_id JOIN content_reviews cr ON dv.id = cr.document_version_id WHERE cr.id = $1", review_id
        )
        if doc_id:
            await publish_review_comment(
                review_id,
                {
                    "event": "workflow_stage_changed",
                    "doc_id": str(doc_id),
                    "action": action,
                    "from_stage": previous_stage,
                    "to_stage": next_stage,
                    "created_at": now_utc.isoformat(),
                },
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to publish workflow event from generic transition: %s", e)

    return workflow_out