# Message key derivation v1

Scheme id: `seedsigner-msg/1`

This is the recovery contract for the message-cryptography extension. Bitcoin
BIP-32 derivation is not used and is not modified. Changing the salt, a
label, or an output length creates different keys and requires a new scheme
id plus envelope version. Do not edit the v1 constants in place.

## Seed

The input keying material is the 64-byte BIP-39 seed: the output of
`mnemonic_to_seed`, including the BIP-39 passphrase when one is set. It is
the same `Seed.seed_bytes` value SeedSigner already computes. Electrum seeds
are rejected.

A BIP-39 passphrase changes this seed, and therefore every message key.

## KDF

HKDF-SHA256 (RFC 5869):

| Input | Value |
| --- | --- |
| salt | ASCII `seedsigner-msg/1` |
| info | the label below, as ASCII bytes |
| length | the length in the table |

| Label | Length | Consumer |
| --- | --- | --- |
| `rsa-sign` | 32 | HMAC-SHA256 counter stream for `RSA.generate` (signing key) |
| `rsa-encrypt` | 32 | HMAC-SHA256 counter stream for `RSA.generate` (encryption key) |
| `ml-dsa-44` | 32 | `ML_DSA_44.key_derive` seed (`xi`) |
| `ml-kem-512` | 64 | `ML_KEM_512.key_derive` seed (`d` then `z`) |

The RSA stream key is not the bytes returned to `RSA.generate`. Each request
for `n` bytes takes the next bytes of:

```text
block_i = HMAC-SHA256(stream_key, uint64be(i))   for i = 0, 1, 2, ...
```

One stream object is used for one `RSA.generate` call. It is not used for
signature salts, encapsulation coins, or AES nonces. Those stay random.

Device RSA keys are 2048 bits with public exponent 65537. The test suite also
accepts 1024-bit keys so generation stays short. 1024-bit keys are not the
device profile.

## Algorithms

| Purpose | Algorithm | Randomness |
| --- | --- | --- |
| RSA signature | RSASSA-PSS with SHA-256 | random PSS salt |
| RSA encryption | RSA-OAEP SHA-256 wraps a 32-byte AES key; AES-256-GCM encrypts the message | OS random AES key and 12-byte nonce |
| ML-DSA-44 signature | `dilithium-py` `key_derive`, then `sign(..., deterministic=True)` | none; context is ASCII `seedsigner-msg/1` |
| ML-KEM-512 encryption | `kyber-py` `key_derive`, then `encaps`; the 32-byte shared secret is the AES-256 key | encapsulation coins stay inside kyber-py; AES nonce is OS random |

AES-GCM additional data is ASCII `seedsigner-msg/1 enc-rsa` or
`seedsigner-msg/1 enc-kem`. There is no second KDF on the ML-KEM shared
secret. Adding one would be a new envelope version.

`dilithium-py` and `kyber-py` are learning implementations. They are the
prototypes named in the project README, not a production cryptography choice.
PyCryptodome supplies RSA.

Signed and encrypted message bytes are the UTF-8 encoding of the confirmed
text, with no Unicode normalization. The review screen states that byte count.

## Envelopes

One JSON object, version `1`, compact encoding with sorted keys. Unknown
fields and unknown `op` values are rejected.

| `op` | Role |
| --- | --- |
| `text` | Plaintext QR: `msg` |
| `pub` | Public key. `alg` is `rsa-sign`, `rsa-encrypt`, `ml-dsa-44`, `ml-kem-512`, `pgp-rsa-encrypt`, or `pgp-rsa-sign`. The two PGP values are interchangeable and only record which step the key was entered for |
| `enc-rsa` | Hybrid ciphertext. `ek` is the RSA-OAEP wrapped AES key |
| `enc-kem` | Hybrid ciphertext. `ek` is the ML-KEM ciphertext, not the public key |
| `enc-pgp` | OpenPGP ciphertext in `armor` |
| `sig-rsa` | RSA-PSS signature and `msg` |
| `sig-dsa` | ML-DSA signature and `msg` |
| `sig-pgp` | OpenPGP cleartext signed block in `armor`, plus `msg` |

PGP uses the same seed RSA keys as `rsa-encrypt` and `rsa-sign`, exported as
one OpenPGP key, as other PGP apps make them: the `rsa-sign` key is the
primary key (certify and sign), and the `rsa-encrypt` key is its subkey
(encrypt). Each key keeps its own fingerprint, because a fingerprint covers
only the key and its creation time. The creation time, and the date of every
self-signature, is 2026-01-01 UTC, so one seed always exports the same armor.
ML-DSA-44 and ML-KEM-512 are not wrapped as OpenPGP keys. PGPy cannot carry
them, and pysequoia will not accept these already-derived keys.

QR transport splits that JSON into frames:

```text
ssmsg1 {index}of{count} {chunk}
```

`index` is 1-based. The **QR code density** setting caps each chunk at 45 (Low), 90 (Medium, the
default) or 180 (High) characters. Decoders accept any chunk size.

## Test vector

BIP-39 mnemonic `abandon` eleven times, then `about`, empty passphrase.

BIP-39 seed:

```text
5eb00bbddcf069084889a8ab9155568165f5c453ccb85e70811aaed6f6da5fc19a5ac40b389cd370d086206dec8aa6c43daea6690f20ad3d8d48b2d2ce9e38e4
```

HKDF output for label `ml-dsa-44` (32 bytes):

```text
36806ed8d19a3d562aa583aee2087cf16676e5dc757baa82391427c55508abc4
```
