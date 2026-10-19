"""Phase 3: approve-step branded workflow emails."""
from apis.core.email_renderer import (
    build_workflow_context,
    render_email,
    resolve_workflow_template_id,
)


def test_resolve_workflow_template_id_sme_approve():
    assert (
        resolve_workflow_template_id(
            "sme_review",
            "marketing_review",
            workflow_action="approve",
        )
        == "workflow_sme_approve"
    )


def test_resolve_workflow_template_id_to_compliance():
    assert (
        resolve_workflow_template_id("marketing_review", "compliance_review")
        == "workflow_to_compliance"
    )


def test_resolve_workflow_template_id_compliance_approve():
    assert (
        resolve_workflow_template_id(
            "compliance_review",
            "approved",
            workflow_action="approve",
        )
        == "workflow_compliance_approve"
    )


def test_sme_approve_not_confused_with_request_changes():
    assert (
        resolve_workflow_template_id(
            "sme_review",
            "marketing_review",
            workflow_action="request_changes",
        )
        == "workflow_sme_changes"
    )
    assert (
        resolve_workflow_template_id("sme_review", "marketing_review")
        is None
    )


def test_render_workflow_sme_approve_ai_step():
    ctx = build_workflow_context(
        "workflow_sme_approve",
        recipient_name="becky",
        document_name="Q2 Brochure",
        actor_name="SME User",
        from_stage="sme_review",
        to_stage="marketing_review",
        doc_id="doc-1",
        org_slug="acme",
    )
    subject, text, html = render_email("workflow_sme_approve", ctx)
    assert "approved by SME" in subject
    assert "SME review approved" in html
    assert "AI Analysis" in html
    assert "Compliance Review" not in html
    assert "Approved" in html
    assert "AI Analysis" in text


def test_render_workflow_to_compliance():
    ctx = build_workflow_context(
        "workflow_to_compliance",
        recipient_name="becky",
        document_name="Q2 Brochure",
        actor_name="Marketing User",
        from_stage="marketing_review",
        to_stage="compliance_review",
        doc_id="doc-1",
        org_slug="acme",
    )
    subject, _, html = render_email("workflow_to_compliance", ctx)
    assert "compliance review" in subject.lower()
    assert "compliance review" in html.lower()
    assert "Start compliance review" in html


def test_render_workflow_compliance_approve():
    ctx = build_workflow_context(
        "workflow_compliance_approve",
        recipient_name="becky",
        document_name="Q2 Brochure",
        actor_name="Compliance User",
        from_stage="compliance_review",
        to_stage="approved",
        doc_id="doc-1",
        org_slug="acme",
    )
    subject, _, html = render_email("workflow_compliance_approve", ctx)
    assert "approved by Compliance" in subject
    assert "Ready to publish" in html
    assert "Approved" in html
