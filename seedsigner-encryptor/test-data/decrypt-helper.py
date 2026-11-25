"""Decrypt a message that was encrypted to the test seed's public keys.

    python test-data/decrypt-helper.py test-data/ml-kem/test-signed-message.txt

Calls seedsigner.message_crypto with testseed.txt. It does not read the
priv files. Lines that start with # are comments. The remaining text is one
JSON envelope: enc-rsa, enc-kem, or enc-pgp.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "seedsigner" / "src"))

from embit import bip39  # noqa: E402

from seedsigner.message_crypto.codec import parse_document  # noqa: E402
from seedsigner.message_crypto.keys import keys_for_seed  # noqa: E402
from seedsigner.message_crypto.operations import decrypt_with  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python test-data/decrypt-helper.py <envelope>")
    payload = "\n".join(
        line for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )
    mnemonic = " ".join(HERE.joinpath("testseed.txt").read_text(encoding="utf-8").split())
    keys = keys_for_seed(bip39.mnemonic_to_seed(mnemonic, password=""))
    print(decrypt_with(keys, parse_document(payload)))


if __name__ == "__main__":
    main()
