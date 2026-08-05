"""Encryption for small secrets (OAuth tokens) using AES-256-GCM."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SIZE = 32  # AES-256 requires a 32-byte key
NONCE_SIZE = 12  # 96-bit nonce, the standard size for AES-GCM


class Encryptor:
    """Encrypts and decrypts bytes with AES-256-GCM.

    Constructed once with a fixed key; safe to reuse across the app since
    AESGCM itself holds no mutable state.
    """

    def __init__(self, base64_key: str) -> None:
        try:
            key = base64.b64decode(base64_key, validate=True)
        except Exception as exc:
            raise ValueError("encryptor: invalid base64 key") from exc

        if len(key) != KEY_SIZE:
            raise ValueError(
                f"encryptor: key must be {KEY_SIZE} bytes, got {len(key)}"
            )

        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Seal plaintext, returning nonce || ciphertext+tag.

        A fresh random nonce is generated on every call — required for GCM
        security — and prepended to the output so decrypt() can split it back
        out.
        """
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt(self, data: bytes) -> bytes:
        """Reverse encrypt(). Raises if the data is too short or fails
        authentication (tampered, or encrypted under a different key)."""
        if len(data) < NONCE_SIZE:
            raise ValueError("encryptor: ciphertext too short")

        nonce, ciphertext = data[:NONCE_SIZE], data[NONCE_SIZE:]
        return self._aesgcm.decrypt(nonce, ciphertext, None)
