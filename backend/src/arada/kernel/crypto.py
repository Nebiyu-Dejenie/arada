"""Envelope encryption for application-held secrets (ADR-017).

Each secret gets a fresh 256-bit data key (DEK). The secret is sealed with
AES-256-GCM under the DEK, and the DEK is wrapped under the versioned
key-encryption key (KEK). The associated data binds a ciphertext to its
table, row and tenant: a ciphertext copied onto another row fails to decrypt.

The KEK never touches the database. In Phase 1 it comes from configuration;
the ``Keyring`` interface allows a KMS or Vault transit backend later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DecryptionError(Exception):
    """Ciphertext could not be opened (wrong key, wrong AAD, or tampering)."""


@dataclass(frozen=True, slots=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    dek_nonce: bytes
    kek_version: int


def aad_for(table: str, row_id: str, tenant_id: str | None, purpose: str) -> bytes:
    return f"{table}|{row_id}|{tenant_id or '-'}|{purpose}".encode()


class Keyring:
    def __init__(self, keks: dict[int, bytes], current_version: int) -> None:
        if current_version not in keks:
            raise ValueError("current KEK version missing from keyring")
        for version, key in keks.items():
            if len(key) != 32:
                raise ValueError(f"KEK version {version} must be 32 bytes")
        self._keks = dict(keks)
        self._current = current_version

    @property
    def current_version(self) -> int:
        return self._current

    def seal(self, plaintext: bytes, *, aad: bytes) -> Sealed:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
        dek_nonce = os.urandom(12)
        wrap_aad = self._wrap_aad(self._current, aad)
        wrapped = AESGCM(self._keks[self._current]).encrypt(dek_nonce, dek, wrap_aad)
        return Sealed(ciphertext, nonce, wrapped, dek_nonce, self._current)

    def open(self, sealed: Sealed, *, aad: bytes) -> bytes:
        kek = self._keks.get(sealed.kek_version)
        if kek is None:
            raise DecryptionError("unknown KEK version")
        try:
            dek = AESGCM(kek).decrypt(
                sealed.dek_nonce, sealed.wrapped_dek, self._wrap_aad(sealed.kek_version, aad)
            )
            return AESGCM(dek).decrypt(sealed.nonce, sealed.ciphertext, aad)
        except InvalidTag as exc:
            raise DecryptionError("ciphertext failed authentication") from exc

    @staticmethod
    def _wrap_aad(version: int, aad: bytes) -> bytes:
        return b"dek|v" + str(version).encode() + b"|" + aad
