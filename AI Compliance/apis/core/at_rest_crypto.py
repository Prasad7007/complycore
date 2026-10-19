"""AES-256-GCM helpers for application-level (at-rest) encryption of TEXT columns.

On-disk format
--------------
Encrypted strings carry the ``ENCv1:`` prefix followed by URL-safe base64 of
``nonce || ciphertext+tag``:

    ENCv1:<b64url(nonce(12B) || ciphertext || tag(16B))>

This lets us share a single ``TEXT`` column with legacy plaintext rows: values
without the prefix are returned as-is on read, and only get the prefix on the
next write.

Key
---
``DATA_ENCRYPTION_KEY`` is the base64 (standard or URL-safe) of 32 random bytes::

    python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

When the variable is missing or empty, the helpers are a no-op: writes return
the plaintext and reads return the value unchanged. This keeps development and
local tests friction-free while still enforcing encryption in production by
setting the variable.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import secrets
from functools import lru_cache
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# Version tag and per-record sizes (AES-GCM standard).
_ENC_PREFIX = "ENCv1:"
_NONCE_LEN = 12  # bytes
_KEY_LEN = 32  # bytes (AES-256)
_ENV_VAR = "DATA_ENCRYPTION_KEY"


class EncryptionConfigError(RuntimeError):
    """Raised when ``DATA_ENCRYPTION_KEY`` is set but invalid."""


def _decode_key(raw: str) -> bytes:
    """Decode a key from base64 (standard or URL-safe). Raises if malformed."""
    raw = raw.strip()
    if not raw:
        raise EncryptionConfigError("DATA_ENCRYPTION_KEY is empty.")
    # Try URL-safe first (covers both alphabets when length matches).
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return decoder(raw)
        except (binascii.Error, ValueError):
            continue
    raise EncryptionConfigError("DATA_ENCRYPTION_KEY is not valid base64.")


@lru_cache(maxsize=1)
def _load_key() -> Optional[bytes]:
    """Load and validate the key once. Returns ``None`` when not configured."""
    raw = os.environ.get(_ENV_VAR, "")
    if not raw or not raw.strip():
        return None
    key = _decode_key(raw)
    if len(key) != _KEY_LEN:
        raise EncryptionConfigError(
            f"DATA_ENCRYPTION_KEY must decode to {_KEY_LEN} bytes (AES-256); got {len(key)}."
        )
    return key


def is_at_rest_encryption_configured() -> bool:
    """True when ``DATA_ENCRYPTION_KEY`` is set to a valid 32-byte key."""
    try:
        return _load_key() is not None
    except EncryptionConfigError:
        # Surface configuration errors early at the call site rather than silently disabling.
        raise


def _reset_key_cache_for_tests() -> None:
    """Test-only hook to force re-reading the environment variable."""
    _load_key.cache_clear()


def is_encrypted(value: Optional[str]) -> bool:
    """True iff ``value`` looks like an ``ENCv1:`` blob produced by this module."""
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


def encrypt_text(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string for storage in a ``TEXT`` column.

    - ``None`` round-trips as ``None``.
    - When no key is configured, returns ``plaintext`` unchanged (no-op mode).
    - Otherwise returns ``ENCv1:<b64url(nonce || ciphertext+tag)>``.
    - Already-encrypted inputs (``ENCv1:``-prefixed) are returned unchanged so
      that double-encoding is impossible at write sites.
    """
    if plaintext is None:
        return None
    if not isinstance(plaintext, str):
        raise TypeError("encrypt_text expects str or None")
    if is_encrypted(plaintext):
        return plaintext

    key = _load_key()
    if key is None:
        return plaintext

    nonce = secrets.token_bytes(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    blob = nonce + ciphertext
    return _ENC_PREFIX + base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt_text(stored: Optional[str]) -> Optional[str]:
    """Decrypt a stored ``TEXT`` value if it's an ``ENCv1:`` blob.

    Legacy plaintext (no prefix) is returned unchanged so encrypted and
    pre-encryption rows can coexist during rollout.
    """
    if stored is None:
        return None
    if not isinstance(stored, str):
        raise TypeError("decrypt_text expects str or None")
    if not is_encrypted(stored):
        return stored

    key = _load_key()
    if key is None:
        # Encrypted value but no key configured: refuse to read silently because
        # returning the ciphertext would corrupt downstream consumers.
        raise EncryptionConfigError(
            "Encountered ENCv1 ciphertext but DATA_ENCRYPTION_KEY is not configured."
        )

    payload = stored[len(_ENC_PREFIX):]
    try:
        blob = base64.urlsafe_b64decode(payload.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise EncryptionConfigError("Malformed ENCv1 payload (base64 decode failed).") from exc
    if len(blob) <= _NONCE_LEN:
        raise EncryptionConfigError("Malformed ENCv1 payload (too short).")
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
    except InvalidTag as exc:
        # Likely a key mismatch; log enough to diagnose without leaking ciphertext.
        logger.warning("at_rest_crypto: AES-GCM auth tag check failed (wrong key?)")
        raise EncryptionConfigError("Decryption failed: invalid auth tag.") from exc
    return plaintext.decode("utf-8")
