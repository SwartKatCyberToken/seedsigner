"""Derive test keys from testseed.txt and copy the public keys into the app.

Run from the repo root or from this directory:

    python test-data/testhelper.py

Uses seedsigner.message_crypto. Device RSA size is 2048 bits, so these keys
match a seed loaded on the device. ML-KEM cannot sign; that folder's
test-signed-message.txt is a ciphertext, with a note on the first lines.
The mnemonic in testseed.txt is the public BIP-39 test vector, not a wallet.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "seedsigner" / "src"))

from embit import bip39  # noqa: E402

from seedsigner.message_crypto.codec import (  # noqa: E402
    ALG_ML_KEM,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    dumps,
)
from seedsigner.message_crypto.keys import keys_for_seed  # noqa: E402
from seedsigner.message_crypto.operations import encrypt_for, export_public, sign_with  # noqa: E402
from seedsigner.message_crypto.pgp_ops import private_armor  # noqa: E402

MESSAGE = "seedsigner test message"
INI = ROOT / "seedsigner" / "preloaded-public-keys.ini"


def main() -> None:
    mnemonic = " ".join(HERE.joinpath("testseed.txt").read_text(encoding="utf-8").split())
    seed = bip39.mnemonic_to_seed(mnemonic, password="")
    keys = keys_for_seed(seed)
    documents = {
        ALG_RSA_ENCRYPT: export_public(keys, ALG_RSA_ENCRYPT),
        ALG_RSA_SIGN: export_public(keys, ALG_RSA_SIGN),
        ALG_ML_KEM: export_public(keys, ALG_ML_KEM),
        ALG_PGP_SIGN: export_public(keys, ALG_PGP_SIGN),
    }
    _write_rsa(keys, documents)
    _write_kem(keys, documents[ALG_ML_KEM])
    _write_pgp(keys, documents)
    _write_ini(documents)
    print(f"wrote public keys to {INI}")


def _write_rsa(keys, documents: dict) -> None:
    folder = HERE / "rsa"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pub").write_text(
        "# rsa-encrypt\n" + dumps(documents[ALG_RSA_ENCRYPT]) + "\n"
        "# rsa-sign\n" + dumps(documents[ALG_RSA_SIGN]) + "\n",
        encoding="utf-8",
    )
    (folder / "priv").write_text(
        "# rsa-encrypt\n" + keys.rsa_encryption_key().export_key().decode() + "\n"
        "# rsa-sign\n" + keys.rsa_signing_key().export_key().decode() + "\n",
        encoding="utf-8",
    )
    signed = sign_with(keys, ALG_RSA_SIGN, MESSAGE)
    (folder / "test-signed-message.txt").write_text(dumps(signed) + "\n", encoding="utf-8")


def _write_kem(keys, public: dict) -> None:
    folder = HERE / "ml-kem"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pub").write_text(dumps(public) + "\n", encoding="utf-8")
    _encapsulation, secret = keys.ml_kem_keys()
    import base64
    (folder / "priv").write_text(base64.b64encode(secret).decode("ascii") + "\n", encoding="utf-8")
    ciphertext = encrypt_for(keys, ALG_ML_KEM, public, MESSAGE)
    (folder / "test-signed-message.txt").write_text(
        "# ML-KEM-512 does not sign. The JSON line is a ciphertext encrypted to this public key.\n"
        "# decrypt-helper.py opens it with the test seed.\n"
        + dumps(ciphertext) + "\n",
        encoding="utf-8",
    )


def _write_pgp(keys, documents: dict) -> None:
    folder = HERE / "pgp"
    folder.mkdir(parents=True, exist_ok=True)
    # One block: the signing key with the encryption key as its subkey.
    (folder / "pub").write_text(documents[ALG_PGP_SIGN]["armor"], encoding="utf-8")
    (folder / "priv").write_text(
        private_armor(keys.rsa_signing_key(), keys.rsa_encryption_key()), encoding="utf-8"
    )
    signed = sign_with(keys, ALG_PGP_SIGN, MESSAGE)
    (folder / "test-signed-message.txt").write_text(dumps(signed) + "\n", encoding="utf-8")


def _write_ini(documents: dict) -> None:
    lines = [
        "# Public keys the Messages menu lists as Contact (preloaded).",
        "# test-data/testhelper.py writes this from test-data/testseed.txt.",
        "# Section names are public-key algorithms. label is the list name.",
        "# document is one JSON envelope.",
        "",
    ]
    for alg, document in documents.items():
        lines.append(f"[{alg}]")
        lines.append("label = testseed")
        lines.append("document = " + dumps(document))
        lines.append("")
    INI.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
