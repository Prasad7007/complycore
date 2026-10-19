"""Column-level helpers that route TEXT fields through ``at_rest_crypto``.

These are thin re-exports so the call sites read like ``encode_extracted_text(...)``
instead of importing the generic primitive. Centralising the names also makes
it easy to extend the at-rest encryption surface to more columns later (just
add ``encode_<column>`` / ``decode_<column>`` here).
"""

from __future__ import annotations

from typing import Optional

from apis.core.at_rest_crypto import decrypt_text, encrypt_text


def encode_extracted_text(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt before writing ``document_versions.extracted_text``."""
    return encrypt_text(plaintext)


def decode_extracted_text(stored: Optional[str]) -> Optional[str]:
    """Decrypt after reading ``document_versions.extracted_text``."""
    return decrypt_text(stored)
