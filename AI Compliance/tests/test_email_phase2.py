"""Phase 2: author-facing post-classification emails."""
from apis.core.email_renderer import (
    build_collab_document_uploaded_context,
    build_submission_received_context,
    render_email,
    resolve_submission_route,
    submission_route_stage_labels,
)
from apis.v1.routers.documents import is_document_reupload


def test_resolve_submission_route_sme():
    assert resolve_submission_route("sme_review") == "sme"


def test_resolve_submission_route_ai():
    assert resolve_submission_route("marketing_review") == "ai"


def test_submission_route_stage_labels_ai():
    assert submission_route_stage_labels("ai") == ("AI Analysis", "AI Analysis")


def test_submission_route_stage_labels_sme():
    assert submission_route_stage_labels("sme") == ("SME Review", "SME Review")


def test_is_document_reupload():
    assert is_document_reupload(1) is False
    assert is_document_reupload(2) is True


def test_render_submission_received_sme_variant():
    ctx = build_submission_received_context(
        recipient_name="becky",
        document_name="Q2 Brochure",
        doc_id="doc-1",
        route="sme",
        org_slug="acme",
    )
    subject, text, html = render_email("workflow_submission_received", ctx)
    assert "We've received Q2 Brochure" in subject
    assert "Submission received" in html
    assert "SME Review" in html
    assert "Document Upload" in html
    assert "View status" in html
    assert "SME Review" in text


def test_render_submission_received_ai_variant():
    ctx = build_submission_received_context(
        recipient_name="becky",
        document_name="Q2 Brochure",
        doc_id="doc-1",
        route="ai",
        org_slug="acme",
    )
    _, _, html = render_email("workflow_submission_received", ctx)
    assert "AI Analysis" in html
    assert "SME Review" not in html


def test_render_collab_document_uploaded():
    ctx = build_collab_document_uploaded_context(
        recipient_name="becky",
        document_name="Q2 Brochure",
        doc_id="doc-1",
        version_label="1.1",
        org_slug="acme",
    )
    subject, text, html = render_email("collab_document_uploaded", ctx)
    assert "New version uploaded" in subject
    assert "version 1.1" in html
    assert "You uploaded" in html
    assert "Open document" in html
    assert "1.1" in text
