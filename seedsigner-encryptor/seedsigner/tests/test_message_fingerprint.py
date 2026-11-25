"""Public key fingerprints, and the screen that checks a key that just came in.

The PGP fingerprint must be the one gpg and SHAP (OpenPGP.js) show for the same
key, so people can compare them across apps. The expected values here come from
gpg and openssl, not from the code under test.
"""

import hashlib
from unittest.mock import patch

import pytest
from base import FlowStep, FlowTest
from test_message_pgp_text_qr import SHAP_KEY

from seedsigner.controller import Controller
from seedsigner.message_crypto.codec import ALG_ML_DSA, ALG_ML_KEM, ALG_PGP_ENCRYPT, ALG_RSA_ENCRYPT
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.fingerprint import (
    fingerprint,
    format_fingerprint,
    kind,
    screen_lines,
    short_fingerprint,
)
from seedsigner.message_crypto.flow import ACTION_ENCRYPT, ACTION_PUBLIC, EXPECT_PEER, advance, new_flow
from seedsigner.message_crypto.key_catalog import choices_for
from seedsigner.message_crypto.ml_dsa_ops import export_public as export_dsa_public
from seedsigner.message_crypto.ml_dsa_ops import keypair as dsa_keypair
from seedsigner.message_crypto.ml_kem_ops import export_public as export_kem_public
from seedsigner.message_crypto.ml_kem_ops import keypair as kem_keypair
from seedsigner.message_crypto.sanitize import WANT_PUB, parse_input
from seedsigner.views.message_collect_views import (
    MessageFingerprintView,
    MessageInputChoiceView,
    MessageTextEntryView,
)
from seedsigner.views.message_run_views import MessagePublicFingerprintView, MessageResultFormatView
from seedsigner.views.message_views import (
    MessageAlgorithmView,
    MessageEncryptNoticeView,
    MessageKeyListView,
    MessageMenuView,
)
from seedsigner.views.view import ErrorView

# gpg --show-keys --with-colons on SHAP_KEY: the primary (Ed25519) key's fingerprint.
SHAP_FINGERPRINT = "595B4C24A4A006CDD629E5C0430587A4258FACD5"

# A 1024-bit key made with openssl genpkey. The fingerprint is
# openssl pkey -pubout -outform DER | sha256sum, first 40 hex digits.
OPENSSL_RSA_N = (
    "xRb7Bnwy-1StcMhldPwpv4dosWu7-uNxA19sDbbwZSufGKaxHTS0ijHFtsJl-5mdwabjAXRuCbIcY_DyiIGx5TcK6_"
    "MrvfBsYF5SnMPuh0Aqc0NMnhjXT0Ymh1Uggm5e5ddu1K9OhTkXFqe7dE0CVGlG3WsBfzIO8F9DOY5Feb8"
)
OPENSSL_RSA_FINGERPRINT = "C59154BF71E97ECF3C329F8153CA7C7D0D9D06E5"


def _shap_document() -> dict:
    return parse_input(SHAP_KEY, WANT_PUB, ALG_PGP_ENCRYPT)


def test_pgp_fingerprint_matches_gpg_for_a_shap_key():
    assert fingerprint(_shap_document()) == SHAP_FINGERPRINT


def test_rsa_fingerprint_matches_openssl():
    document = {"v": 1, "op": "pub", "alg": ALG_RSA_ENCRYPT, "n": OPENSSL_RSA_N, "e": 65537}
    assert fingerprint(document) == OPENSSL_RSA_FINGERPRINT


@pytest.mark.parametrize("make", ["ml-kem", "ml-dsa"])
def test_ml_fingerprints_hash_the_raw_public_key(make):
    seed = bytes(range(64))
    if make == "ml-kem":
        raw, _secret = kem_keypair(seed)
        document = export_kem_public(raw)
    else:
        raw, _secret = dsa_keypair(seed[:32])
        document = export_dsa_public(raw)
    assert fingerprint(document) == hashlib.sha256(raw).hexdigest()[:40].upper()
    assert kind(document) == "SHA-256 fingerprint"


def test_only_public_keys_have_a_fingerprint():
    with pytest.raises(MessageCryptoError):
        fingerprint({"v": 1, "op": "text", "msg": "hello"})
    with pytest.raises(MessageCryptoError):
        fingerprint({"v": 1, "op": "pub", "alg": "rsa-encrypt", "n": "Ag", "e": 65537})


def test_formats_follow_gpg():
    assert format_fingerprint(SHAP_FINGERPRINT.lower()) == (
        "595B 4C24 A4A0 06CD D629  E5C0 4305 87A4 258F ACD5"
    )
    assert screen_lines(SHAP_FINGERPRINT) == "595B 4C24 A4A0 06CD D629\nE5C0 4305 87A4 258F ACD5"
    assert short_fingerprint(SHAP_FINGERPRINT) == "595B 4C24"
    assert kind(_shap_document()) == "OpenPGP fingerprint"
    with pytest.raises(MessageCryptoError):
        format_fingerprint("ABCD")


def test_imported_key_label_starts_with_its_fingerprint():
    entries = choices_for(ACTION_ENCRYPT, ALG_PGP_ENCRYPT, [], [_shap_document()])["entries"]
    assert [entry["label"] for entry in entries if entry["document"] is not None][0] == (
        "Contact (imported) 595B 4C24"
    )


def test_a_key_that_came_in_is_checked_before_it_is_used():
    flow = new_flow(ACTION_ENCRYPT)
    flow["alg"] = ALG_PGP_ENCRYPT
    flow["peer"] = _shap_document()
    assert advance(flow, "peer") == "fingerprint"
    assert advance(flow, "fingerprint") == "input"
    # A key chosen from the list was checked when it came in.
    assert advance(flow, "keys") == "input"


def test_doesnt_match_is_the_default_button():
    controller = Controller.get_instance()
    controller.message_flow = new_flow(ACTION_ENCRYPT)
    controller.message_flow["peer"] = _shap_document()
    view = MessageFingerprintView()
    with patch.object(MessageFingerprintView, "run_screen", return_value=1) as run_screen:
        view.run()
    kwargs = run_screen.call_args.kwargs
    assert kwargs["button_data"][kwargs["selected_button"]] == MessageFingerprintView.NO_MATCH
    assert kwargs["fingerprint_lines"] == "595B 4C24 A4A0 06CD D629\nE5C0 4305 87A4 258F ACD5"


class TestFingerprintFlows(FlowTest):
    def _enter_shap_key(self) -> list:
        return [
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.ENCRYPT),
            FlowStep(MessageEncryptNoticeView, button_data_selection=MessageEncryptNoticeView.CONTINUE),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.PGP),
            FlowStep(MessageKeyListView, button_data_selection=MessageKeyListView.ENTER),
            FlowStep(MessageTextEntryView, screen_return_value=SHAP_KEY),
        ]

    def test_a_matching_key_is_kept_and_used(self):
        self.controller.message_contacts = []
        self.run_sequence(self._enter_shap_key() + [
            FlowStep(MessageFingerprintView, button_data_selection=MessageFingerprintView.MATCHES),
            FlowStep(MessageInputChoiceView),
        ])
        assert [fingerprint(key) for key in self.controller.message_contacts] == [SHAP_FINGERPRINT]

    def test_a_key_that_doesnt_match_is_dropped(self):
        self.controller.message_contacts = []
        self.run_sequence(self._enter_shap_key() + [
            FlowStep(MessageFingerprintView, button_data_selection=MessageFingerprintView.NO_MATCH),
            FlowStep(ErrorView),
        ])
        assert self.controller.message_contacts == []
        assert self.controller.message_flow is None

    def test_view_public_key_offers_the_fingerprint(self):
        def with_result(view):
            view.controller.message_flow = new_flow(ACTION_PUBLIC)
            view.controller.message_flow["result"] = _shap_document()
            view.controller.message_flow["peer"] = _shap_document()

        self.run_sequence([
            FlowStep(
                MessageResultFormatView,
                before_run=with_result,
                button_data_selection=MessageResultFormatView.FINGERPRINT,
            ),
            FlowStep(MessagePublicFingerprintView),
        ])
