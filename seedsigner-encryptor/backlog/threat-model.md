# Decide which attack comes first

## Problem

The air gap has to defend against two different attacks, and they call for different work:

| Attack | Example | What helps |
| --- | --- | --- |
| **Infiltration:** bad data gets in | A crafted QR code or relay message exploits a bug in the device's parser and takes over the device | Less to parse. The relay (one contact per direction, or seven on the 7-segment build, with numbered packets and CRCs) is far less to attack than a camera plus an image decoder. Strict input checks, already in `sanitize.py` and `codec.py`. |
| **Exfiltration:** secrets get out | A compromised device hides seed bits in a signature or ciphertext, or in screen flicker while a QR code is shown | Removing hidden side channels (the relay does this). Outputs that have only one valid value ([checkable-signatures.md](checkable-signatures.md)). An independent checker on the line ([relay-verifier-tap.md](relay-verifier-tap.md)). |

The relay already helps against both. What's left differs:
- Against infiltration, the remaining work is mostly hardening the parsers.
- Against exfiltration, the remaining work is the checkable-outputs work.

## Decision needed

Which attack does the project defend against first, and which kind of user is it for:
- an engineer who can read the code and the hex, or
- someone who can only compare fingerprints and read text on a screen?

Write the answer in the project README's threat model, and reorder [README.md](README.md) to match.

## Notes

- A compromised device can always hide a few bits inside a random-looking output, such as ciphertext, an RSA-PSS signature, or an encrypted key exchange. No channel prevents that. Only outputs with a single valid value can be checked from outside.
- Bitcoin hardware wallets face the same problem with ECDSA nonces. Their answer is the "anti-exfil" (anti-klepto) protocol, used by Blockstream Jade and BitBox02. It's worth reading before designing the signature checks here.
