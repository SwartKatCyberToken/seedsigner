"""Public keys the message menu can offer from an INI file.

Does not derive keys. test-data/testhelper.py and
seedsigner/tools/preload_pub_keys.py write seedsigner/preloaded-public-keys.ini.
The file is INI, not TOML, so the Python 3.10 image on the Pi can read it
without tomllib. A section name is an algorithm, or that algorithm plus
`.2`, `.3`, and so on when there is more than one key. `label` is the name
shown in the list. `document` is one JSON public-key envelope.

Set SEEDSIGNER_PRELOADED_KEYS to point at a different file. A missing file
means there is no preloaded key.
"""

import configparser
import os
from pathlib import Path

from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    OP_PUB,
    dumps,
    parse_document,
    same_key_type,
)
from seedsigner.message_crypto.errors import MessageCryptoError

_ALGS = (
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    ALG_ML_DSA,
    ALG_ML_KEM,
)


def config_path() -> Path:
    override = os.environ.get("SEEDSIGNER_PRELOADED_KEYS")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "preloaded-public-keys.ini"


def section_alg(section: str) -> str | None:
    """Return the algorithm a section stores, or None when the name is unknown."""
    for alg in sorted(_ALGS, key=len, reverse=True):
        if section == alg or section.startswith(alg + "."):
            return alg
    return None


def preloaded_entries(alg: str | None = None) -> list:
    """Return {section, label, alg, document} for each saved public key."""
    path = config_path()
    if not path.is_file():
        return []
    parser = _parser()
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise MessageCryptoError("saved public key file could not be read") from exc
    entries = []
    for section in parser.sections():
        found = section_alg(section)
        if found is None or (alg is not None and not same_key_type(found, alg)):
            continue
        if not parser.has_option(section, "document"):
            continue
        label = parser.get(section, "label", fallback="").strip() or section
        entries.append({
            "section": section,
            "label": label,
            "alg": found,
            "document": parse_document(parser.get(section, "document")),
        })
    return entries


def preloaded_for(alg: str) -> dict | None:
    """Return the first saved public-key envelope for alg, or None."""
    entries = preloaded_entries(alg)
    if not entries:
        return None
    return entries[0]["document"]


def append_preloaded(path: Path, alg: str, label: str, document: dict) -> str:
    """Add one public key and return the section name that was written."""
    if section_alg(alg) != alg:
        raise MessageCryptoError(f"unknown public key alg {alg}")
    if not isinstance(label, str) or label.strip() == "" or "\n" in label or "]" in label:
        raise MessageCryptoError("key label must be one line")
    if document.get("alg") != alg or document.get("op") != OP_PUB:
        raise MessageCryptoError("document alg does not match the section")
    parser = _parser()
    if path.is_file():
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error as exc:
            raise MessageCryptoError("saved public key file could not be read") from exc
    section = _next_section(parser.sections(), alg)
    parser.add_section(section)
    parser.set(section, "label", label.strip())
    parser.set(section, "document", dumps(document))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    return section


def document_from_paste(alg: str, text: str) -> dict:
    """Read a pasted public-key JSON envelope or a PGP armor block."""
    from seedsigner.message_crypto.sanitize import WANT_PUB, parse_input

    if not isinstance(text, str) or text.strip() == "":
        raise MessageCryptoError("pasted public key is empty")
    document = parse_input(text, WANT_PUB, alg)
    if document.get("op") != OP_PUB or document.get("alg") != alg:
        raise MessageCryptoError("pasted key is not a public key for this algorithm")
    return document


def _parser() -> configparser.ConfigParser:
    return configparser.ConfigParser(interpolation=None)


def _next_section(sections: list, alg: str) -> str:
    if alg not in sections:
        return alg
    number = 2
    while f"{alg}.{number}" in sections:
        number += 1
    return f"{alg}.{number}"
