"""Paste device public keys into seedsigner/preloaded-public-keys.ini.

Does not generate keys and does not read testseed.txt. On the device, open
Messages, View Public Key, choose the seed and the algorithm, then Show text.
Copy that text into the prompt here. A line that is only a period ends the paste,
so a PGP armor block can include its blank line.

Run from seedsigner/ with PYTHONPATH=src, or from the repo root:

    python seedsigner/tools/preload_pub_keys.py
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from seedsigner.message_crypto.errors import MessageCryptoError  # noqa: E402
from seedsigner.message_crypto.preloaded import (  # noqa: E402
    append_preloaded,
    config_path,
    document_from_paste,
)

_PROMPTS = (
    ("rsa-encrypt", "RSA encryption"),
    ("rsa-sign", "RSA signing"),
    ("ml-kem-512", "ML-KEM"),
    ("ml-dsa-44", "ML-DSA"),
    ("pgp-rsa-sign", "PGP (one key for encrypting and verifying)"),
)


def main() -> None:
    path = config_path()
    print(f"Preloaded keys file: {path}")
    print("Answer y to add a key. Paste the public key, then a line with only a period.")
    for alg, title in _PROMPTS:
        while True:
            answer = input(f"Add a {title} key? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                break
            label = input("Label: ").strip() or title
            print("Paste the public key JSON or PGP armor. End with a line that is only a period.")
            lines = []
            while True:
                line = input()
                if line.strip() == ".":
                    break
                lines.append(line)
            try:
                document = document_from_paste(alg, "\n".join(lines))
                section = append_preloaded(path, alg, label, document)
            except MessageCryptoError as exc:
                print(exc)
                continue
            print(f"Saved {section}")


if __name__ == "__main__":
    main()
