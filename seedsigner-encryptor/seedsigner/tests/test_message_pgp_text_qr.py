"""Bare OpenPGP armor from other PGP apps, typed or scanned as ur:bytes text.

Apps such as SHAP send text over a few hundred bytes as an animated
ur:bytes QR holding the UTF-8 text. A PGP public key arrives that way as a
bare PUBLIC KEY BLOCK, not as a v1 JSON envelope. These tests build such
frames, scan them with DecodeQR, and encrypt to the key.
"""

import pytest
from base import BaseTest

from seedsigner.helpers.ur2.ur import UR
from seedsigner.helpers.ur2.ur_encoder import UREncoder
from seedsigner.message_crypto.codec import ALG_PGP_ENCRYPT, ALG_RSA_ENCRYPT, OP_ENC_PGP, OP_PUB
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.flow import (
    ACTION_DECRYPT,
    ACTION_ENCRYPT,
    ACTION_VERIFY,
    EXPECT_ENVELOPE,
    EXPECT_PEER,
    EXPECT_SIGNATURE,
    EXPECT_TEXT,
    accept_copied,
    accept_typed,
    new_flow,
)
from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus
from urtypes.bytes import Bytes


def _ur_frames(text: str, fragment_len: int = 120):
    encoder = UREncoder(UR("bytes", Bytes(text.encode("utf-8")).to_cbor()), fragment_len)
    while True:
        yield encoder.next_part()


def _scan(text: str) -> DecodeQR:
    decoder = DecodeQR()
    for count, frame in enumerate(_ur_frames(text)):
        status = decoder.add_data(frame)
        if status == DecodeQRStatus.COMPLETE:
            return decoder
        assert count < 500, "decoder never completed"
    raise AssertionError("unreachable")


def _peer_flow(alg: str = ALG_PGP_ENCRYPT) -> dict:
    flow = new_flow(ACTION_ENCRYPT)
    flow["alg"] = alg
    flow["expect"] = EXPECT_PEER
    return flow


def test_ur_bytes_text_is_message_text():
    decoder = _scan("hello " * 100)
    assert decoder.is_message_text
    assert not decoder.is_message_crypto
    assert decoder.get_message_text() == "hello " * 100


FAKE_KEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nxgEE\n-----END PGP PUBLIC KEY BLOCK-----"


def test_bare_public_key_armor_becomes_a_pub_envelope():
    flow = _peer_flow()
    accept_typed(flow, FAKE_KEY)
    assert flow["peer"]["op"] == OP_PUB
    assert flow["peer"]["alg"] == ALG_PGP_ENCRYPT
    assert flow["peer"]["armor"].endswith("-----END PGP PUBLIC KEY BLOCK-----\n")


def test_pgp_key_needs_the_pgp_algorithm():
    with pytest.raises(MessageCryptoError, match="choose PGP"):
        accept_typed(_peer_flow(ALG_RSA_ENCRYPT), FAKE_KEY)


def test_pgp_message_is_not_a_public_key():
    with pytest.raises(MessageCryptoError, match="PUBLIC KEY BLOCK"):
        accept_typed(_peer_flow(), "-----BEGIN PGP MESSAGE-----\n\nwQED\n-----END PGP MESSAGE-----")


def test_bare_pgp_message_becomes_an_enc_pgp_envelope():
    flow = new_flow(ACTION_DECRYPT)
    flow["expect"] = EXPECT_ENVELOPE
    accept_typed(flow, "-----BEGIN PGP MESSAGE-----\n\nwQED\n-----END PGP MESSAGE-----\n")
    assert flow["envelope"]["op"] == OP_ENC_PGP


# An OpenPGP.js Ed25519 + Curve25519 key, as SHAP made it.
SHAP_KEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

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


def test_armor_with_line_breaks_turned_into_spaces_is_repaired():
    from seedsigner.message_crypto.sanitize import normalize_armor
    flattened = " ".join(SHAP_KEY.split("\n")).strip()
    assert "\n" not in flattened
    canonical = normalize_armor(SHAP_KEY)
    assert normalize_armor(flattened) == canonical
    assert normalize_armor(SHAP_KEY.replace("\n", "\r\n")) == canonical
    assert normalize_armor(canonical) == canonical


@pytest.mark.parametrize("flatten", [False, True], ids=["line-breaks", "spaces"])
def test_shap_key_scans_and_encrypts(flatten):
    pgpy = _pgpy()
    from seedsigner.message_crypto.operations import encrypt_for

    text = " ".join(SHAP_KEY.split("\n")).strip() if flatten else SHAP_KEY
    flow = _peer_flow()
    accept_typed(flow, _scan(text).get_message_text())
    envelope = encrypt_for(None, ALG_PGP_ENCRYPT, flow["peer"], "meet at noon")
    assert "-----BEGIN PGP MESSAGE-----" in envelope["armor"]


# Real keys, as RSA (the device's own type) and Curve25519 (OpenPGP.js's default).

def _pgpy():
    try:
        import pgpy
    except Exception:  # PGPy 0.6.0 does not import on Python 3.13+ (imghdr)
        pytest.skip("PGPy is not importable on this Python")
    return pgpy


def _rsa_key(pgpy):
    from pgpy.constants import KeyFlags, PubKeyAlgorithm
    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    key.add_uid(pgpy.PGPUID.new("rsa peer"), usage={KeyFlags.Sign, KeyFlags.EncryptCommunications})
    return key


def _curve25519_key(pgpy):
    from pgpy.constants import EllipticCurveOID, KeyFlags, PubKeyAlgorithm
    key = pgpy.PGPKey.new(PubKeyAlgorithm.EdDSA, EllipticCurveOID.Ed25519)
    key.add_uid(pgpy.PGPUID.new("ecc peer"), usage={KeyFlags.Sign})
    sub = pgpy.PGPKey.new(PubKeyAlgorithm.ECDH, EllipticCurveOID.Curve25519)
    key.add_subkey(sub, usage={KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage})
    return key


@pytest.mark.parametrize("make_key", [_rsa_key, _curve25519_key], ids=["rsa", "curve25519"])
def test_scanned_pgp_public_key_encrypts(make_key):
    pgpy = _pgpy()
    from seedsigner.message_crypto.operations import encrypt_for

    private = make_key(pgpy)
    decoder = _scan(str(private.pubkey))
    flow = _peer_flow()
    accept_typed(flow, decoder.get_message_text())

    envelope = encrypt_for(None, ALG_PGP_ENCRYPT, flow["peer"], "meet at noon")
    assert envelope["op"] == OP_ENC_PGP
    clear = private.decrypt(pgpy.PGPMessage.from_blob(envelope["armor"]))
    assert clear.message == "meet at noon"


# Plain text QRs, as a QR generator app makes them after a copy and paste.

COPY_DAMAGE = {
    "clean": lambda text: text,
    "BOM and zero-width": lambda text: "\ufeff" + text.replace("\n", "\u200b\n"),
    "typed line breaks": lambda text: text.strip().replace("\n", "\\n"),
    "flattened with no-break spaces": lambda text: text.strip().replace("\n", "\xa0"),
    "control characters": lambda text: "\x00" + text.replace("\n", "\x07\n") + "\x1b[0m",
}


def _scan_plain(text, as_bytes=True) -> DecodeQR:
    decoder = DecodeQR(accept_plain_text=True)
    status = decoder.add_data(text.encode("utf-8") if as_bytes else text)
    assert status == DecodeQRStatus.COMPLETE
    return decoder


@pytest.mark.parametrize("damage", COPY_DAMAGE)
def test_plain_text_qr_with_a_damaged_pgp_key_is_repaired(damage):
    from seedsigner.message_crypto.sanitize import normalize_armor

    flow = _peer_flow()
    accept_copied(flow, _scan_plain(COPY_DAMAGE[damage](SHAP_KEY)).get_message_text())
    assert flow["peer"]["armor"] == normalize_armor(SHAP_KEY)


def test_plain_text_qr_is_only_read_where_it_was_asked_for():
    assert DecodeQR().add_data(SHAP_KEY.encode("utf-8")) == DecodeQRStatus.INVALID


def test_plain_text_qr_keeps_seeds_out():
    from seedsigner.models.qr_type import QRType

    words = " ".join(["abandon"] * 11 + ["about"])
    for text in (words, "\u200b" + words.replace(" ", "\u200b ") + "\n", "0" * 48):
        decoder = DecodeQR(accept_plain_text=True)
        decoder.add_data(text.encode("utf-8"))
        assert decoder.is_seed and not decoder.is_message_text
    binary_seed = bytes(range(0x80, 0x90))
    decoder = DecodeQR(accept_plain_text=True)
    decoder.add_data(binary_seed)
    assert decoder.qr_type == QRType.SEED__COMPACTSEEDQR


@pytest.mark.parametrize("text", ["sixteen chars ok", "x" * 32])
def test_text_the_length_of_a_compact_seed_is_text(text):
    assert _scan_plain(text).get_message_text() == text


def test_a_qr_that_is_only_invisible_characters_is_not_text():
    decoder = DecodeQR(accept_plain_text=True)
    assert decoder.add_data("\u200b\ufeff\n".encode("utf-8")) == DecodeQRStatus.INVALID


def test_scanned_plaintext_loses_what_does_not_print():
    flow = new_flow(ACTION_ENCRYPT)
    flow["expect"] = EXPECT_TEXT
    accept_copied(flow, _scan_plain("\ufeffmeet\u200b at\xa0noon\u202e\r\nline two\n").get_message_text())
    assert flow["text"] == "meet at noon\nline two"


def test_scanned_ur_bytes_plaintext_loses_what_does_not_print():
    flow = new_flow(ACTION_ENCRYPT)
    flow["expect"] = EXPECT_TEXT
    accept_copied(flow, _scan("meet\u200b at noon " * 40).get_message_text())
    assert "\u200b" not in flow["text"] and flow["text"].startswith("meet at noon")


def test_scanned_plaintext_with_nothing_left_is_refused():
    flow = new_flow(ACTION_ENCRYPT)
    flow["expect"] = EXPECT_TEXT
    with pytest.raises(MessageCryptoError, match="empty"):
        accept_copied(flow, "\u200b\ufeff")


def test_scanned_signature_keeps_the_exact_signed_text():
    from seedsigner.message_crypto.codec import b64e, dumps

    message = "family \U0001F468\u200d\U0001F469"
    envelope = {"v": 1, "op": "sig-rsa", "alg": "rsa-sign", "msg": message, "sig": b64e(b"x" * 128)}
    flow = new_flow(ACTION_VERIFY)
    flow["expect"] = EXPECT_SIGNATURE
    accept_copied(flow, _scan_plain("\ufeff" + dumps(envelope)).get_message_text())
    assert flow["envelope"]["msg"] == message


@pytest.mark.parametrize("prefix", ["", "\ufeff", "\u200b\n"])
def test_message_frames_survive_a_copy_with_their_chunk_intact(prefix):
    from seedsigner.message_crypto.codec import dumps
    from seedsigner.message_crypto.qr_codec import split_frames

    document = {"v": 1, "op": "text", "msg": "a\u200db " * 40}
    decoder = DecodeQR(accept_plain_text=True)
    for frame in split_frames(dumps(document)):
        status = decoder.add_data((prefix + frame).encode("utf-8"))
    assert status == DecodeQRStatus.COMPLETE
    assert decoder.is_message_crypto
    assert decoder.get_qr_data()["msg"] == document["msg"]


def test_damaged_ur_frames_still_decode():
    decoder = DecodeQR(accept_plain_text=True)
    for count, frame in enumerate(_ur_frames("hello " * 100)):
        if decoder.add_data(("\ufeff" + frame + "\u200b\n").encode("utf-8")) == DecodeQRStatus.COMPLETE:
            break
        assert count < 500, "decoder never completed"
    assert decoder.get_message_text() == "hello " * 100


class TestMessageScreens(BaseTest):
    def test_scan_screen_accepts_a_generator_app_qr(self):
        from seedsigner.controller import Controller
        from seedsigner.views.message_collect_views import MessageIngestQrView, MessageScanView

        controller = Controller.get_instance()
        controller.message_flow = _peer_flow()
        view = MessageScanView()
        assert view.decoder.add_data(COPY_DAMAGE["typed line breaks"](SHAP_KEY).encode("utf-8")) == DecodeQRStatus.COMPLETE
        assert view.is_valid_qr_type

        controller.message_scanned = view.decoder.get_message_text()
        MessageIngestQrView().run()
        assert controller.message_flow["peer"]["op"] == OP_PUB
