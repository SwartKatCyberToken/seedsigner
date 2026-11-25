"""Which keys a message screen is allowed to offer.

Does not draw and does not derive keys. Encrypt and verify use someone
else's public key, so a loaded seed is not required. Sign and decrypt use
the private key from a loaded BIP-39 seed. View Public Key can show either.
"""

from seedsigner.message_crypto.codec import dumps, same_key_type
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.fingerprint import fingerprint, short_fingerprint
from seedsigner.message_crypto.flow import (
    ACTION_DECRYPT,
    ACTION_ENCRYPT,
    ACTION_PUBLIC,
    ACTION_SIGN,
    ACTION_VERIFY,
)
from seedsigner.message_crypto.preloaded import preloaded_entries

ROLE_OWN = "Own (Seed)"
ROLE_IMPORTED = "Contact (imported)"
ROLE_PRELOADED = "Contact (preloaded)"

_TITLES = {
    ACTION_ENCRYPT: "Their public key",
    ACTION_VERIFY: "Signer public key",
    ACTION_SIGN: "Your signing key",
    ACTION_DECRYPT: "Your decryption key",
    ACTION_PUBLIC: "Public key",
}
_BLOCKED = {
    ACTION_SIGN: "Signing uses your private key. Load a BIP-39 seed from the Seeds menu.",
    ACTION_DECRYPT: "Decrypting uses your private key. Load a BIP-39 seed from the Seeds menu.",
}


def choices_for(action: str, alg: str | None, own: list, imported: list) -> dict:
    """Build the key list for one screen.

    own is a list of {seed, fingerprint}. imported is a list of public-key
    envelopes already scanned or typed in this session. Preloaded keys are
    read from the INI file here so they appear in the same list.
    """
    entries = []
    if action in (ACTION_SIGN, ACTION_DECRYPT, ACTION_PUBLIC):
        for item in own:
            entries.append({
                "role": ROLE_OWN,
                "label": f"{ROLE_OWN} {item['fingerprint']}",
                "seed": item["seed"],
                "document": None,
            })
    contacts = _contacts(alg, imported)
    if action in (ACTION_ENCRYPT, ACTION_VERIFY, ACTION_PUBLIC):
        entries.extend(contacts)
    blocked = None
    if action in (ACTION_SIGN, ACTION_DECRYPT) and not any(item["role"] == ROLE_OWN for item in entries):
        blocked = _BLOCKED[action]
    return {
        "title": _TITLES[action],
        "entries": entries,
        "blocked": blocked,
        "allow_other": action in (ACTION_ENCRYPT, ACTION_VERIFY, ACTION_PUBLIC),
    }


def remember_contact(contacts: list, document: dict) -> list:
    """Return contacts with document appended when it is not already there."""
    found = list(contacts or [])
    if any(dumps(item) == dumps(document) for item in found):
        return found
    found.append(document)
    return found


def _contacts(alg: str | None, imported: list) -> list:
    preloaded = preloaded_entries(alg)
    known = {dumps(item["document"]) for item in preloaded}
    entries = []
    for document in imported or []:
        if alg is not None and not same_key_type(document.get("alg"), alg):
            continue
        if dumps(document) in known:
            continue
        entries.append({
            "role": ROLE_IMPORTED,
            "label": f"{ROLE_IMPORTED} {_short_label(document)}",
            "seed": None,
            "document": document,
        })
    for item in preloaded:
        entries.append({
            "role": ROLE_PRELOADED,
            "label": f"{ROLE_PRELOADED} {item['label']}",
            "seed": None,
            "document": item["document"],
        })
    return entries


def _short_label(document: dict) -> str:
    """The start of the key's fingerprint, so the label matches what gets compared."""
    try:
        return short_fingerprint(fingerprint(document))
    except MessageCryptoError:
        return "(unreadable key)"
