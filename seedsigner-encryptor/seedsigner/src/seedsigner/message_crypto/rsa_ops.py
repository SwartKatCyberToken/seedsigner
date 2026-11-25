"""RSA key generation, PSS signatures, and OAEP+AES-GCM hybrid encryption.

Does not derive the BIP-39 stream key; callers pass that key into
generate_rsa. Signatures use a random PSS salt. Encryption nonces and AES
keys come from the operating-system RNG. Only RSA.generate uses the
deterministic stream. Device keys are 2048-bit; 1024 is accepted so the test
suite can run a faster generation.
"""

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Signature import pss

from seedsigner.message_crypto.codec import (
    AAD_RSA,
    ALG_RSA_ENCRYPT,
    ALG_RSA_HYBRID,
    ALG_RSA_SIGN,
    ENVELOPE_VERSION,
    OP_ENC_RSA,
    OP_PUB,
    OP_SIG_RSA,
    b64d,
    b64e,
)
from seedsigner.message_crypto.derivation import HmacSha256Counter
from seedsigner.message_crypto.errors import MessageCryptoError

RSA_BITS = 2048
RSA_PUBLIC_EXPONENT = 65537
RSA_ACCEPTED_BITS = (1024, 2048, 3072)
AES_KEY_BYTES = 32
GCM_NONCE_BYTES = 12
GCM_TAG_BYTES = 16


def generate_rsa(stream_key: bytes, bits: int = RSA_BITS):
    """Return an RSA key from a one-shot HMAC-SHA256 counter stream."""
    if bits not in RSA_ACCEPTED_BITS:
        raise MessageCryptoError(f"RSA bit length {bits} is not a v1 size")
    stream = HmacSha256Counter(stream_key)
    return RSA.generate(bits, randfunc=stream, e=RSA_PUBLIC_EXPONENT)


def export_public(key, alg: str) -> dict:
    if alg not in (ALG_RSA_SIGN, ALG_RSA_ENCRYPT):
        raise MessageCryptoError("RSA export alg is not rsa-sign or rsa-encrypt")
    width = (key.n.bit_length() + 7) // 8
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_PUB,
        "alg": alg,
        "n": b64e(key.n.to_bytes(width, "big")),
        "e": key.e,
    }


def import_public(document: dict):
    if document.get("alg") not in (ALG_RSA_SIGN, ALG_RSA_ENCRYPT):
        raise MessageCryptoError("RSA public key alg is not a v1 RSA algorithm")
    if document.get("e") != RSA_PUBLIC_EXPONENT:
        raise MessageCryptoError("RSA public exponent must be 65537")
    modulus = int.from_bytes(b64d(document["n"], "n"), "big")
    bits = modulus.bit_length()
    if bits not in RSA_ACCEPTED_BITS and bits + 1 not in RSA_ACCEPTED_BITS:
        raise MessageCryptoError(f"RSA modulus length {bits} is not a v1 size")
    return RSA.construct((modulus, RSA_PUBLIC_EXPONENT))


def sign(private_key, message: bytes) -> dict:
    digest = SHA256.new(message)
    signature = pss.new(private_key).sign(digest)
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_SIG_RSA,
        "alg": ALG_RSA_SIGN,
        "msg": message.decode("utf-8"),
        "sig": b64e(signature),
    }


def verify(public_key, message: bytes, signature: bytes) -> bool:
    width = (public_key.n.bit_length() + 7) // 8
    if len(signature) != width:
        raise MessageCryptoError(f"malformed RSA signature length {len(signature)}")
    digest = SHA256.new(message)
    try:
        pss.new(public_key).verify(digest, signature)
    except (ValueError, TypeError):
        return False
    return True


def encrypt(public_key, plaintext: bytes) -> dict:
    aes_key = get_random_bytes(AES_KEY_BYTES)
    nonce = get_random_bytes(GCM_NONCE_BYTES)
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
    cipher.update(AAD_RSA)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    wrapped = PKCS1_OAEP.new(public_key, hashAlgo=SHA256).encrypt(aes_key)
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_ENC_RSA,
        "alg": ALG_RSA_HYBRID,
        "ek": b64e(wrapped),
        "nonce": b64e(nonce),
        "ct": b64e(ciphertext),
        "tag": b64e(tag),
    }


def decrypt(private_key, document: dict) -> bytes:
    if document.get("op") != OP_ENC_RSA:
        raise MessageCryptoError("ciphertext is not enc-rsa")
    nonce = b64d(document["nonce"], "nonce")
    tag = b64d(document["tag"], "tag")
    if len(nonce) != GCM_NONCE_BYTES or len(tag) != GCM_TAG_BYTES:
        raise MessageCryptoError("enc-rsa nonce or tag has the wrong length")
    try:
        aes_key = PKCS1_OAEP.new(private_key, hashAlgo=SHA256).decrypt(
            b64d(document["ek"], "ek")
        )
        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        cipher.update(AAD_RSA)
        return cipher.decrypt_and_verify(b64d(document["ct"], "ct"), tag)
    except (ValueError, TypeError) as exc:
        raise MessageCryptoError("ciphertext authentication failed") from exc
