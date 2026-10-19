"""Phase 1: post-classification reviewer notification gating."""
from apis.core.email_renderer import resolve_workflow_template_id
from apis.v1.routers.documents import should_notify_reviewers_after_classification


def test_should_notify_reviewers_after_classification_sme_path():
    assert should_notify_reviewers_after_classification("sme_review") is True


def test_should_notify_reviewers_after_classification_compliance_path():
    assert should_notify_reviewers_after_classification("compliance_review") is True


def test_should_notify_reviewers_after_classification_direct_ai_skipped():
    assert should_notify_reviewers_after_classification("marketing_review") is False


def test_should_notify_reviewers_after_classification_empty_stage():
    assert should_notify_reviewers_after_classification(None) is False
    assert should_notify_reviewers_after_classification("") is False


def test_resolve_workflow_template_id_to_sme_unchanged():
    assert (
        resolve_workflow_template_id("document_upload", "sme_review")
        == "workflow_to_sme"
    )
