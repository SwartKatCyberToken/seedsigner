"""Repair public keys and envelopes that were damaged by copying.

Copying through chat, email, web forms, code, logs or a QR generator often
changes whitespace: line breaks become spaces or a typed \\n, lines get joined,
wrapped, or indented, and control or invisible characters appear. This module
undoes that for every input the message menu accepts, then hands a v1 envelope
to parse_document:

- v1 JSON envelopes (RSA, ML-DSA, ML-KEM, PGP): whitespace inside base64
  fields, raw line breaks inside strings, curly quotes.
- OpenPGP armor (public key or encrypted message): any line layout, missing
  or extra headers, missing blank line, wrong line length, mangled dashes.
  The CRC-24 checksum, when present, proves the repair is exact.
- RSA PEM ("BEGIN PUBLIC KEY" / "BEGIN RSA PUBLIC KEY") and "ssh-rsa" keys.
- Bare base64 of an ML-DSA-44 / ML-KEM-512 public key or of a binary PGP key.

Plaintext and the "msg" field are never altered, even when they contain
invisible characters: those bytes are signed. Cleaning a JSON envelope therefore
stops at its strings, apart from the base64 and name fields.
Anything that cannot be repaired raises MessageCryptoError with a reason.
"""

import base64
import binascii
import json
import re

from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP,
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    ENVELOPE_VERSION,
    OP_ENC_PGP,
    OP_PUB,
    OP_SIG_PGP,
    SIGNED_BEGIN,
    b64e,
    dumps,
    parse_document,
    require_armor,
    split_signed_block,
)
from seedsigner.message_crypto.errors import MessageCryptoError

WANT_PUB = "pub"
WANT_ENVELOPE = "envelope"
WANT_SIGNATURE = "signature"

_PGP_ALGS = (ALG_PGP_ENCRYPT, ALG_PGP_SIGN)
_RSA_ALGS = (ALG_RSA_ENCRYPT, ALG_RSA_SIGN)
# Raw public key sizes, for bare base64 keys.
_RAW_PUB_BYTES = {ALG_ML_DSA: 1312, ALG_ML_KEM: 800}
_RAW_PUB_FIELD = {ALG_ML_DSA: "pk", ALG_ML_KEM: "ek"}
# Base64url fields in v1 envelopes. Whitespace inside them is copy damage.
_B64_FIELDS = ("n", "pk", "ek", "ct", "sig", "nonce", "tag")

# Terminal colour codes, as in text copied from a log.
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Control and format characters, and others that print nothing: bidi marks, joiners,
# variation selectors, tag characters and blank letters. U+FFFD isn't here, because
# it means data was already lost, so that input should still be rejected.
_INVISIBLE_RE = re.compile(
    "[\x00-\x08\x0e-\x1f\x7f-\x84\x86-\x9f\xad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    "\u200b-\u200f\u202a-\u202e\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff9-\ufffb"
    "\U000e0000-\U000e0fff]"
)
_SPACE_RE = re.compile("[\xa0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_BREAK_RE = re.compile("\r\n?|[\x0b\x0c\x85\u2028\u2029]")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "“”„‟″«»"), '"')

_ARMOR_RE = re.compile(
    r"-*\s*BEGIN\s+PGP\s+([A-Z]+(?: [A-Z]+)*)\s*-+(.*?)-+\s*END\s+PGP\s+([A-Z]+(?: [A-Z]+)*)",
    re.DOTALL | re.IGNORECASE,
)
_PEM_RE = re.compile(
    r"-*\s*BEGIN\s+(RSA\s+)?PUBLIC\s+KEY\s*-+(.*?)-+\s*END\s+(RSA\s+)?PUBLIC\s+KEY\s*-*",
    re.DOTALL | re.IGNORECASE,
)
_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_B64_ANY_RE = re.compile(r"^[A-Za-z0-9+/_=-]+$")
_CRC_RE = re.compile(r"=([A-Za-z0-9+/]{4})$")
# A line break written out as \n, \r\n or \\n. Base64 never contains a backslash.
_TYPED_BREAK_RE = re.compile(r"\\+[nrt]")
_JSON_STRING_RE = re.compile(r'("(?:[^"\\]|\\.)*")', re.DOTALL)


def clean_text(text) -> str:
    """Drop what doesn't print, unify line breaks and odd spaces, strip.

    Only for key material and structure, never for text that gets signed.
    """
    if not isinstance(text, str):
        raise MessageCryptoError("input is not text")
    text = _INVISIBLE_RE.sub("", _ANSI_RE.sub("", text))
    return _BREAK_RE.sub("\n", _SPACE_RE.sub(" ", text)).strip()


def parse_input(text, want: str, alg: str | None = None) -> dict:
    """Return the checked v1 envelope for typed, pasted or scanned text.

    want is WANT_PUB, WANT_ENVELOPE or WANT_SIGNATURE. alg is the algorithm
    chosen in the flow; foreign key formats need it to build a pub envelope.
    """
    original = text
    text = _unwrap_string(clean_text(text))
    if text == "":
        raise MessageCryptoError("input is empty")
    if text.startswith("{") or text.translate(_QUOTES).startswith('{"'):
        return _json_document(original, text)
    if SIGNED_BEGIN in original:
        return _signed_document(original, want)
    if re.search(r"BEGIN\s+PGP", text, re.IGNORECASE):
        return _armor_document(text, want, alg)
    if _PEM_RE.search(text.translate(_DASHES)) or text.startswith("ssh-rsa "):
        return _rsa_document(text, want, alg)
    if want == WANT_PUB:
        document = _bare_base64_document(text, alg)
        if document is not None:
            return document
    raise MessageCryptoError(_unknown_input_message(want))


def _unescape(text: str) -> str | None:
    """Undo one level of string escaping, or None if text isn't validly escaped."""
    try:
        return json.loads('"' + text + '"', strict=False)
    except ValueError:
        return None


def _unwrap_string(text: str) -> str:
    """Undo a string literal copied from code or a log, such as "-----BEGIN...\\n..."."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        inner = text[1:-1]
        return (_unescape(inner) or inner).strip()
    return text


def split_base64(text: str) -> list:
    """Split text on whitespace and on line breaks written out as \\n."""
    return _TYPED_BREAK_RE.sub(" ", text).split()


def normalize_armor(text: str) -> str:
    """Rebuild an OpenPGP armor block from any line layout.

    Headers (Version:, Comment:) are dropped; they carry no key data. The
    CRC-24 checksum is checked when present and added when missing.
    """
    if SIGNED_BEGIN in text:
        return _signed_block(text)
    cleaned = clean_text(text).translate(_DASHES)
    match = _ARMOR_RE.search(cleaned)
    if match is None:
        raise MessageCryptoError("PGP block has no BEGIN/END lines")
    kind = " ".join(match.group(1).upper().split())
    if kind != " ".join(match.group(3).upper().split()):
        raise MessageCryptoError("PGP block BEGIN and END lines do not match")
    data = _armor_body(split_base64(match.group(2)))
    body = base64.b64encode(data).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    crc = base64.b64encode(_crc24(data).to_bytes(3, "big")).decode("ascii")
    return (
        f"-----BEGIN PGP {kind}-----\n\n"
        + "\n".join(lines)
        + f"\n={crc}\n-----END PGP {kind}-----\n"
    )


def _armor_body(tokens: list) -> bytes:
    """Find the base64 body among the tokens after BEGIN, skipping headers.

    Tries each start token in turn and accepts the first candidate that
    decodes to a well-formed OpenPGP packet sequence and, when a checksum is
    present, matches it.
    """
    crc_mismatch = False
    for start in range(len(tokens)):
        candidate = "".join(tokens[start:])
        crc_match = _CRC_RE.search(candidate)
        encoded = candidate[:crc_match.start()] if crc_match else candidate
        data = _b64decode(encoded)
        if data is None or not _packets_ok(data):
            continue
        if crc_match:
            expected = _b64decode(crc_match.group(1))
            if expected is None or int.from_bytes(expected, "big") != _crc24(data):
                crc_mismatch = True
                continue
        return data
    if crc_mismatch:
        raise MessageCryptoError("PGP block is damaged: checksum does not match")
    raise MessageCryptoError("PGP block is damaged or incomplete")


def _signed_block(text: str) -> str:
    """Rebuild a cleartext signature, repairing only its signature part."""
    headers, message, signature = split_signed_block(text)
    escaped = re.sub(r"^-", "- -", message, flags=re.MULTILINE)
    return f"{SIGNED_BEGIN}\n{headers}\n{escaped}\n{normalize_armor(signature)}"


def _signed_document(text: str, want: str) -> dict:
    if want != WANT_SIGNATURE:
        raise MessageCryptoError(_unknown_input_message(want))
    return parse_document(dumps({
        "v": ENVELOPE_VERSION,
        "op": OP_SIG_PGP,
        "alg": ALG_PGP_SIGN,
        "msg": split_signed_block(text)[1],
        "armor": _signed_block(text),
    }))


def _armor_document(text: str, want: str, alg: str | None) -> dict:
    armor = require_armor(normalize_armor(text))
    if want == WANT_PUB:
        if "BEGIN PGP PUBLIC KEY BLOCK" not in armor:
            raise MessageCryptoError("expected a PGP PUBLIC KEY BLOCK")
        if alg not in _PGP_ALGS:
            raise MessageCryptoError("this is a PGP key; choose PGP as the algorithm")
        document = {"v": ENVELOPE_VERSION, "op": OP_PUB, "alg": alg, "armor": armor}
    elif want == WANT_ENVELOPE:
        if "BEGIN PGP MESSAGE" not in armor:
            raise MessageCryptoError("expected a PGP MESSAGE block")
        document = {"v": ENVELOPE_VERSION, "op": OP_ENC_PGP, "alg": ALG_PGP, "armor": armor}
    else:
        raise MessageCryptoError("a PGP signature needs its message: use the whole signed block")
    return parse_document(dumps(document))


def _clean_outside_strings(text: str) -> str:
    """Clean JSON structure and leave every string as it is, so "msg" stays exact."""
    pieces = _JSON_STRING_RE.split(text)
    pieces[::2] = [clean_text(piece) for piece in pieces[::2]]
    return "".join(pieces)


def _json_document(original: str, cleaned: str) -> dict:
    candidates = (
        _clean_outside_strings(original),
        cleaned,
        cleaned.translate(_QUOTES),
        # The whole document was escaped, as in {\"v\":1,...}.
        _unescape(cleaned) or "",
    )
    # The first is the only one that keeps "msg" exact. If a later one is needed
    # and that changes the text, the signature check fails rather than passes.
    document = next(filter(lambda found: isinstance(found, dict), map(_loads, candidates)), None)
    if document is None:
        raise MessageCryptoError("envelope is not valid JSON")
    document = {clean_text(name): value for name, value in document.items()}
    for field in _B64_FIELDS:
        if isinstance(document.get(field), str):
            document[field] = "".join(split_base64(clean_text(document[field])))
    if isinstance(document.get("e"), str) and clean_text(document["e"]).isdigit():
        document["e"] = int(clean_text(document["e"]))
    if isinstance(document.get("armor"), str):
        document["armor"] = normalize_armor(document["armor"])
    for field in ("op", "alg"):
        if isinstance(document.get(field), str):
            document[field] = clean_text(document[field])
    return parse_document(dumps(document))


def _loads(text: str):
    try:
        # strict=False accepts raw line breaks inside strings.
        return json.loads(text, strict=False)
    except ValueError:
        return None


def _rsa_document(text: str, want: str, alg: str | None) -> dict:
    if want != WANT_PUB:
        raise MessageCryptoError(_unknown_input_message(want))
    if alg not in _RSA_ALGS:
        raise MessageCryptoError("this is an RSA key; choose RSA as the algorithm")
    from Crypto.PublicKey import RSA
    from seedsigner.message_crypto.rsa_ops import export_public, import_public

    text = text.translate(_DASHES)
    try:
        if text.startswith("ssh-rsa "):
            key = RSA.import_key(" ".join(split_base64(text)[:2]))
        else:
            match = _PEM_RE.search(text)
            data = _b64decode("".join(split_base64(match.group(2))))
            if data is None:
                raise ValueError("bad base64")
            key = RSA.import_key(data)
    except (ValueError, IndexError, TypeError) as exc:
        raise MessageCryptoError("RSA key is damaged or incomplete") from exc
    if key.has_private():
        raise MessageCryptoError("that is a private key; paste the public key")
    document = parse_document(dumps(export_public(key, alg)))
    import_public(document)  # size and exponent checks
    return document


def _bare_base64_document(text: str, alg: str | None):
    """A public key pasted as plain base64, without any wrapper."""
    compact = "".join(split_base64(text))
    if not _B64_ANY_RE.match(compact):
        return None
    data = _b64decode(compact) or _b64decode(compact, urlsafe=True)
    if data is None:
        return None
    if alg in _RAW_PUB_BYTES:
        if len(data) != _RAW_PUB_BYTES[alg]:
            return None
        document = {"v": ENVELOPE_VERSION, "op": OP_PUB, "alg": alg, _RAW_PUB_FIELD[alg]: b64e(data)}
        return parse_document(dumps(document))
    if alg in _PGP_ALGS and _packets_ok(data) and _packet_tag(data[0]) == 6:
        body = base64.b64encode(data).decode("ascii")
        return _armor_document(
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n" + body + "\n-----END PGP PUBLIC KEY BLOCK-----",
            WANT_PUB,
            alg,
        )
    return None


def _unknown_input_message(want: str) -> str:
    if want == WANT_PUB:
        return "not a public key: paste JSON, PGP armor, PEM or base64"
    if want == WANT_ENVELOPE:
        return "not an encrypted message: paste JSON or a PGP MESSAGE"
    return "not a signature: paste the signed PGP block or the device's JSON"


def _b64decode(text: str, urlsafe: bool = False):
    if urlsafe:
        text = text.replace("-", "+").replace("_", "/")
    text = text.rstrip("=")
    text += "=" * (-len(text) % 4)
    if not text or not _B64_RE.match(text):
        return None
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None


def _crc24(data: bytes) -> int:
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _packet_tag(header: int) -> int:
    return header & 0x3F if header & 0x40 else (header >> 2) & 0x0F


def _packets_ok(data: bytes) -> bool:
    """True when data is a chain of OpenPGP packets that ends exactly."""
    if not data:
        return False
    i = 0
    size = len(data)
    while i < size:
        header = data[i]
        if not header & 0x80:
            return False
        i += 1
        if header & 0x40:  # new format length
            if i >= size:
                return False
            first = data[i]
            if first < 192:
                length, i = first, i + 1
            elif first < 224:
                if i + 1 >= size:
                    return False
                length, i = ((first - 192) << 8) + data[i + 1] + 192, i + 2
            elif first == 255:
                if i + 4 >= size:
                    return False
                length, i = int.from_bytes(data[i + 1:i + 5], "big"), i + 5
            else:
                return True  # partial body length: only in message data, accept
        else:  # old format length
            length_type = header & 0x03
            if length_type == 3:
                return True  # indeterminate length runs to the end
            width = 1 << length_type
            if i + width > size:
                return False
            length, i = int.from_bytes(data[i:i + width], "big"), i + width
        i += length
    return i == size
