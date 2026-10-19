"""Static checks that canonical schema still encodes org isolation constraints."""

from pathlib import Path


def _schema_text() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "schema.sql").read_text(encoding="utf-8")


def test_schema_organization_users_single_membership_key():
    text = _schema_text()
    assert "organization_users_user_id_key" in text


def test_schema_documents_unique_code_per_org():
    text = _schema_text()
    assert "documents_organization_id_document_code_key" in text


def test_migration_0009_present():
    root = Path(__file__).resolve().parents[1]
    m = (root / "migrations" / "0009_documents_organization_id_and_single_org_user.sql").read_text(
        encoding="utf-8"
    )
    assert "organization_id" in m
    assert "documents" in m


def test_migration_0010_invites_present():
    root = Path(__file__).resolve().parents[1]
    m = (root / "migrations" / "0010_organization_invites.sql").read_text(encoding="utf-8")
    assert "organization_invites" in m
