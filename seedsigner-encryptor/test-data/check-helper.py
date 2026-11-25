"""Check what a Pi shows for the test seed, from a PC.

    python test-data/check-helper.py expected "hello pi"
    python test-data/check-helper.py verify frames.txt

expected prints the start and end of each public key the Pi's View Public
Key text screen shows, each key's fingerprint as View Public Key -> Fingerprint
shows it, plus the ML-DSA-44 signature for the message. ML-DSA
signing here is deterministic, so the Pi produces the same signature for the
same text. RSA-PSS and PGP signatures change on every run and cannot be
compared this way; use verify for those.

verify reads a file of ssmsg1 frame lines (one per line, any order, as a
phone QR reader shows them) or one JSON envelope, then checks the signature
against the test seed's public key. Lines that start with # are skipped.

Uses seedsigner.message_crypto with testseed.txt. Device RSA size is 2048
bits, so RSA keys match a Pi that loaded the same mnemonic.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "seedsigner" / "src"))

from embit import bip39  # noqa: E402

from seedsigner.message_crypto.codec import (  # noqa: E402
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    OP_SIG_DSA,
    OP_SIG_PGP,
    OP_SIG_RSA,
    parse_document,
)
from seedsigner.message_crypto.fingerprint import fingerprint, format_fingerprint  # noqa: E402
from seedsigner.message_crypto.keys import keys_for_seed  # noqa: E402
from seedsigner.message_crypto.operations import export_public, sign_with, verify_with  # noqa: E402
from seedsigner.message_crypto.qr_codec import QrAssembly  # noqa: E402

_EDGE = 16
_KEY_FIELDS = (
    (ALG_RSA_SIGN, "n"),
    (ALG_RSA_ENCRYPT, "n"),
    (ALG_ML_DSA, "pk"),
    (ALG_ML_KEM, "ek"),
)
_SIGNER_ALG = {OP_SIG_RSA: ALG_RSA_SIGN, OP_SIG_DSA: ALG_ML_DSA, OP_SIG_PGP: ALG_PGP_SIGN}


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "expected":
        expected(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify(Path(sys.argv[2]))
    else:
        raise SystemExit(
            "usage: python test-data/check-helper.py expected <message>\n"
            "       python test-data/check-helper.py verify <frames-or-envelope-file>"
        )


def expected(message: str) -> None:
    keys = _test_keys()
    print("Public keys (View Public Key -> Show text). Compare the start and end:")
    for alg, field in _KEY_FIELDS:
        value = export_public(keys, alg)[field]
        print(f"  {alg:12} {field:2} {_edges(value)}  ({len(value)} chars)")
    print()
    print("Fingerprints (View Public Key -> Fingerprint):")
    for alg in (ALG_PGP_SIGN, ALG_RSA_SIGN, ALG_RSA_ENCRYPT, ALG_ML_DSA, ALG_ML_KEM):
        label = "pgp" if alg == ALG_PGP_SIGN else alg
        print(f"  {label:12} {format_fingerprint(fingerprint(export_public(keys, alg)))}")
    signed = sign_with(keys, ALG_ML_DSA, message)
    print()
    print(f"ML-DSA-44 signature of {message!r} ({len(message.encode('utf-8'))} UTF-8 bytes):")
    print(f"  sig {_edges(signed['sig'])}  ({len(signed['sig'])} chars)")
    print("The Pi shows this only inside the QR. Read it with a phone and run verify,")
    print("or compare the first frame's text with the start of the sig above.")


def verify(path: Path) -> None:
    lines = [
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    payload = _assemble(lines)
    envelope = parse_document(payload)
    alg = _SIGNER_ALG.get(envelope["op"])
    if alg is None:
        raise SystemExit(f"envelope op {envelope['op']} is not a signature")
    peer = export_public(_test_keys(), alg)
    valid = verify_with(peer, envelope)
    print(f"message: {envelope['msg']!r}")
    print(f"algorithm: {alg}")
    print("VALID signature from the test seed" if valid else "INVALID signature")
    if not valid:
        raise SystemExit(1)


def _assemble(lines: list) -> str:
    if not lines:
        raise SystemExit("file is empty")
    if not lines[0].startswith("ssmsg1 "):
        return "".join(lines)
    assembly = QrAssembly()
    for line in lines:
        state = assembly.add(line)
        if state == "invalid":
            raise SystemExit(f"not an ssmsg1 frame: {line[:40]}")
    if assembly.payload is None:
        missing = [str(i + 1) for i, part in enumerate(assembly._parts) if part is None]
        raise SystemExit(f"missing frame(s) {', '.join(missing)} of {assembly.total}")
    return assembly.payload


def _test_keys():
    mnemonic = " ".join(HERE.joinpath("testseed.txt").read_text(encoding="utf-8").split())
    return keys_for_seed(bip39.mnemonic_to_seed(mnemonic, password=""))


def _edges(value: str) -> str:
    return f"{value[:_EDGE]} ... {value[-_EDGE:]}"


if __name__ == "__main__":
    main()
