"""ML-KEM-512 key establishment plus AES-256-GCM for the message.

Does not encrypt the message with ML-KEM directly. key_derive takes the
64-byte d||z seed. Encapsulation randomness stays inside kyber-py.
The 32-byte shared secret is the AES-256 key, with no extra KDF; changing
that would be a new envelope version. kyber-py is a learning implementation,
not a production library.
"""

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from kyber_py.ml_kem import ML_KEM_512

from seedsigner.message_crypto.codec import (
    AAD_KEM,
    ALG_KEM_HYBRID,
    ALG_ML_KEM,
    ENVELOPE_VERSION,
    OP_ENC_KEM,
    OP_PUB,
    b64d,
    b64e,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.rsa_ops import AES_KEY_BYTES, GCM_NONCE_BYTES, GCM_TAG_BYTES

ML_KEM_ENCAPSULATION_KEY_BYTES = 800
ML_KEM_CIPHERTEXT_BYTES = 768


def keypair(seed: bytes) -> tuple:
    """Return (encapsulation_key, decapsulation_key) from a 64-byte seed."""
    try:
        encapsulation_key, decapsulation_key = ML_KEM_512.key_derive(seed)
    except ValueError as exc:
        raise MessageCryptoError("ML-KEM seed was rejected") from exc
    if len(encapsulation_key) != ML_KEM_ENCAPSULATION_KEY_BYTES:
        raise MessageCryptoError("ML-KEM encapsulation key has an unexpected length")
    return encapsulation_key, decapsulation_key


def export_public(encapsulation_key: bytes) -> dict:
    _check_encapsulation_key(encapsulation_key)
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_PUB,
        "alg": ALG_ML_KEM,
        "ek": b64e(encapsulation_key),
    }


def import_public(document: dict) -> bytes:
    if document.get("alg") != ALG_ML_KEM:
        raise MessageCryptoError("public key alg is not ml-kem-512")
    return _check_encapsulation_key(b64d(document["ek"], "ek"))


def encapsulate(encapsulation_key: bytes, plaintext: bytes) -> dict:
    _check_encapsulation_key(encapsulation_key)
    try:
        shared_secret, kem_ciphertext = ML_KEM_512.encaps(encapsulation_key)
    except ValueError as exc:
        raise MessageCryptoError("ML-KEM rejected the encapsulation key") from exc
    if len(shared_secret) != AES_KEY_BYTES or len(kem_ciphertext) != ML_KEM_CIPHERTEXT_BYTES:
        raise MessageCryptoError("ML-KEM encapsulation returned an unexpected length")
    nonce = get_random_bytes(GCM_NONCE_BYTES)
    cipher = AES.new(shared_secret, AES.MODE_GCM, nonce=nonce)
    cipher.update(AAD_KEM)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_ENC_KEM,
        "alg": ALG_KEM_HYBRID,
        "ek": b64e(kem_ciphertext),
        "nonce": b64e(nonce),
        "ct": b64e(ciphertext),
        "tag": b64e(tag),
    }


def decapsulate(decapsulation_key: bytes, document: dict) -> bytes:
    if document.get("op") != OP_ENC_KEM:
        raise MessageCryptoError("ciphertext is not enc-kem")
    nonce = b64d(document["nonce"], "nonce")
    tag = b64d(document["tag"], "tag")
    kem_ciphertext = b64d(document["ek"], "ek")
    if len(nonce) != GCM_NONCE_BYTES or len(tag) != GCM_TAG_BYTES:
        raise MessageCryptoError("enc-kem nonce or tag has the wrong length")
    if len(kem_ciphertext) != ML_KEM_CIPHERTEXT_BYTES:
        raise MessageCryptoError("malformed ML-KEM ciphertext length")
    try:
        shared_secret = ML_KEM_512.decaps(decapsulation_key, kem_ciphertext)
        cipher = AES.new(shared_secret, AES.MODE_GCM, nonce=nonce)
        cipher.update(AAD_KEM)
        return cipher.decrypt_and_verify(b64d(document["ct"], "ct"), tag)
    except ValueError as exc:
        raise MessageCryptoError("ciphertext authentication failed") from exc


def _check_encapsulation_key(encapsulation_key: bytes) -> bytes:
    if len(encapsulation_key) != ML_KEM_ENCAPSULATION_KEY_BYTES:
        raise MessageCryptoError(
            f"malformed ML-KEM public key length {len(encapsulation_key)}"
        )
    return encapsulation_key
