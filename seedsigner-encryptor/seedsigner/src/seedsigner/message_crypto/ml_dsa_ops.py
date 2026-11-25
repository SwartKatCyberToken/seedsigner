"""ML-DSA-44 signatures through dilithium-py's seed-based key_derive.

Does not replace the library's random_bytes, and does not implement FIPS 204
itself. keys.py passes the 32-byte derived seed. Signatures are deterministic
(FIPS rnd = 0) and use ML_DSA_CONTEXT so they are tied to this scheme.
dilithium-py is a learning implementation, not a production library.
"""

from dilithium_py.ml_dsa import ML_DSA_44

from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ENVELOPE_VERSION,
    ML_DSA_CONTEXT,
    OP_PUB,
    OP_SIG_DSA,
    b64d,
    b64e,
)
from seedsigner.message_crypto.errors import MessageCryptoError

ML_DSA_PUBLIC_BYTES = 1312
ML_DSA_SIGNATURE_BYTES = 2420


def keypair(seed: bytes) -> tuple:
    """Return (public_key, secret_key) from a 32-byte xi seed."""
    try:
        public_key, secret_key = ML_DSA_44.key_derive(seed)
    except ValueError as exc:
        raise MessageCryptoError("ML-DSA seed was rejected") from exc
    if len(public_key) != ML_DSA_PUBLIC_BYTES:
        raise MessageCryptoError("ML-DSA public key has an unexpected length")
    return public_key, secret_key


def export_public(public_key: bytes) -> dict:
    _check_public(public_key)
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_PUB,
        "alg": ALG_ML_DSA,
        "pk": b64e(public_key),
    }


def import_public(document: dict) -> bytes:
    if document.get("alg") != ALG_ML_DSA:
        raise MessageCryptoError("public key alg is not ml-dsa-44")
    return _check_public(b64d(document["pk"], "pk"))


def sign(secret_key: bytes, message: bytes) -> dict:
    try:
        signature = ML_DSA_44.sign(
            secret_key, message, ctx=ML_DSA_CONTEXT, deterministic=True
        )
    except ValueError as exc:
        raise MessageCryptoError("ML-DSA signing rejected the key or message") from exc
    if len(signature) != ML_DSA_SIGNATURE_BYTES:
        raise MessageCryptoError("ML-DSA signature has an unexpected length")
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_SIG_DSA,
        "alg": ALG_ML_DSA,
        "msg": message.decode("utf-8"),
        "sig": b64e(signature),
    }


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    _check_public(public_key)
    if len(signature) != ML_DSA_SIGNATURE_BYTES:
        raise MessageCryptoError(
            f"malformed ML-DSA signature length {len(signature)}"
        )
    try:
        return bool(
            ML_DSA_44.verify(public_key, message, signature, ctx=ML_DSA_CONTEXT)
        )
    except ValueError as exc:
        raise MessageCryptoError("malformed ML-DSA signature") from exc


def _check_public(public_key: bytes) -> bytes:
    if len(public_key) != ML_DSA_PUBLIC_BYTES:
        raise MessageCryptoError(
            f"malformed ML-DSA public key length {len(public_key)}"
        )
    return public_key
