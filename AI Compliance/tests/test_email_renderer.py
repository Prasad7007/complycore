"""Tests for ComplyCore email rendering (Phase 1)."""
import os

from apis.core.email_renderer import (
    build_otp_context,
    format_otp_display,
    render_email,
    title_case_first_name,
)


def test_title_case_first_name():
    assert title_case_first_name("becky") == "Becky"
    assert title_case_first_name("") == "there"
    assert title_case_first_name("user@acme.com") == "User"


def test_format_otp_display():
    assert format_otp_display("542908") == "542 908"
    assert format_otp_display("542 908") == "542 908"


def test_render_otp_html_contains_brand_and_code():
    os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:5173")
    ctx = build_otp_context(
        recipient_name="Becky",
        otp="123456",
        expire_minutes=1,
        template_id="otp",
    )
    subject, text, html = render_email("otp", ctx)
    assert subject == "Your ComplyCore verification code"
    assert "123 456" in html
    assert "Hi Becky" in html
    assert "ComplyCore" in html
    assert "comply-core-assets.s3.ca-central-1.amazonaws.com/complycore-logo.png" in html
    assert "123 456" in text
    assert "Enter this code" in text


def test_render_password_reset_subject():
    ctx = build_otp_context(
        recipient_name="becky",
        otp="163662",
        expire_minutes=10,
        template_id="password_reset",
    )
    subject, _, html = render_email("password_reset", ctx)
    assert subject == "Reset your ComplyCore password"
    assert "163 662" in html
    assert "reset your password" in html.lower()
