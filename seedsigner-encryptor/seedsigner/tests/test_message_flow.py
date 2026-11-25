"""Navigation decisions for the message menu, without the UI.

Does not derive keys. Views call the same advance and accept functions.
Encrypt and verify select a public key before the message. Sign and decrypt
select an own seed before the message.
"""

import pytest

from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.flow import (
    accept_document,
    accept_typed,
    advance,
    new_flow,
    result_qr_note,
)


def test_encrypt_selects_the_key_before_the_message():
    flow = new_flow("encrypt")
    assert advance(flow, "menu") == "notice"
    assert advance(flow, "notice") == "alg"
    flow["alg"] = "rsa-encrypt"
    assert advance(flow, "alg") == "keys"
    flow["peer"] = {"v": 1, "op": "pub", "alg": "rsa-encrypt", "n": "AQ", "e": 65537}
    assert advance(flow, "keys") == "input"
    assert flow["expect"] == "text"
    assert accept_typed(flow, "hello") == "review"
    assert advance(flow, "review") == "run"
    assert "encrypted message" in result_qr_note("encrypt")
    assert "not the public key" in result_qr_note("encrypt")


def test_sign_selects_the_own_key_before_the_message():
    flow = new_flow("sign")
    assert advance(flow, "menu") == "alg"
    assert advance(flow, "alg") == "keys"
    assert advance(flow, "keys") == "input"
    assert flow["expect"] == "text"
    assert "signature" in result_qr_note("sign")


def test_decrypt_selects_the_own_key_then_the_ciphertext():
    flow = new_flow("decrypt")
    assert advance(flow, "menu") == "keys"
    assert advance(flow, "keys") == "input"
    assert flow["expect"] == "envelope"


def test_verify_selects_the_signer_key_before_the_signature():
    flow = new_flow("verify")
    flow["alg"] = "rsa-sign"
    assert advance(flow, "menu") == "alg"
    assert advance(flow, "alg") == "keys"
    assert advance(flow, "keys") == "input"
    assert flow["expect"] == "signature"
    document = {
        "v": 1,
        "op": "sig-rsa",
        "alg": "rsa-sign",
        "msg": "hello",
        "sig": "aa",
    }
    assert accept_document(flow, document) == "run"


def test_plaintext_qr_is_rejected_when_a_public_key_is_expected():
    flow = new_flow("encrypt")
    advance(flow, "menu")
    advance(flow, "notice")
    advance(flow, "alg")
    flow["expect"] = "peer"
    with pytest.raises(MessageCryptoError, match="public key"):
        accept_document(flow, {"v": 1, "op": "text", "msg": "nope"})


def test_public_key_export_does_not_collect_text():
    flow = new_flow("public-key")
    assert advance(flow, "menu") == "alg"
    assert advance(flow, "alg") == "keys"
    assert advance(flow, "keys") == "run"
    assert "public key" in result_qr_note("public-key")
