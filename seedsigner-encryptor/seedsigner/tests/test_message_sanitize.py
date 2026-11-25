"""Copy-damaged keys and envelopes are repaired, or rejected with a reason.

Each test takes a known-good input, damages it the way chat, email, web
forms or QR generators do, and checks that parse_input returns exactly the
envelope the undamaged input gives.
"""

import base64
import json
import os

import pytest

from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    b64e,
    dumps,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.flow import EXPECT_TEXT, accept_typed, new_flow
from seedsigner.message_crypto.sanitize import (
    WANT_ENVELOPE,
    WANT_PUB,
    WANT_SIGNATURE,
    normalize_armor,
    parse_input,
)

# OpenPGP.js Ed25519 + Curve25519 key (60-character lines, as exported).
PGP_KEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

xjMEaupCGBYJKwYBBAHaRw8BAQdAP+liXH3V0M05uR+v08W0YQ35NHhS9VrM
93v+e0ciXfjNG0pvbiBTbWl0aCA8am9uQGV4YW1wbGUuY29tPsKMBBAWCgA+
BYJq6kIYBAsJBwgJkEMFh6Qlj6zVAxUICgQWAAIBAhkBApsDAh4BFiEEWVtM
JKSgBs3WKeXAQwWHpCWPrNUAABH0AP0UCs+yyFCu+gKQMnihKiqKtWLsPF62
Oc4rQp0JpfeiIAD/cqLDvgNJcuDut8A7OlZhVBtwy8PElmp/Xp6ResBaSw3O
OARq6kIYEgorBgEEAZdVAQUBAQdA0KxDKV4obmg0SpQ/lIKRI+YzKnxXx3+8
ivI9OgCwF2YDAQgHwngEGBYKACoFgmrqQhgJkEMFh6Qlj6zVApsMFiEEWVtM
JKSgBs3WKeXAQwWHpCWPrNUAALVpAP4wStfUtjdjDUXsdFEhbR531QXKzLx0
SOofGtwagyAcmAEAy2hYINQa+MtiQK2xhkc76yKKyBLw+BDtQ7+EmkrhaQU=
=Uu+i
-----END PGP PUBLIC KEY BLOCK-----
"""
BEGIN = "-----BEGIN PGP PUBLIC KEY BLOCK-----"
END = "-----END PGP PUBLIC KEY BLOCK-----"
BODY_LINES = PGP_KEY.strip().split("\n")[2:-2]
CRC_LINE = PGP_KEY.strip().split("\n")[-2]
BODY = "".join(BODY_LINES)


def _rewrap(text: str, width: int) -> list:
    return [text[i:i + width] for i in range(0, len(text), width)]


PGP_DAMAGE = {
    "intact": PGP_KEY,
    "line breaks as spaces": " ".join(PGP_KEY.split("\n")),
    "one line, no separators": BEGIN + BODY + CRC_LINE + END,
    "windows line endings": PGP_KEY.replace("\n", "\r\n"),
    "old mac line endings": PGP_KEY.replace("\n", "\r"),
    "no blank line after BEGIN": PGP_KEY.replace(BEGIN + "\n\n", BEGIN + "\n"),
    "headers": PGP_KEY.replace(BEGIN + "\n", BEGIN + "\nVersion: OpenPGP.js v6.1.0\nComment: https://openpgpjs.org\n"),
    "headers, flattened": " ".join(
        PGP_KEY.replace(BEGIN + "\n", BEGIN + "\nVersion: OpenPGP.js v6.1.0\nComment: https://openpgpjs.org\n").split("\n")
    ),
    "rewrapped at 76": "\n".join([BEGIN, ""] + _rewrap(BODY, 76) + [CRC_LINE, END]),
    "rewrapped at 20": "\n".join([BEGIN, ""] + _rewrap(BODY, 20) + [CRC_LINE, END]),
    "indented and trailing spaces": "\n".join("    " + line + "  " for line in PGP_KEY.split("\n")),
    "blank lines between lines": "\n\n".join(PGP_KEY.split("\n")),
    "checksum on the last body line": "\n".join([BEGIN, ""] + BODY_LINES[:-1] + [BODY_LINES[-1] + CRC_LINE, END]),
    "no checksum": PGP_KEY.replace(CRC_LINE + "\n", ""),
    "en/em dashes in markers": PGP_KEY.replace("-----", "——-"),
    "lower-case markers": PGP_KEY.replace(BEGIN, BEGIN.lower()).replace(END, END.lower()),
    "BOM, zero-width and no-break spaces": "﻿" + PGP_KEY.replace("\n", "​\n ", 4),
    "surrounding text": "Here is my key:\n\n" + PGP_KEY + "\nThanks!",
    "four dashes, no gap": BEGIN[:-1] + BODY + CRC_LINE + END,
    "typed \\n": "\\n".join([BEGIN, *BODY_LINES, CRC_LINE, END]),
    "typed \\n and spaces": "\\n ".join([BEGIN, *BODY_LINES, CRC_LINE, END]),
    "typed \\r\\n": "\\r\\n".join([BEGIN, *BODY_LINES, CRC_LINE, END]),
    "typed \\\\n": "\\\\n".join([BEGIN, *BODY_LINES, CRC_LINE, END]),
    "typed \\n and real breaks": "\\n\n".join([BEGIN, *BODY_LINES, CRC_LINE, END]),
    "string literal from code": '"' + "\\n".join([BEGIN, *BODY_LINES, CRC_LINE, END]) + '"',
}


@pytest.mark.parametrize("damage", PGP_DAMAGE.keys())
def test_pgp_armor_is_repaired(damage):
    expected = normalize_armor(PGP_KEY)
    assert normalize_armor(PGP_DAMAGE[damage]) == expected
    document = parse_input(PGP_DAMAGE[damage], WANT_PUB, ALG_PGP_ENCRYPT)
    assert document["armor"] == expected


def test_repaired_armor_keeps_the_same_key_bytes():
    canonical = normalize_armor(PGP_KEY)
    lines = canonical.strip().split("\n")
    assert lines[0] == BEGIN and lines[1] == "" and lines[-1] == END
    assert lines[-2] == CRC_LINE
    assert all(len(line) <= 64 for line in lines[2:-2])
    assert base64.b64decode("".join(lines[2:-2])) == base64.b64decode(BODY)


def test_pgp_checksum_mismatch_is_reported():
    damaged = PGP_KEY.replace("P+liXH3V", "P+liXH4V")
    with pytest.raises(MessageCryptoError, match="checksum does not match"):
        parse_input(damaged, WANT_PUB, ALG_PGP_ENCRYPT)


def test_truncated_pgp_key_is_reported():
    truncated = "\n".join([BEGIN, ""] + BODY_LINES[:4] + [END])
    with pytest.raises(MessageCryptoError, match="damaged or incomplete"):
        parse_input(truncated, WANT_PUB, ALG_PGP_ENCRYPT)


def test_pgp_key_without_markers_is_accepted_as_base64():
    document = parse_input(" ".join(BODY_LINES), WANT_PUB, ALG_PGP_SIGN)
    assert document["armor"] == normalize_armor(PGP_KEY)


def test_pgp_key_needs_a_pgp_algorithm():
    with pytest.raises(MessageCryptoError, match="choose PGP"):
        parse_input(PGP_KEY, WANT_PUB, ALG_RSA_ENCRYPT)


def test_pgp_key_is_not_a_message_or_signature():
    with pytest.raises(MessageCryptoError, match="PGP MESSAGE"):
        parse_input(PGP_KEY, WANT_ENVELOPE)
    with pytest.raises(MessageCryptoError, match="whole signed block"):
        parse_input(PGP_KEY, WANT_SIGNATURE)


# JSON envelopes: RSA, ML-DSA and ML-KEM keys, and ciphertext.

def _rsa_key():
    from Crypto.PublicKey import RSA
    return RSA.generate(1024)


@pytest.fixture(scope="module")
def rsa_key():
    return _rsa_key()


@pytest.fixture(scope="module")
def rsa_document(rsa_key):
    from seedsigner.message_crypto.rsa_ops import export_public
    return export_public(rsa_key, ALG_RSA_ENCRYPT)


def _json_damage(document: dict) -> dict:
    compact = dumps(document)
    wrapped = dict(document)
    wrapped["n"] = "\n".join(_rewrap(document["n"], 50))
    spaced = dict(document)
    spaced["n"] = " ".join(_rewrap(document["n"], 8))
    return {
        "intact": compact,
        "pretty printed": json.dumps(document, indent=4),
        "line breaks inside base64": json.dumps(wrapped).replace("\\n", "\n"),
        "spaces inside base64": json.dumps(spaced),
        "curly quotes": compact.replace('"', "“"),
        "BOM and zero-width": "﻿" + compact.replace(",", ",​"),
        "exponent as a string": compact.replace('"e":65537', '"e":"65537"'),
        "windows line endings": json.dumps(document, indent=2).replace("\n", "\r\n"),
    }


@pytest.mark.parametrize(
    "damage",
    ["intact", "pretty printed", "line breaks inside base64", "spaces inside base64",
     "curly quotes", "BOM and zero-width", "exponent as a string", "windows line endings"],
)
def test_json_public_key_is_repaired(rsa_document, damage):
    assert parse_input(_json_damage(rsa_document)[damage], WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document


@pytest.mark.parametrize("alg,field,size", [(ALG_ML_DSA, "pk", 1312), (ALG_ML_KEM, "ek", 800)])
def test_post_quantum_keys_as_json_or_bare_base64(alg, field, size):
    raw = os.urandom(size)
    document = {"v": 1, "op": "pub", "alg": alg, field: b64e(raw)}
    wrapped_json = json.dumps(document, indent=2).replace(document[field], "\n".join(_rewrap(document[field], 64)))
    standard_b64 = "\n".join(_rewrap(base64.b64encode(raw).decode(), 76))
    for text in (dumps(document), wrapped_json, standard_b64, b64e(raw)):
        assert parse_input(text, WANT_PUB, alg) == document


def test_bare_base64_with_the_wrong_length_is_rejected():
    with pytest.raises(MessageCryptoError, match="not a public key"):
        parse_input(b64e(os.urandom(799)), WANT_PUB, ALG_ML_KEM)


def test_signed_message_text_is_never_changed():
    message = "  two  spaces,\na line break, “quotes” and ​ zero-width "
    envelope = {"v": 1, "op": "sig-rsa", "alg": "rsa-sign", "msg": message, "sig": b64e(b"x" * 128)}
    assert parse_input(json.dumps(envelope, indent=2), WANT_SIGNATURE)["msg"] == message


def test_plaintext_is_never_changed():
    flow = new_flow("encrypt")
    flow["expect"] = EXPECT_TEXT
    accept_typed(flow, "  hi​ there \n")
    assert flow["text"] == "  hi​ there \n"


def test_pretty_printed_ciphertext_is_repaired():
    envelope = {
        "v": 1, "op": "enc-kem", "alg": "ml-kem-512+aes-256-gcm",
        "ek": b64e(os.urandom(768)), "nonce": b64e(os.urandom(12)),
        "ct": b64e(os.urandom(40)), "tag": b64e(os.urandom(16)),
    }
    text = json.dumps(envelope, indent=2).replace(envelope["ek"], " ".join(_rewrap(envelope["ek"], 60)))
    assert parse_input(text, WANT_ENVELOPE) == envelope


# RSA keys from other tools: PEM and OpenSSH.

@pytest.mark.parametrize("fmt", ["SPKI", "PKCS1", "SPKI flattened", "SPKI one line", "OpenSSH"])
def test_rsa_pem_and_ssh_keys(rsa_key, rsa_document, fmt):
    public = rsa_key.public_key()
    if fmt.startswith("SPKI"):
        text = public.export_key("PEM").decode()
    elif fmt == "PKCS1":
        from Crypto.IO import PEM
        from Crypto.Util.asn1 import DerSequence
        text = PEM.encode(DerSequence([public.n, public.e]).encode(), "RSA PUBLIC KEY")
    else:
        text = public.export_key("OpenSSH").decode() + " user@host"
    if fmt == "SPKI flattened":
        text = " ".join(text.split("\n"))
    if fmt == "SPKI one line":
        text = text.replace("\n", "")
    assert parse_input(text, WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document
    signing = parse_input(text, WANT_PUB, ALG_RSA_SIGN)
    assert signing["alg"] == ALG_RSA_SIGN and signing["n"] == rsa_document["n"]


def test_rsa_private_key_is_refused(rsa_key):
    with pytest.raises(MessageCryptoError):
        parse_input(rsa_key.export_key("PEM").decode(), WANT_PUB, ALG_RSA_ENCRYPT)


def test_rsa_pem_needs_an_rsa_algorithm(rsa_key):
    with pytest.raises(MessageCryptoError, match="choose RSA"):
        parse_input(rsa_key.public_key().export_key("PEM").decode(), WANT_PUB, ALG_PGP_ENCRYPT)


# Characters that don't print, in every format.

NON_PRINTING = [
    "\x00", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x7f", "\x80", "\x85", "\x9b", "\xa0", "\xad", "\u034f",
    "\u061c", "\u180e", "\u2002", "\u2009", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2028", "\u2029",
    "\u202a", "\u202e", "\u202f", "\u205f", "\u2060", "\u2062", "\u2066", "\u2069", "\u2800", "\u3000", "\u3164",
    "\ufe0f", "\ufeff", "\ufff9", "\U000e0041", "\x1b[0m", "\x1b[1;31m", "\r\n",
]


def _sprinkle(text: str, char: str) -> str:
    """Put char at the start, at each line break, and every 40 characters inside lines."""
    lines = [char.join(_rewrap(line, 40)) if line else line for line in text.split("\n")]
    return char + ("\n" + char).join(lines) + char


@pytest.mark.parametrize("char", NON_PRINTING, ids=ascii)
def test_non_printing_characters_in_keys_are_removed(rsa_key, rsa_document, char):
    assert parse_input(_sprinkle(PGP_KEY, char), WANT_PUB, ALG_PGP_ENCRYPT)["armor"] == normalize_armor(PGP_KEY)
    pem = rsa_key.public_key().export_key("PEM").decode()
    assert parse_input(_sprinkle(pem, char), WANT_PUB, ALG_RSA_ENCRYPT)["n"] == rsa_document["n"]
    raw = os.urandom(800)
    assert parse_input(_sprinkle(base64.b64encode(raw).decode(), char), WANT_PUB, ALG_ML_KEM)["ek"] == b64e(raw)


@pytest.mark.parametrize("char", NON_PRINTING, ids=ascii)
def test_non_printing_characters_in_json_are_removed(rsa_document, char):
    n = rsa_document["n"]
    text = dumps(rsa_document).replace(",", "," + char).replace(n[:20], n[:10] + char + n[10:20])
    assert parse_input(char + text + char, WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document


def test_a_replacement_character_is_still_rejected():
    # U+FFFD means a byte was already lost, so this can't be repaired.
    with pytest.raises(MessageCryptoError, match="damaged"):
        parse_input(PGP_KEY.replace("P+liXH3V", "P+li\ufffdH3V"), WANT_PUB, ALG_PGP_ENCRYPT)


SIGNED_TEXTS = [
    "family \U0001F468\u200d\U0001F469\u200d\U0001F467",
    "price\xa010",
    "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645",
    "\ufeff  hi\x07  \u202e",
    "\u201chi\u201d a\u2014b",
]


@pytest.mark.parametrize("message", SIGNED_TEXTS, ids=ascii)
@pytest.mark.parametrize("damage", ["intact", "BOM in front", "invisible between tokens", "invisible in signature"])
def test_invisible_characters_in_signed_text_are_kept(message, damage):
    envelope = {"v": 1, "op": "sig-rsa", "alg": "rsa-sign", "msg": message, "sig": b64e(b"x" * 128)}
    text = dumps(envelope)
    text = {
        "intact": text,
        "BOM in front": "\ufeff" + text,
        "invisible between tokens": text.replace(',"sig"', ',\u200b"sig"'),
        "invisible in signature": text.replace(envelope["sig"], envelope["sig"][:8] + "\u200b" + envelope["sig"][8:]),
    }[damage]
    assert parse_input(text, WANT_SIGNATURE) == envelope


def test_a_signature_over_text_with_invisible_characters_verifies():
    from seedsigner.message_crypto import rsa_ops

    key = _rsa_key()
    message = "family \U0001F468\u200d\U0001F469"
    signed = rsa_ops.sign(key, message.encode("utf-8"))
    parsed = parse_input("\ufeff" + dumps(signed), WANT_SIGNATURE)
    assert parsed["msg"] == message
    assert rsa_ops.verify(key.public_key(), parsed["msg"].encode("utf-8"), base64.urlsafe_b64decode(parsed["sig"] + "=" * (-len(parsed["sig"]) % 4)))


SIGNATURE_ARMOR = """-----BEGIN PGP SIGNATURE-----

wnUEARYKACcFgmrtM9oJkJ9wibKGDi3EFiEEa8f4XEQjrqCIVHCun3CJsoYO
LcQAAHq1AQCzkG6PkI7qSG4XBPntLd9uhTwhfmfz5Q0NM+UT1mD8xQD/QHY2
VYF4BafKqDpN7ETIcoVc1YbM9YVRJCNI4WJQAAo=
=cz/W
-----END PGP SIGNATURE-----
"""


def test_a_cleartext_signed_block_keeps_its_message_exact():
    block = "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n﻿a‍b\xa0\n" + SIGNATURE_ARMOR
    assert "\n﻿a‍b\xa0\n-----BEGIN PGP SIGNATURE-----\n" in normalize_armor(block)
    assert parse_input(block, WANT_SIGNATURE)["msg"] == "﻿a‍b\xa0"


def test_a_cleartext_signed_block_with_no_signature_is_rejected():
    with pytest.raises(MessageCryptoError, match="damaged"):
        parse_input("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\nhi\n", WANT_SIGNATURE)


def test_a_bare_detached_signature_asks_for_the_whole_block():
    with pytest.raises(MessageCryptoError, match="whole signed block"):
        parse_input(SIGNATURE_ARMOR, WANT_SIGNATURE)


def test_plaintext_with_invisible_characters_is_kept():
    flow = new_flow("encrypt")
    flow["expect"] = EXPECT_TEXT
    accept_typed(flow, "\ufeffa\u200db\x07")
    assert flow["text"] == "\ufeffa\u200db\x07"


# Line breaks written out as \n, in every format that holds base64.

TYPED_BREAKS = ["\\n", "\\n ", "\\r\\n", "\\\\n"]


@pytest.mark.parametrize("sep", TYPED_BREAKS)
def test_typed_line_breaks_in_rsa_pem(rsa_key, rsa_document, sep):
    text = sep.join(rsa_key.public_key().export_key("PEM").decode().split("\n"))
    assert parse_input(text, WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document


def test_typed_line_break_after_an_ssh_key(rsa_key, rsa_document):
    text = rsa_key.public_key().export_key("OpenSSH").decode() + "\\n"
    assert parse_input(text, WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document


@pytest.mark.parametrize("sep", TYPED_BREAKS)
def test_typed_line_breaks_in_bare_base64(sep):
    raw = os.urandom(800)
    text = sep.join(_rewrap(base64.b64encode(raw).decode(), 64))
    assert parse_input(text, WANT_PUB, ALG_ML_KEM)["ek"] == b64e(raw)
    assert parse_input(sep.join(BODY_LINES), WANT_PUB, ALG_PGP_SIGN)["armor"] == normalize_armor(PGP_KEY)


def test_typed_line_breaks_inside_json_base64(rsa_document):
    wrapped = "\\\\n".join(_rewrap(rsa_document["n"], 50))
    text = json.dumps(rsa_document).replace(rsa_document["n"], wrapped)
    assert parse_input(text, WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document


def test_typed_line_breaks_inside_json_armor():
    armor = "\\\\n".join([BEGIN, *BODY_LINES, CRC_LINE, END])
    text = '{"v": 1, "op": "pub", "alg": "%s", "armor": "%s"}' % (ALG_PGP_ENCRYPT, armor)
    assert parse_input(text, WANT_PUB, ALG_PGP_ENCRYPT)["armor"] == normalize_armor(PGP_KEY)


@pytest.mark.parametrize("wrap", ["{}", '"{}"'])
def test_a_whole_escaped_json_document_is_repaired(rsa_document, wrap):
    escaped = json.dumps(rsa_document).replace('"', '\\"')
    assert parse_input(wrap.format(escaped), WANT_PUB, ALG_RSA_ENCRYPT) == rsa_document


def test_typed_line_breaks_in_a_pgp_message():
    armor = normalize_armor(PGP_KEY).replace("PUBLIC KEY BLOCK", "MESSAGE")
    text = "\\n".join(armor.strip().split("\n"))
    assert parse_input(text, WANT_ENVELOPE)["armor"] == armor


def test_repairing_typed_breaks_still_checks_the_checksum():
    damaged = "\\n".join([BEGIN, *BODY_LINES, CRC_LINE, END]).replace("P+liXH3V", "P+liXH4V")
    with pytest.raises(MessageCryptoError, match="checksum does not match"):
        parse_input(damaged, WANT_PUB, ALG_PGP_ENCRYPT)


def test_a_typed_line_break_in_signed_text_is_kept():
    # The signature covers these bytes, so a literal backslash-n must survive.
    envelope = {"v": 1, "op": "sig-rsa", "alg": "rsa-sign", "msg": "C:\\new\\nline", "sig": b64e(b"x" * 128)}
    assert parse_input(json.dumps(envelope), WANT_SIGNATURE)["msg"] == "C:\\new\\nline"
    escaped = json.dumps(envelope).replace("\\", "\\\\").replace('"', '\\"')
    assert parse_input(escaped, WANT_SIGNATURE)["msg"] == "C:\\new\\nline"


def test_a_typed_line_break_in_plaintext_is_kept():
    flow = new_flow("encrypt")
    flow["expect"] = EXPECT_TEXT
    accept_typed(flow, "first\\nsecond")
    assert flow["text"] == "first\\nsecond"


def test_unknown_text_gives_a_reason():
    with pytest.raises(MessageCryptoError, match="not a public key"):
        parse_input("hello there", WANT_PUB, ALG_RSA_ENCRYPT)
    with pytest.raises(MessageCryptoError, match="not an encrypted message"):
        parse_input("hello there", WANT_ENVELOPE)
