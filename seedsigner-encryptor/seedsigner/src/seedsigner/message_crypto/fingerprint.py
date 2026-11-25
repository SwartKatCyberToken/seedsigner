"""Fingerprints people compare to check that a public key is the right one.

Does not draw. Views show format_fingerprint(...) and ask the person to compare
it with the one the key's owner gives them some other way: read aloud, shown on
their own screen, or printed.

A PGP key's fingerprint is the standard OpenPGP v4 fingerprint of its primary
key, the same 40 hex digits that gpg, SHAP (OpenPGP.js) and other PGP apps show,
so it can be compared across apps.

The other key types have no standard fingerprint, so they use the first 160 bits
(40 hex digits) of a SHA-256, which stock tools can recompute:

- RSA: SHA-256 of the DER SubjectPublicKeyInfo, as in
  ``openssl pkey -pubin -outform DER | sha256sum``.
- ML-DSA-44 and ML-KEM-512: SHA-256 of the raw public key bytes (the pk or ek field).

Every fingerprint is shown the way gpg shows one: ten groups of four upper-case
hex digits, with two spaces between the fifth and the sixth.
"""

import hashlib

from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    OP_PUB,
    PGP_PUBLIC_ALGS,
)
from seedsigner.message_crypto.errors import MessageCryptoError

FINGERPRINT_HEX_DIGITS = 40
# Enough to tell keys apart in a list. Never enough to check a key: use the full one.
SHORT_HEX_DIGITS = 8


def fingerprint(document: dict) -> str:
    """The key's fingerprint as 40 upper-case hex digits with no spaces."""
    if not isinstance(document, dict) or document.get("op") != OP_PUB:
        raise MessageCryptoError("only a public key has a fingerprint")
    alg = document.get("alg")
    if alg in PGP_PUBLIC_ALGS:
        from seedsigner.message_crypto.pgp_ops import primary_fingerprint
        return primary_fingerprint(document.get("armor"))
    if alg in (ALG_RSA_SIGN, ALG_RSA_ENCRYPT):
        from seedsigner.message_crypto.rsa_ops import import_public
        raw = import_public(document).export_key(format="DER")
    elif alg == ALG_ML_DSA:
        from seedsigner.message_crypto.ml_dsa_ops import import_public
        raw = import_public(document)
    elif alg == ALG_ML_KEM:
        from seedsigner.message_crypto.ml_kem_ops import import_public
        raw = import_public(document)
    else:
        raise MessageCryptoError("public key alg has no fingerprint")
    return hashlib.sha256(raw).hexdigest()[:FINGERPRINT_HEX_DIGITS].upper()


def kind(document: dict) -> str:
    """How the fingerprint was made, in a few words for the screen."""
    if isinstance(document, dict) and document.get("alg") in PGP_PUBLIC_ALGS:
        return "OpenPGP fingerprint"
    return "SHA-256 fingerprint"


def format_fingerprint(digits: str) -> str:
    """Ten groups of four, with two spaces in the middle, as gpg prints it."""
    clean = digits.replace(" ", "").upper()
    if len(clean) != FINGERPRINT_HEX_DIGITS:
        raise MessageCryptoError("a fingerprint has 40 hex digits")
    groups = [clean[i:i + 4] for i in range(0, FINGERPRINT_HEX_DIGITS, 4)]
    return " ".join(groups[:5]) + "  " + " ".join(groups[5:])


def screen_lines(digits: str) -> str:
    """The same groups as format_fingerprint, five to a line, for a narrow screen."""
    first, second = format_fingerprint(digits).split("  ")
    return first + "\n" + second


def short_fingerprint(digits: str) -> str:
    """The first two groups, for labels in a key list."""
    clean = digits.replace(" ", "").upper()
    return clean[:4] + " " + clean[4:SHORT_HEX_DIGITS]
