"""Version-1 JSON envelopes for message keys, ciphertext, and signatures.

Does not derive keys or perform cryptography. operations.py builds these
documents and the QR layer carries the compact JSON. Field names and op
values are the v1 on-the-wire contract; parsers reject unknown ops and
unexpected fields rather than ignoring them.
"""

import base64
import json
import re

from seedsigner.message_crypto.errors import MessageCryptoError

ENVELOPE_VERSION = 1
# Bounds a QR payload and a decrypted message for this prototype.
MAX_MESSAGE_CHARS = 2000
MAX_FIELD_BYTES = 8000
MAX_ARMOR_CHARS = 16000

SIGNED_BEGIN = "-----BEGIN PGP SIGNED MESSAGE-----"
# Dash-escaping means only the real boundary can start a line with these dashes.
_SIGNED_RE = re.compile(
    re.escape(SIGNED_BEGIN) + r"[ \t]*\n((?:[^\n]+\n)*)[ \t]*\n(.*?)\n"
    r"(^-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----)",
    re.DOTALL | re.MULTILINE,
)

OP_TEXT = "text"
OP_PUB = "pub"
OP_ENC_RSA = "enc-rsa"
OP_ENC_KEM = "enc-kem"
OP_ENC_PGP = "enc-pgp"
OP_SIG_RSA = "sig-rsa"
OP_SIG_DSA = "sig-dsa"
OP_SIG_PGP = "sig-pgp"

ALG_RSA_SIGN = "rsa-sign"
ALG_RSA_ENCRYPT = "rsa-encrypt"
ALG_ML_DSA = "ml-dsa-44"
ALG_ML_KEM = "ml-kem-512"
ALG_PGP = "pgp-rsa"
ALG_PGP_ENCRYPT = "pgp-rsa-encrypt"
ALG_PGP_SIGN = "pgp-rsa-sign"
ALG_RSA_HYBRID = "rsa-oaep-sha256+aes-256-gcm"
ALG_KEM_HYBRID = "ml-kem-512+aes-256-gcm"

AAD_RSA = b"seedsigner-msg/1 enc-rsa"
AAD_KEM = b"seedsigner-msg/1 enc-kem"
# Bound into ML-DSA Sign/Verify so these signatures are not reusable elsewhere.
ML_DSA_CONTEXT = b"seedsigner-msg/1"

_FIELDS = {
    OP_TEXT: {"v", "op", "msg"},
    OP_PUB: {"v", "op", "alg", "n", "e", "pk", "ek"},
    OP_ENC_RSA: {"v", "op", "alg", "ek", "nonce", "ct", "tag"},
    OP_ENC_KEM: {"v", "op", "alg", "ek", "nonce", "ct", "tag"},
    OP_ENC_PGP: {"v", "op", "alg", "armor"},
    OP_SIG_RSA: {"v", "op", "alg", "msg", "sig"},
    OP_SIG_DSA: {"v", "op", "alg", "msg", "sig"},
    OP_SIG_PGP: {"v", "op", "alg", "msg", "armor"},
}
_PUB_ALG_FIELDS = {
    ALG_RSA_SIGN: {"v", "op", "alg", "n", "e"},
    ALG_RSA_ENCRYPT: {"v", "op", "alg", "n", "e"},
    ALG_ML_DSA: {"v", "op", "alg", "pk"},
    ALG_ML_KEM: {"v", "op", "alg", "ek"},
    ALG_PGP_ENCRYPT: {"v", "op", "alg", "armor"},
    ALG_PGP_SIGN: {"v", "op", "alg", "armor"},
}


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text: str, field_name: str) -> bytes:
    if not isinstance(text, str) or text == "":
        raise MessageCryptoError(f"{field_name} is missing")
    pad = "=" * ((4 - len(text) % 4) % 4)
    try:
        data = base64.urlsafe_b64decode(text + pad)
    except Exception as exc:
        raise MessageCryptoError(f"{field_name} is not base64url") from exc
    if len(data) > MAX_FIELD_BYTES:
        raise MessageCryptoError(f"{field_name} exceeds {MAX_FIELD_BYTES} bytes")
    return data


def dumps(document: dict) -> str:
    """Compact JSON with sorted keys so the same document encodes once."""
    return json.dumps(document, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def parse_document(payload: str) -> dict:
    """Parse and check a v1 envelope. Returns the JSON object."""
    if not isinstance(payload, str) or payload.strip() == "":
        raise MessageCryptoError("envelope is empty")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MessageCryptoError("envelope is not JSON") from exc
    if not isinstance(document, dict):
        raise MessageCryptoError("envelope must be a JSON object")
    _check_common(document)
    return document


def require_message(text: str) -> str:
    """Return text when it is a non-empty message inside the v1 size cap."""
    if not isinstance(text, str) or text == "":
        raise MessageCryptoError("message is empty")
    if len(text) > MAX_MESSAGE_CHARS:
        raise MessageCryptoError(f"message exceeds {MAX_MESSAGE_CHARS} characters")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MessageCryptoError("message is not valid UTF-8 text") from exc
    return text


def _check_common(document: dict) -> None:
    op = document.get("op")
    if op not in _FIELDS:
        raise MessageCryptoError("envelope op is not a v1 operation")
    if document.get("v") != ENVELOPE_VERSION:
        raise MessageCryptoError("envelope version is not 1")
    allowed = _pub_fields(document) if op == OP_PUB else _FIELDS[op]
    unknown = set(document.keys()) - allowed
    if unknown:
        raise MessageCryptoError("envelope contains an unexpected field")
    missing = allowed - set(document.keys())
    if missing:
        raise MessageCryptoError("envelope is missing a required field")
    _check_op(document)


def _pub_fields(document: dict) -> set:
    alg = document.get("alg")
    if alg not in _PUB_ALG_FIELDS:
        raise MessageCryptoError("public key alg is not a v1 algorithm")
    return _PUB_ALG_FIELDS[alg]


def _check_op(document: dict) -> None:
    op = document["op"]
    if op == OP_TEXT:
        require_message(document["msg"])
    elif op == OP_ENC_RSA and document["alg"] != ALG_RSA_HYBRID:
        raise MessageCryptoError("enc-rsa alg does not match v1")
    elif op == OP_ENC_KEM and document["alg"] != ALG_KEM_HYBRID:
        raise MessageCryptoError("enc-kem alg does not match v1")
    elif op == OP_SIG_RSA:
        require_message(document["msg"])
        if document["alg"] != ALG_RSA_SIGN:
            raise MessageCryptoError("sig-rsa alg does not match v1")
    elif op == OP_SIG_DSA:
        require_message(document["msg"])
        if document["alg"] != ALG_ML_DSA:
            raise MessageCryptoError("sig-dsa alg does not match v1")
    elif op == OP_ENC_PGP:
        if document["alg"] != ALG_PGP:
            raise MessageCryptoError("enc-pgp alg does not match v1")
        require_armor(document["armor"])
    elif op == OP_SIG_PGP:
        require_message(document["msg"])
        if document["alg"] != ALG_PGP_SIGN:
            raise MessageCryptoError("sig-pgp alg does not match v1")
        require_armor(document["armor"])
    elif op == OP_PUB and document["alg"] in (ALG_PGP_ENCRYPT, ALG_PGP_SIGN):
        require_armor(document["armor"])


PGP_PUBLIC_ALGS = (ALG_PGP_ENCRYPT, ALG_PGP_SIGN)


def same_key_type(alg: str, wanted: str) -> bool:
    """True when a public key tagged alg can be used where wanted is asked for.

    A PGP public key is one block that both encrypts and signs, so the two PGP
    tags only record which step it was entered for.
    """
    return alg == wanted or (alg in PGP_PUBLIC_ALGS and wanted in PGP_PUBLIC_ALGS)


def split_signed_block(text: str) -> tuple:
    """Return the headers, signed text and signature armor of a cleartext block.

    The text stays exact, so damage to it makes the signature check fail.
    Line break style isn't covered by the signature.
    """
    match = _SIGNED_RE.search(text.replace("\r\n", "\n"))
    if match is None:
        raise MessageCryptoError("PGP signed message is damaged")
    headers, escaped, signature = match.groups()
    return headers, re.sub(r"^- ", "", escaped, flags=re.MULTILINE), signature


def require_armor(armor: str) -> str:
    """Return armor when it is an OpenPGP block inside the v1 size cap."""
    if not isinstance(armor, str) or "-----BEGIN PGP" not in armor:
        raise MessageCryptoError("armor is not an OpenPGP block")
    if len(armor) > MAX_ARMOR_CHARS:
        raise MessageCryptoError(f"armor exceeds {MAX_ARMOR_CHARS} characters")
    return armor
