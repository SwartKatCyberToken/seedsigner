"""OpenPGP encrypt, decrypt, sign, and verify with the seed RSA keys.

Does not generate a new RSA modulus. The key bytes come from rsa_ops, which
derives them from the BIP-39 seed. PGPy 0.6.0 can hold those parameters.
It is the last PGPy release and it imports imghdr, removed in Python 3.13,
so this module installs a stub before the import when imghdr is missing.

pysequoia is newer and can generate hybrid ML-DSA and ML-KEM certificates,
but it has no way to take an existing modulus or the ML-DSA-44 and
ML-KEM-512 seeds this project already derives. Those two stay on the custom
envelopes. PGP here is RSA only, and the exported public key is one block, as
other PGP apps make: the signing seed key is the primary key, and the
encryption seed key is its subkey. Decrypting and signing still use each key on
its own, so the private side never needs both. A subkey's fingerprint covers
only the key and its date, so a message to the subkey is a message to the
encryption key.

The key creation time is fixed so the same seed exports the same armor.

Signatures are cleartext blocks (BEGIN PGP SIGNED MESSAGE), the only form SHAP
and its OpenPGP.js can verify.
"""

import importlib.machinery
import re
import sys
import types
import warnings
from datetime import datetime, timezone

from seedsigner.message_crypto.codec import (
    ALG_PGP,
    ALG_PGP_SIGN,
    ENVELOPE_VERSION,
    OP_ENC_PGP,
    OP_PUB,
    OP_SIG_PGP,
    PGP_PUBLIC_ALGS,
    SIGNED_BEGIN,
    require_armor,
    require_message,
    split_signed_block,
)
from seedsigner.message_crypto.errors import MessageCryptoError

KEY_CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ENCRYPT = "encrypt"
_SIGN = "sign"
_USER_ID = "seedsigner-msg/1 (pgp-rsa)"
_LINE_END_SPACE_RE = re.compile(r"[ \t]+(?=\r?\n|\Z)")


def _import_pgpy():
    if "imghdr" not in sys.modules:
        try:
            import imghdr  # noqa: F401
        except ModuleNotFoundError:
            imghdr = types.ModuleType("imghdr")
            imghdr.what = lambda *args, **kwargs: None
            imghdr.__spec__ = importlib.machinery.ModuleSpec("imghdr", loader=None)
            sys.modules["imghdr"] = imghdr
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="pgpy")
    warnings.filterwarnings("ignore", category=UserWarning, module="pgpy")
    import pgpy
    from pgpy.constants import (
        CompressionAlgorithm,
        HashAlgorithm,
        KeyFlags,
        PubKeyAlgorithm,
        SymmetricKeyAlgorithm,
    )
    from pgpy.packet.fields import MPI
    from pgpy.packet.packets import PrivKeyV4
    return pgpy, MPI, PrivKeyV4, PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm


def export_public(signing_key, encryption_key, alg: str) -> dict:
    """The one public key block. alg records which step it's for."""
    if alg not in PGP_PUBLIC_ALGS:
        raise MessageCryptoError("PGP export alg is not pgp-rsa-encrypt or pgp-rsa-sign")
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_PUB,
        "alg": alg,
        "armor": str(certificate(signing_key, encryption_key).pubkey),
    }


def private_armor(signing_key, encryption_key) -> str:
    """Armored secret key for the test helper. The device does not display this."""
    return str(certificate(signing_key, encryption_key))


def encrypt(peer: dict, plaintext: bytes) -> dict:
    if peer.get("alg") not in PGP_PUBLIC_ALGS:
        raise MessageCryptoError("recipient key must be a PGP public key")
    pgpy, *_rest = _import_pgpy()
    recipient = _public_from_armor(pgpy, peer.get("armor"))
    message = pgpy.PGPMessage.new(plaintext.decode("utf-8"))
    try:
        encrypted = recipient.encrypt(message)
    except Exception as exc:
        raise MessageCryptoError("This PGP key can't encrypt. It may be a signing-only key.") from exc
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_ENC_PGP,
        "alg": ALG_PGP,
        "armor": str(encrypted),
    }


def decrypt(rsa_key, document: dict) -> bytes:
    if document.get("op") != OP_ENC_PGP:
        raise MessageCryptoError("ciphertext is not enc-pgp")
    pgpy, *_rest = _import_pgpy()
    private = key_from_rsa(rsa_key, _ENCRYPT)
    try:
        clear = private.decrypt(pgpy.PGPMessage.from_blob(require_armor(document.get("armor"))))
    except Exception as exc:
        raise MessageCryptoError("PGP decryption failed") from exc
    message = clear.message
    if isinstance(message, bytes):
        return message
    if isinstance(message, str):
        return message.encode("utf-8")
    raise MessageCryptoError("PGP decryption did not return text")


def sign(rsa_key, message: bytes) -> dict:
    pgpy, _mpi, _pkt, _pkalg, _flags, HashAlgorithm, *_rest = _import_pgpy()
    private = key_from_rsa(rsa_key, _SIGN)
    text = require_message(_signed_text(message.decode("utf-8")))
    block = pgpy.PGPMessage.new(text, cleartext=True)
    block |= private.sign(block, hash=HashAlgorithm.SHA256, created=_signature_time())
    return {
        "v": ENVELOPE_VERSION,
        "op": OP_SIG_PGP,
        "alg": ALG_PGP_SIGN,
        "msg": text,
        "armor": str(block),
    }


def verify(peer: dict, message: bytes, armor: str) -> bool:
    if peer.get("alg") not in PGP_PUBLIC_ALGS:
        raise MessageCryptoError("verification key must be a PGP public key")
    pgpy, *_rest = _import_pgpy()
    public = _public_from_armor(pgpy, peer.get("armor"))
    text = message.decode("utf-8")
    armor = require_armor(armor)
    try:
        if SIGNED_BEGIN not in armor:
            # Envelopes from before signatures became cleartext blocks.
            return bool(public.verify(text, pgpy.PGPSignature.from_blob(armor)))
        _headers, block_text, signature_armor = split_signed_block(armor)
        signed = _signed_text(block_text)
        if signed != _signed_text(text):
            return False
        # PGPy's parser loses non-ASCII text and the signatures after it, so it never sees the text.
        stand_in = pgpy.PGPMessage.from_blob(f"{SIGNED_BEGIN}\n\n-\n{signature_armor}")
        signers = {public.fingerprint.keyid} | set(public.subkeys)
        return any(
            public.verify(signed, signature)
            for signature in stand_in.signatures
            if signature.signer in signers
        )
    except Exception as exc:
        raise MessageCryptoError("PGP verification failed") from exc


def _signed_text(text: str) -> str:
    """The text a cleartext signature covers: no spaces or tabs at line ends."""
    return _LINE_END_SPACE_RE.sub("", text).replace("\r\n", "\n")


def _signature_time() -> datetime:
    """Now, but never before the key existed, which verifiers reject.

    The Pi has no battery clock, so without a network it boots near 1970.
    """
    return max(datetime.now(timezone.utc), KEY_CREATED)


def certificate(signing_key, encryption_key):
    """One unprotected PGPy key: the signing key, with the encryption key as its subkey.

    Every date is KEY_CREATED, so the same seed always exports the same block,
    and a Pi with no clock can't date the subkey binding before the key.
    """
    pgpy, _mpi, PrivKeyV4, _pkalg, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm = _import_pgpy()
    from pgpy.packet.packets import PrivSubKeyV4

    primary = pgpy.PGPKey()
    primary._key = _key_packet(signing_key, PrivKeyV4)
    primary.add_uid(
        pgpy.PGPUID.new(_USER_ID),
        usage={KeyFlags.Certify, KeyFlags.Sign},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB, CompressionAlgorithm.ZIP, CompressionAlgorithm.Uncompressed],
        created=KEY_CREATED,
    )
    subkey = pgpy.PGPKey()
    subkey._key = _key_packet(encryption_key, PrivSubKeyV4)
    primary.add_subkey(
        subkey,
        usage={KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        created=KEY_CREATED,
        crosssign=False,
    )
    return primary


def key_from_rsa(rsa_key, purpose: str):
    """Wrap one PyCryptodome RSA key as an unprotected PGPy key, for signing or decrypting."""
    if purpose not in (_ENCRYPT, _SIGN):
        raise MessageCryptoError("PGP key purpose is not encrypt or sign")
    pgpy, MPI, PrivKeyV4, PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm = _import_pgpy()

    key = pgpy.PGPKey()
    key._key = _key_packet(rsa_key, PrivKeyV4)
    if purpose == _ENCRYPT:
        usage = {KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage}
        label = "seedsigner-msg/1 (pgp-rsa-encrypt)"
    else:
        usage = {KeyFlags.Sign}
        label = "seedsigner-msg/1 (pgp-rsa-sign)"
    key.add_uid(
        pgpy.PGPUID.new(label),
        usage=usage,
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB, CompressionAlgorithm.ZIP, CompressionAlgorithm.Uncompressed],
        created=KEY_CREATED,
    )
    return key


def _key_packet(rsa_key, packet_class):
    """A PGP secret key packet holding a PyCryptodome RSA key, dated KEY_CREATED."""
    _pgpy, MPI, _pk, PubKeyAlgorithm, *_rest = _import_pgpy()
    from cryptography.hazmat.primitives.asymmetric import rsa as crypto_rsa

    packet = packet_class()
    packet.pkalg = PubKeyAlgorithm.RSAEncryptOrSign
    packet.created = KEY_CREATED
    material = packet.keymaterial
    material.n = MPI(rsa_key.n)
    material.e = MPI(rsa_key.e)
    material.d = MPI(rsa_key.d)
    material.p = MPI(rsa_key.p)
    material.q = MPI(rsa_key.q)
    # PGPy stores p^-1 mod q. rsa_crt_iqmp(p, q) is q^-1 mod p, so the arguments are swapped.
    material.u = MPI(int(crypto_rsa.rsa_crt_iqmp(rsa_key.q, rsa_key.p)))
    material._compute_chksum()
    packet.update_hlen()
    return packet


def primary_fingerprint(armor: str) -> str:
    """The primary key's OpenPGP v4 fingerprint: 40 upper-case hex digits, as gpg shows it."""
    pgpy, *_rest = _import_pgpy()
    return str(_public_from_armor(pgpy, armor).fingerprint).replace(" ", "").upper()


def _public_from_armor(pgpy, armor: str):
    try:
        key, _others = pgpy.PGPKey.from_blob(require_armor(armor))
    except MessageCryptoError:
        raise
    except Exception as exc:
        raise MessageCryptoError("PGP public key could not be read") from exc
    if not key.is_public:
        raise MessageCryptoError("PGP recipient must be a public key")
    return key

