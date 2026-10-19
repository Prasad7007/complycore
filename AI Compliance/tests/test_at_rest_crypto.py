"""Tests for ``apis.core.at_rest_crypto``."""

from __future__ import annotations

import base64
import os
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apis.core import at_rest_crypto  # noqa: E402


def _set_key(monkeypatch: pytest.MonkeyPatch, key_bytes: bytes | None) -> None:
    if key_bytes is None:
        monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", base64.b64encode(key_bytes).decode("ascii"))
    at_rest_crypto._reset_key_cache_for_tests()


def test_no_key_is_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, None)
    assert at_rest_crypto.is_at_rest_encryption_configured() is False
    assert at_rest_crypto.encrypt_text("hello") == "hello"
    assert at_rest_crypto.decrypt_text("hello") == "hello"
    assert at_rest_crypto.encrypt_text(None) is None
    assert at_rest_crypto.decrypt_text(None) is None


def test_round_trip_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, secrets.token_bytes(32))
    assert at_rest_crypto.is_at_rest_encryption_configured() is True

    plaintext = "Compliance content — \u00e9\u00e8 \U0001f512 lines of text"
    encoded = at_rest_crypto.encrypt_text(plaintext)
    assert encoded is not None
    assert encoded.startswith("ENCv1:")
    assert encoded != plaintext
    decoded = at_rest_crypto.decrypt_text(encoded)
    assert decoded == plaintext


def test_legacy_plaintext_decrypt_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, secrets.token_bytes(32))
    # Legacy rows lack the ENCv1: prefix and must round-trip through decrypt unchanged.
    assert at_rest_crypto.decrypt_text("legacy raw content") == "legacy raw content"


def test_double_encrypt_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, secrets.token_bytes(32))
    once = at_rest_crypto.encrypt_text("payload")
    twice = at_rest_crypto.encrypt_text(once)
    assert once == twice


def test_nonces_differ_for_same_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, secrets.token_bytes(32))
    a = at_rest_crypto.encrypt_text("same text")
    b = at_rest_crypto.encrypt_text("same text")
    assert a != b
    assert at_rest_crypto.decrypt_text(a) == "same text"
    assert at_rest_crypto.decrypt_text(b) == "same text"


def test_invalid_key_length(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, secrets.token_bytes(16))  # AES-128 length, not allowed
    with pytest.raises(at_rest_crypto.EncryptionConfigError):
        at_rest_crypto.is_at_rest_encryption_configured()


def test_encrypted_value_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Produce a ciphertext with a real key...
    _set_key(monkeypatch, secrets.token_bytes(32))
    encoded = at_rest_crypto.encrypt_text("secret")
    # ...then drop the key and verify we don't silently return ciphertext.
    _set_key(monkeypatch, None)
    with pytest.raises(at_rest_crypto.EncryptionConfigError):
        at_rest_crypto.decrypt_text(encoded)


def test_wrong_key_fails_auth_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, secrets.token_bytes(32))
    encoded = at_rest_crypto.encrypt_text("secret")
    # Rotate the env to a different key.
    _set_key(monkeypatch, secrets.token_bytes(32))
    with pytest.raises(at_rest_crypto.EncryptionConfigError):
        at_rest_crypto.decrypt_text(encoded)


def test_url_safe_base64_key_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = secrets.token_bytes(32)
    # Some operators paste URL-safe base64; the loader should accept both.
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", base64.urlsafe_b64encode(raw).decode("ascii"))
    at_rest_crypto._reset_key_cache_for_tests()
    encoded = at_rest_crypto.encrypt_text("ok")
    assert at_rest_crypto.decrypt_text(encoded) == "ok"
