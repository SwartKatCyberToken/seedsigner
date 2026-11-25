"""Encrypt, decrypt, sign, verify, and export for one loaded seed.

Does not navigate or draw. Message views pass a seed's MessageKeys plus the
peer's public-key envelope. RSA signing and RSA encryption keys are separate.
ML-DSA signatures are over the UTF-8 bytes of the envelope msg field, with no
Unicode normalization.
"""

from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    OP_ENC_KEM,
    OP_ENC_PGP,
    OP_ENC_RSA,
    OP_SIG_DSA,
    OP_SIG_PGP,
    OP_SIG_RSA,
    b64d,
    require_message,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.keys import MessageKeys
from seedsigner.message_crypto.ml_dsa_ops import export_public as export_dsa_public
from seedsigner.message_crypto.ml_dsa_ops import import_public as import_dsa_public
from seedsigner.message_crypto.ml_dsa_ops import sign as dsa_sign
from seedsigner.message_crypto.ml_dsa_ops import verify as dsa_verify
from seedsigner.message_crypto.ml_kem_ops import decapsulate
from seedsigner.message_crypto.ml_kem_ops import encapsulate
from seedsigner.message_crypto.ml_kem_ops import export_public as export_kem_public
from seedsigner.message_crypto.ml_kem_ops import import_public as import_kem_public
from seedsigner.message_crypto.pgp_ops import decrypt as pgp_decrypt
from seedsigner.message_crypto.pgp_ops import encrypt as pgp_encrypt
from seedsigner.message_crypto.pgp_ops import export_public as export_pgp_public
from seedsigner.message_crypto.pgp_ops import sign as pgp_sign
from seedsigner.message_crypto.pgp_ops import verify as pgp_verify
from seedsigner.message_crypto.rsa_ops import decrypt as rsa_decrypt
from seedsigner.message_crypto.rsa_ops import encrypt as rsa_encrypt
from seedsigner.message_crypto.rsa_ops import export_public as export_rsa_public
from seedsigner.message_crypto.rsa_ops import import_public as import_rsa_public
from seedsigner.message_crypto.rsa_ops import sign as rsa_sign
from seedsigner.message_crypto.rsa_ops import verify as rsa_verify


def export_public(keys: MessageKeys, alg: str) -> dict:
    if alg == ALG_RSA_SIGN:
        return export_rsa_public(keys.rsa_signing_key(), ALG_RSA_SIGN)
    if alg == ALG_RSA_ENCRYPT:
        return export_rsa_public(keys.rsa_encryption_key(), ALG_RSA_ENCRYPT)
    if alg == ALG_ML_DSA:
        public_key, _secret = keys.ml_dsa_keys()
        return export_dsa_public(public_key)
    if alg == ALG_ML_KEM:
        encapsulation_key, _secret = keys.ml_kem_keys()
        return export_kem_public(encapsulation_key)
    if alg in (ALG_PGP_ENCRYPT, ALG_PGP_SIGN):
        return export_pgp_public(keys.rsa_signing_key(), keys.rsa_encryption_key(), alg)
    raise MessageCryptoError(f"cannot export public key for {alg}")


def encrypt_for(keys: MessageKeys, alg: str, peer: dict, message: str) -> dict:
    plaintext = require_message(message).encode("utf-8")
    if alg == ALG_RSA_ENCRYPT:
        if peer.get("alg") != ALG_RSA_ENCRYPT:
            raise MessageCryptoError("recipient key must be an RSA encryption public key")
        return rsa_encrypt(import_rsa_public(peer), plaintext)
    if alg == ALG_ML_KEM:
        if peer.get("alg") != ALG_ML_KEM:
            raise MessageCryptoError("recipient key must be an ML-KEM-512 public key")
        return encapsulate(import_kem_public(peer), plaintext)
    if alg == ALG_PGP_ENCRYPT:
        return pgp_encrypt(peer, plaintext)
    raise MessageCryptoError(f"cannot encrypt with {alg}")


def decrypt_with(keys: MessageKeys, envelope: dict) -> str:
    op = envelope.get("op")
    if op == OP_ENC_RSA:
        plaintext = rsa_decrypt(keys.rsa_encryption_key(), envelope)
    elif op == OP_ENC_KEM:
        _encapsulation, decapsulation_key = keys.ml_kem_keys()
        plaintext = decapsulate(decapsulation_key, envelope)
    elif op == OP_ENC_PGP:
        plaintext = pgp_decrypt(keys.rsa_encryption_key(), envelope)
    else:
        raise MessageCryptoError("ciphertext op is not enc-rsa, enc-kem, or enc-pgp")
    try:
        text = plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MessageCryptoError("decrypted bytes are not UTF-8") from exc
    return require_message(text)


def sign_with(keys: MessageKeys, alg: str, message: str) -> dict:
    raw = require_message(message).encode("utf-8")
    if alg == ALG_RSA_SIGN:
        document = rsa_sign(keys.rsa_signing_key(), raw)
    elif alg == ALG_ML_DSA:
        _public, secret = keys.ml_dsa_keys()
        document = dsa_sign(secret, raw)
    elif alg == ALG_PGP_SIGN:
        document = pgp_sign(keys.rsa_signing_key(), raw)
    else:
        raise MessageCryptoError(f"cannot sign with {alg}")
    return document


def verify_with(peer: dict, envelope: dict) -> bool:
    """Return whether the signature matches peer. Malformed input raises."""
    message = require_message(envelope.get("msg"))
    raw = message.encode("utf-8")
    op = envelope.get("op")
    if op == OP_SIG_RSA:
        if peer.get("alg") != ALG_RSA_SIGN:
            raise MessageCryptoError("verification key must be an RSA signing public key")
        signature = b64d(envelope["sig"], "sig")
        return rsa_verify(import_rsa_public(peer), raw, signature)
    if op == OP_SIG_DSA:
        if peer.get("alg") != ALG_ML_DSA:
            raise MessageCryptoError("verification key must be an ML-DSA-44 public key")
        signature = b64d(envelope["sig"], "sig")
        return dsa_verify(import_dsa_public(peer), raw, signature)
    if op == OP_SIG_PGP:
        return pgp_verify(peer, raw, envelope.get("armor"))
    raise MessageCryptoError("signature op is not sig-rsa, sig-dsa, or sig-pgp")
