"""Domain-separated key material from a BIP-39 seed.

Does not generate RSA primes, ML-DSA keys, or ML-KEM keys, and does not call
BIP-32. MessageKeys in keys.py is the caller. Scheme salt and labels are the
v1 recovery contract: changing them creates new keys and must ship as a new
scheme id, not an edit of these constants.
"""

import hashlib
import hmac

from seedsigner.message_crypto.errors import MessageCryptoError

SCHEME_ID = "seedsigner-msg/1"
# HKDF salt. Binds every derived output to this scheme version.
SCHEME_SALT = b"seedsigner-msg/1"
BIP39_SEED_LENGTH = 64
# HMAC-SHA256 key length for the RSA generation stream.
RSA_STREAM_LENGTH = 32
# ML-DSA-44 key_derive seed (xi). FIPS 204 section 6.1.
ML_DSA_SEED_LENGTH = 32
# ML-KEM-512 key_derive seed (d || z). FIPS 203 section 7.1.
ML_KEM_SEED_LENGTH = 64

LABEL_RSA_SIGN = b"rsa-sign"
LABEL_RSA_ENCRYPT = b"rsa-encrypt"
LABEL_ML_DSA = b"ml-dsa-44"
LABEL_ML_KEM = b"ml-kem-512"

_COUNTER_WIDTH = 8
_SHA256_LENGTH = 32


def hkdf_sha256(ikm: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256 (RFC 5869) with SCHEME_SALT. info is the domain label."""
    if length < 1 or length > 255 * _SHA256_LENGTH:
        raise MessageCryptoError(f"HKDF length {length} is outside the v1 range")
    prk = hmac.new(SCHEME_SALT, ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def derive_material(seed_bytes: bytes, label: bytes, length: int) -> bytes:
    """Return domain-separated bytes. seed_bytes is the 64-byte BIP-39 seed."""
    if len(seed_bytes) != BIP39_SEED_LENGTH:
        raise MessageCryptoError(
            f"BIP-39 seed must be {BIP39_SEED_LENGTH} bytes, got {len(seed_bytes)}"
        )
    if not label:
        raise MessageCryptoError("derivation label is empty")
    return hkdf_sha256(seed_bytes, label, length)


class HmacSha256Counter:
    """Byte stream for RSA.generate(randfunc=...).

    Each call appends HMAC-SHA256(key, uint64be(counter)) blocks. The key and
    the BIP-39 seed are never returned as output. One instance serves one
    RSA.generate call; do not reuse it for signatures or encryption nonces.
    """

    def __init__(self, key: bytes):
        if len(key) != RSA_STREAM_LENGTH:
            raise MessageCryptoError(
                f"RSA stream key must be {RSA_STREAM_LENGTH} bytes, got {len(key)}"
            )
        self._key = key
        self._counter = 0
        self._buffer = b""

    def __call__(self, nbytes: int) -> bytes:
        if nbytes < 0:
            raise MessageCryptoError(f"randfunc byte count {nbytes} is negative")
        while len(self._buffer) < nbytes:
            message = self._counter.to_bytes(_COUNTER_WIDTH, "big")
            self._counter += 1
            self._buffer += hmac.new(self._key, message, hashlib.sha256).digest()
        output = self._buffer[:nbytes]
        self._buffer = self._buffer[nbytes:]
        return output
