"""Which screen comes next in the message menu.

Does not derive keys or draw. Views call advance after a step finishes and
open the returned name. expect tells the input screen whether typed text is
a message or a JSON envelope. Electrum seeds are rejected so message keys
stay tied to the BIP-39 seed bytes.
"""

from seedsigner.message_crypto.codec import (
    OP_ENC_KEM,
    OP_ENC_PGP,
    OP_ENC_RSA,
    OP_PUB,
    OP_SIG_DSA,
    OP_SIG_PGP,
    OP_SIG_RSA,
    OP_TEXT,
    require_message,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.sanitize import (
    clean_text,
    WANT_ENVELOPE,
    WANT_PUB,
    WANT_SIGNATURE,
    parse_input,
)

ACTION_ENCRYPT = "encrypt"
ACTION_DECRYPT = "decrypt"
ACTION_SIGN = "sign"
ACTION_VERIFY = "verify"
ACTION_PUBLIC = "public-key"

EXPECT_TEXT = "text"
EXPECT_ENVELOPE = "envelope"
EXPECT_SIGNATURE = "signature"
EXPECT_PEER = "peer"

_STEP_NOTICE = "notice"
_STEP_ALG = "alg"
_STEP_KEYS = "keys"
_STEP_FINGERPRINT = "fingerprint"
_STEP_INPUT = "input"
_STEP_REVIEW = "review"
_STEP_RUN = "run"


def new_flow(action: str) -> dict:
    if action not in (
        ACTION_ENCRYPT, ACTION_DECRYPT, ACTION_SIGN, ACTION_VERIFY, ACTION_PUBLIC
    ):
        raise MessageCryptoError(f"unknown message action {action}")
    return {
        "action": action,
        "alg": None,
        "seed": None,
        "text": None,
        "envelope": None,
        "peer": None,
        "expect": None,
    }


def ensure_bip39(seed) -> None:
    from seedsigner.models.seed import ElectrumSeed

    if isinstance(seed, ElectrumSeed):
        raise MessageCryptoError("message keys require a BIP-39 seed")
    if seed.seed_bytes is None or len(seed.seed_bytes) != 64:
        raise MessageCryptoError("BIP-39 seed must be 64 bytes")


def advance(flow: dict, completed: str) -> str:
    """Record that completed finished and return the next step name."""
    action = flow.get("action")
    if completed == "menu":
        if action == ACTION_ENCRYPT:
            return _STEP_NOTICE
        if action == ACTION_DECRYPT:
            return _STEP_KEYS
        return _STEP_ALG
    if completed == "notice":
        return _STEP_ALG
    if completed == "alg":
        return _STEP_KEYS
    if completed == "peer":
        # A key that just came in is checked against its owner's fingerprint first.
        return _STEP_FINGERPRINT
    if completed in ("keys", "fingerprint"):
        return _after_key(flow)
    if completed == "text":
        return _STEP_REVIEW
    if completed == "review":
        return _STEP_RUN
    if completed == "payload":
        return _STEP_RUN
    raise MessageCryptoError(f"unknown message step {completed}")


def result_qr_note(action: str) -> str:
    """Sentence shown before a result QR so the code is not mistaken for a key."""
    if action == ACTION_ENCRYPT:
        return "This QR is the encrypted message, not the public key."
    if action == ACTION_SIGN:
        return "This QR is the signature."
    if action == ACTION_PUBLIC:
        return "This QR is the public key."
    raise MessageCryptoError(f"action {action} does not show a result QR")


def _after_key(flow: dict) -> str:
    """The key is already chosen. Collect the message, or show a public key."""
    action = flow.get("action")
    if action == ACTION_PUBLIC:
        return _STEP_RUN
    if action in (ACTION_ENCRYPT, ACTION_SIGN):
        flow["expect"] = EXPECT_TEXT
        return _STEP_INPUT
    if action == ACTION_DECRYPT:
        flow["expect"] = EXPECT_ENVELOPE
        return _STEP_INPUT
    if action == ACTION_VERIFY:
        flow["expect"] = EXPECT_SIGNATURE
        return _STEP_INPUT
    raise MessageCryptoError(f"action {action} does not use a key")


def accept_typed(flow: dict, text: str) -> str:
    """Store typed or scanned text. Plaintext is raw; other steps need an
    envelope, or a bare OpenPGP armor block from another PGP app."""
    if flow.get("expect") == EXPECT_TEXT:
        flow["text"] = require_message(text)
        return advance(flow, "text")
    return accept_document(flow, document_from_text(flow, text))


def accept_copied(flow: dict, text: str) -> str:
    """Store text from a QR or the relay, which came through copy and paste.

    Keys and envelopes are repaired by parse_input. Plaintext has what doesn't print
    removed here, so what the device shows is exactly what gets signed or encrypted.
    Typed text can't hold those characters, so accept_typed keeps it as it is.
    """
    if flow.get("expect") == EXPECT_TEXT:
        text = clean_text(text)
    return accept_typed(flow, text)


def document_from_text(flow: dict, text: str) -> dict:
    """Parse typed or scanned text into the envelope this step expects.

    Accepts the device's JSON envelopes and other apps' key formats (PGP
    armor, RSA PEM, bare base64), repairing copy damage first. See sanitize.
    """
    want = {
        EXPECT_PEER: WANT_PUB,
        EXPECT_ENVELOPE: WANT_ENVELOPE,
        EXPECT_SIGNATURE: WANT_SIGNATURE,
    }.get(flow.get("expect"))
    if want is None:
        raise MessageCryptoError("this screen is not waiting for input")
    return parse_input(text, want, flow.get("alg"))


def accept_document(flow: dict, document: dict) -> str:
    """Store a scanned or pasted envelope that matches flow['expect']."""
    expect = flow.get("expect")
    op = document.get("op")
    if expect == EXPECT_TEXT:
        if op != OP_TEXT:
            raise MessageCryptoError("expected a plaintext QR")
        flow["text"] = require_message(document.get("msg"))
        return advance(flow, "text")
    if expect == EXPECT_PEER:
        if op != OP_PUB:
            raise MessageCryptoError("expected a public key")
        flow["peer"] = document
        return advance(flow, "peer")
    if expect == EXPECT_ENVELOPE:
        if op not in (OP_ENC_RSA, OP_ENC_KEM, OP_ENC_PGP):
            raise MessageCryptoError("expected an encrypted message")
        flow["envelope"] = document
        return advance(flow, "payload")
    if expect == EXPECT_SIGNATURE:
        if op not in (OP_SIG_RSA, OP_SIG_DSA, OP_SIG_PGP):
            raise MessageCryptoError("expected a signature")
        flow["envelope"] = document
        return advance(flow, "payload")
    raise MessageCryptoError("this screen is not waiting for input")


def encrypt_notice() -> dict:
    """Copy shown as soon as Encrypt is chosen, before the message keyboard."""
    return {
        "title": "Their key",
        "headline": "Not your seed",
        "text": "Your seed holds your keys. Encrypting needs their public key.",
    }

