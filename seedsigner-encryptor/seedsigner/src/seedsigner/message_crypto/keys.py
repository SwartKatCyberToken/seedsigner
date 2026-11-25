"""Cached message keys derived from one BIP-39 seed.

Does not draw the UI or choose Bitcoin keys. Views call keys_for_seed with
Seed.seed_bytes. The cache lives in process memory and is dropped by
forget_seed_bytes when the controller discards that seed. It is not written
to the SD card.
"""

import hashlib

from seedsigner.message_crypto.derivation import (
    BIP39_SEED_LENGTH,
    LABEL_ML_DSA,
    LABEL_ML_KEM,
    LABEL_RSA_ENCRYPT,
    LABEL_RSA_SIGN,
    ML_DSA_SEED_LENGTH,
    ML_KEM_SEED_LENGTH,
    RSA_STREAM_LENGTH,
    derive_material,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.ml_dsa_ops import keypair as mldsa_keypair
from seedsigner.message_crypto.ml_kem_ops import keypair as mlkem_keypair
from seedsigner.message_crypto.rsa_ops import RSA_BITS, generate_rsa

_CACHE = {}


class MessageKeys:
    """Lazy key objects for one seed and one RSA bit length."""

    def __init__(self, seed_bytes: bytes, rsa_bits: int = RSA_BITS):
        if len(seed_bytes) != BIP39_SEED_LENGTH:
            raise MessageCryptoError(
                f"BIP-39 seed must be {BIP39_SEED_LENGTH} bytes, got {len(seed_bytes)}"
            )
        self._seed = seed_bytes
        self.rsa_bits = rsa_bits
        self._rsa_sign = None
        self._rsa_encrypt = None
        self._ml_dsa = None
        self._ml_kem = None

    def rsa_signing_key(self):
        if self._rsa_sign is None:
            material = derive_material(self._seed, LABEL_RSA_SIGN, RSA_STREAM_LENGTH)
            self._rsa_sign = generate_rsa(material, self.rsa_bits)
        return self._rsa_sign

    def rsa_encryption_key(self):
        if self._rsa_encrypt is None:
            material = derive_material(self._seed, LABEL_RSA_ENCRYPT, RSA_STREAM_LENGTH)
            self._rsa_encrypt = generate_rsa(material, self.rsa_bits)
        return self._rsa_encrypt

    def ml_dsa_keys(self) -> tuple:
        if self._ml_dsa is None:
            material = derive_material(self._seed, LABEL_ML_DSA, ML_DSA_SEED_LENGTH)
            self._ml_dsa = mldsa_keypair(material)
        return self._ml_dsa

    def ml_kem_keys(self) -> tuple:
        if self._ml_kem is None:
            material = derive_material(self._seed, LABEL_ML_KEM, ML_KEM_SEED_LENGTH)
            self._ml_kem = mlkem_keypair(material)
        return self._ml_kem


def keys_for_seed(seed_bytes: bytes, rsa_bits: int = RSA_BITS) -> MessageKeys:
    """Return the cached MessageKeys for this seed, generating them on a miss."""
    token = hashlib.sha256(seed_bytes).digest()
    found = _CACHE.get(token)
    if found is not None and found.rsa_bits == rsa_bits:
        return found
    created = MessageKeys(seed_bytes, rsa_bits=rsa_bits)
    _CACHE[token] = created
    return created


def forget_seed_bytes(seed_bytes: bytes) -> None:
    """Drop cached keys for this seed. Missing entries are ignored."""
    if not isinstance(seed_bytes, (bytes, bytearray)):
        return
    _CACHE.pop(hashlib.sha256(bytes(seed_bytes)).digest(), None)


def clear_cache() -> None:
    """Drop every cached key. Tests use this between cases."""
    _CACHE.clear()
