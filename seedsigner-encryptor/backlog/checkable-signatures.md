# Signatures with only one valid value

## Problem

A compromised device can hide data in any output where more than one value would be accepted. Nobody can tell a clean random-looking value from one that carries seed bits. A signature can only be checked for hidden data if exactly one valid signature exists for a given key and message. Today:

| Signature | Where | Only one valid value? |
| --- | --- | --- |
| Custom RSA (`sig-rsa`) | `rsa_ops.sign`: `pss.new(private_key).sign(digest)` | **No.** RSA-PSS uses a random salt, which can carry hidden data. |
| PGP (`sig-pgp`) | `pgp_ops.sign`: RSA PKCS#1 v1.5 over the message and the signature's hashed packets | **Almost.** PKCS#1 v1.5 has one value per input, but the hashed packets include `created=_signature_time()`, which is the current time. The Pi has no battery clock, so that time is close to meaningless, and a compromised device could pick it freely to hide bits. |
| ML-DSA-44 (`sig-dsa`) | `ml_dsa_ops.sign` with `deterministic=True` | **Only for someone with the seed.** The verifier accepts any valid signature, randomised ones included, so an outside checker can't tell. A second device or `test-data/check-helper.py` with the same seed can recompute it and compare byte for byte. |
| Encryption (all) | `enc-rsa`, `enc-kem`, `enc-pgp` | **No, by design.** Encryption has to be random. Leave as is and say so in the docs. |

## Done when

1. **Custom RSA signing** uses PKCS#1 v1.5 (`Crypto.Signature.pkcs1_15`) instead of PSS. Or `sig-rsa` is retired in favour of PGP, which already uses v1.5.
   - This changes the `sig-rsa` wire format. Decide whether old PSS signatures should still verify. If so, `verify` tries v1.5 first and falls back to PSS, and the docs say only v1.5 signatures can be checked for hidden data.
2. **PGP signatures** have a signature time that the device doesn't choose freely. Options:
   - always `KEY_CREATED`,
   - a value derived from the message,
   - a date the user types in and can see on screen.
   - Also check that every other hashed packet PGPy writes is fixed. That's the issuer fingerprint and key ID, the hash algorithm, and anything PGPy adds by default.
3. **A test per signature type** proves determinism: same seed and message, two runs, identical bytes.
4. **Docs:** `seedsigner/docs/message_key_derivation.md` and the README say which outputs can be checked from outside and which can't.

## Open questions

- Does a fixed PGP signature time upset other apps? SHAP (OpenPGP.js) and gpg verify signatures older than "now" without complaint, but test it. The signature time must not be before the key's creation time, which is why `_signature_time` exists.
- Should ML-DSA stay? It can be checked by a second seed holder but not by a tap. That may be acceptable, because the post-quantum option is there for the future, not for this check.
