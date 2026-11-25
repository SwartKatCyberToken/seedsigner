"""Key list contents for encrypt, sign, verify, and view public key.

Does not draw. Preloaded keys come from a temporary INI file.
"""

from seedsigner.message_crypto.flow import ACTION_ENCRYPT, ACTION_PUBLIC, ACTION_SIGN, ACTION_VERIFY
from seedsigner.message_crypto.key_catalog import (
    ROLE_IMPORTED,
    ROLE_OWN,
    ROLE_PRELOADED,
    choices_for,
    remember_contact,
)
from seedsigner.message_crypto.preloaded import append_preloaded, document_from_paste


_RSA = {"v": 1, "op": "pub", "alg": "rsa-encrypt", "n": "AQ", "e": 65537}


def test_encrypt_offers_a_named_preloaded_key_and_not_the_seed(monkeypatch, tmp_path):
    path = tmp_path / "keys.ini"
    monkeypatch.setenv("SEEDSIGNER_PRELOADED_KEYS", str(path))
    append_preloaded(path, "rsa-encrypt", "alice", _RSA)
    catalog = choices_for(
        ACTION_ENCRYPT,
        "rsa-encrypt",
        [{"seed": object(), "fingerprint": "abcdef12"}],
        [],
    )
    assert catalog["blocked"] is None
    assert catalog["allow_other"] is True
    assert [item["role"] for item in catalog["entries"]] == [ROLE_PRELOADED]
    assert catalog["entries"][0]["label"] == "Contact (preloaded) alice"


def test_sign_offers_only_the_own_seed(monkeypatch, tmp_path):
    monkeypatch.setenv("SEEDSIGNER_PRELOADED_KEYS", str(tmp_path / "missing.ini"))
    blocked = choices_for(ACTION_SIGN, "rsa-sign", [], [])
    assert blocked["blocked"].startswith("Signing uses your private key")
    catalog = choices_for(
        ACTION_SIGN,
        "rsa-sign",
        [{"seed": "seed", "fingerprint": "abcdef12"}],
        [_RSA],
    )
    assert catalog["blocked"] is None
    assert catalog["entries"] == [{
        "role": ROLE_OWN,
        "label": "Own (Seed) abcdef12",
        "seed": "seed",
        "document": None,
    }]


def test_view_public_key_lists_own_imported_and_preloaded(monkeypatch, tmp_path):
    path = tmp_path / "keys.ini"
    monkeypatch.setenv("SEEDSIGNER_PRELOADED_KEYS", str(path))
    append_preloaded(path, "rsa-encrypt", "alice", _RSA)
    imported = {"v": 1, "op": "pub", "alg": "rsa-encrypt", "n": "Ag", "e": 65537}
    catalog = choices_for(
        ACTION_PUBLIC,
        "rsa-encrypt",
        [{"seed": "seed", "fingerprint": "abcdef12"}],
        remember_contact([], imported),
    )
    roles = [item["role"] for item in catalog["entries"]]
    assert roles == [ROLE_OWN, ROLE_IMPORTED, ROLE_PRELOADED]


def test_a_pasted_pgp_block_and_a_second_key_get_their_own_section(tmp_path):
    path = tmp_path / "keys.ini"
    armor = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nxgEE\n-----END PGP PUBLIC KEY BLOCK-----\n"
    first = document_from_paste("pgp-rsa-sign", armor)
    assert append_preloaded(path, "pgp-rsa-sign", "desk", first) == "pgp-rsa-sign"
    second = document_from_paste("pgp-rsa-sign", armor.replace("xgEE", "xgEF"))
    assert append_preloaded(path, "pgp-rsa-sign", "phone", second) == "pgp-rsa-sign.2"


def test_a_pgp_key_saved_for_one_step_is_offered_for_the_other(monkeypatch, tmp_path):
    from seedsigner.message_crypto.codec import ALG_PGP_ENCRYPT, ALG_PGP_SIGN

    path = tmp_path / "keys.ini"
    monkeypatch.setenv("SEEDSIGNER_PRELOADED_KEYS", str(path))
    armor = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nxgEE\n-----END PGP PUBLIC KEY BLOCK-----\n"
    append_preloaded(path, ALG_PGP_SIGN, "friend", document_from_paste(ALG_PGP_SIGN, armor))
    imported = [document_from_paste(ALG_PGP_ENCRYPT, armor.replace("xgEE", "xgEF"))]
    for action, alg in ((ACTION_ENCRYPT, ALG_PGP_ENCRYPT), (ACTION_VERIFY, ALG_PGP_SIGN)):
        labels = [entry["label"] for entry in choices_for(action, alg, [], imported)["entries"]]
        assert "Contact (preloaded) friend" in labels
        assert any(label.startswith("Contact (imported)") for label in labels)
