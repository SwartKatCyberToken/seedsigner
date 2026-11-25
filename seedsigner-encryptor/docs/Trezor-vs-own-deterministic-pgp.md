# Trezor vs our own deterministic PGP/RSA keys

**Question:** Was it right to make our own change, feeding seed-derived randomness into RSA and PGP key generation? Trezor, with many more eyes on its code, already does "keys from a seed phrase".

**Short answer:** Trezor solved a different, easier problem. It never derives RSA keys from a seed. Every seed-derived key it has (Bitcoin, U2F, FIDO2, and GPG through trezor-agent) is an elliptic-curve key, where "deterministic" just means "use the derived bytes as the private key". RSA has no equivalent: you have to search for primes, so the result depends on exactly how the search is done.

Our approach is a known pattern: HKDF, then an HMAC stream passed in as `randfunc`, then the library's standard `RSA.generate`. We did not modify any algorithm. The real weakness is narrower: our RSA keys depend on PyCryptodome's internal prime-search code staying the same forever. A public spec now exists for exactly this job (C2SP `det-keygen`), and it removes that dependency.

Nothing in the code was changed for this research.

---

## 1. What our code actually does

The files are in [seedsigner/src/seedsigner/message_crypto/](seedsigner/src/seedsigner/message_crypto/).

| Key | How it is made | Is that a "modification"? |
| --- | --- | --- |
| RSA sign / RSA encrypt (2048) | `HKDF-SHA256(BIP-39 seed, salt "seedsigner-msg/1", info "rsa-sign" / "rsa-encrypt")` gives a 32-byte key. `HmacSha256Counter` turns it into a byte stream, which `Crypto.PublicKey.RSA.generate(2048, randfunc=stream, e=65537)` uses. See [derivation.py](seedsigner/src/seedsigner/message_crypto/derivation.py) and [rsa_ops.py](seedsigner/src/seedsigner/message_crypto/rsa_ops.py). | No. `randfunc` is PyCryptodome's public, documented parameter. The RSA algorithm is unchanged; only its random source differs. |
| PGP | The same two RSA keys, wrapped by PGPy 0.6.0 with a fixed creation time (2026-01-01), so the fingerprint is stable. See [pgp_ops.py](seedsigner/src/seedsigner/message_crypto/pgp_ops.py). | No. PGPy only packages keys that already exist. |
| ML-DSA-44 | A 32-byte HKDF output goes into `ML_DSA_44.key_derive(seed)` ([ml_dsa_ops.py](seedsigner/src/seedsigner/message_crypto/ml_dsa_ops.py)). | No. Seeded key generation (`ξ`) is part of FIPS 204 itself. |
| ML-KEM-512 | A 64-byte HKDF output (`d‖z`) goes into `ML_KEM_512.key_derive(seed)` ([ml_kem_ops.py](seedsigner/src/seedsigner/message_crypto/ml_kem_ops.py)). | No. Seeded key generation is part of FIPS 203 itself. |
| Signing salts, AES keys, nonces, KEM encapsulation | OS RNG (`get_random_bytes`) | Correct. Only key *generation* is deterministic. |

ML-DSA and ML-KEM already follow the standard exactly: their specifications define key generation from a seed. **The only real design question is RSA (and therefore PGP).**

---

## 2. What Trezor does

### 2.1 U2F and FIDO2 (inside the firmware)

Sources: [legacy/firmware/u2f.c](https://github.com/trezor/trezor-firmware/blob/main/legacy/firmware/u2f.c), [legacy/firmware/config.c](https://github.com/trezor/trezor-firmware/blob/main/legacy/firmware/config.c), [core/src/apps/webauthn/fido2.py](https://github.com/trezor/trezor-firmware/blob/main/core/src/apps/webauthn/fido2.py), [core/src/apps/webauthn/credential.py](https://github.com/trezor/trezor-firmware/blob/main/core/src/apps/webauthn/credential.py), [SLIP-0021](https://github.com/satoshilabs/slips/blob/master/slip-0021.md)

- **U2F (Trezor T/Safe):** root path `m/0x80553246'`, which spells "U2F" in ASCII. For each registration the firmware picks **8 random hardened indexes**, derives the NIST P-256 key at `m/"U2F"'/r1'/…/r8'`, and returns a key handle = `path ‖ HMAC-SHA256(node.private_key, rp_id_hash ‖ path)`. The website stores the handle. After a restore, the same seed plus that handle gives the same key again.
- **U2F (Trezor One):** same idea. `config_compute_u2froot` runs `mnemonic_to_seed(mnemonic, "")` (empty passphrase) and derives a P-256 node, which is cached in storage.
- **FIDO2:** keys are at `m/10022'/…`, with the path taken from the credential ID. The credential ID is encrypted with ChaCha20-Poly1305 using a [SLIP-0021](https://github.com/satoshilabs/slips/blob/master/slip-0021.md) key derived from the seed (labels `"SLIP-0022"`, `"Encryption key"`). Keys survive a restore because they come from the seed and the ID.
- **Algorithms:** ES256 (P-256) and EdDSA (Ed25519) only. **There is no RSA anywhere in the firmware:** no `rsa.c` in `crypto/`, and none in the WebAuthn app.
- Domain separation uses distinct BIP-32 purpose numbers (`"U2F"'`, `10022'`) and SLIP-0021 string labels. This is the same idea as our HKDF `info` labels.

### 2.2 GPG (trezor-agent, separate host software)

Sources: [doc/README-GPG.md](https://github.com/romanz/trezor-agent/blob/master/doc/README-GPG.md), [doc/DESIGN.md](https://github.com/romanz/trezor-agent/blob/master/doc/DESIGN.md), `libagent/gpg/*.py`, `libagent/device/interface.py` and `trezor.py` in [romanz/trezor-agent](https://github.com/romanz/trezor-agent), [SLIP-0013](https://github.com/satoshilabs/slips/blob/master/slip-0013.md), [SLIP-0017](https://github.com/satoshilabs/slips/blob/master/slip-0017.md)

- **Algorithms:** the signing primary is NIST P-256 (default) or Ed25519. The encryption subkey is ECDH on P-256 or Curve25519. **The device generates no RSA key.** RSA only appears in a mode where a Trezor subkey is added to an existing software RSA primary key.
- **Derivation (SLIP-0013):** `digest = SHA256(uint32le(0) ‖ "gpg://<user id>")`. The first 16 bytes give four integers A, B, C, D. The signing key is at `m/13'/A'/B'/C'/D'`, and the ECDH key at `m/17'/A'/B'/C'/D'` (SLIP-0017). So the **user ID string is part of the key**: a different spelling gives a different key.
- **The private key never leaves the device.** The host builds the OpenPGP packets and hashes them; the device signs the digest or performs ECDH, after the user confirms on screen.
- **Timestamp:** the creation time is hashed into the fingerprint. trezor-agent defaults `--time` to 0 and tells you to remember it to regenerate the same key. Our fixed `KEY_CREATED` solves the same problem in the same way.
- **Passphrase:** a hidden-wallet passphrase changes the root and therefore every GPG key. Ours behaves the same, because `Seed.seed_bytes` already includes the BIP-39 passphrase.
- **Status:** the project itself says *"This GPG tool is still in EXPERIMENTAL mode … API and features may change without backwards compatibility"* and *"the GPG-related code is still under development"*. No audit is claimed. Many people review the Trezor *firmware*; trezor-agent's GPG mode is a smaller, separate project.

### 2.3 Why Trezor can avoid our problem

For an elliptic-curve key, the private key *is* a 32-byte number. BIP-32/SLIP-10 gives you 32 bytes, and you're done. No library's internal behaviour is involved. Any implementation that follows the SLIP gets the same key.

For RSA you must **find** two large primes. "Same seed gives same key" holds only if the whole search is fixed: how candidates are drawn from the stream, how many bytes each attempt uses, sieving filters, retry conditions, and whether Miller-Rabin bases come from the same stream. Trezor avoided this by not doing RSA.

---

## 3. Others who *do* derive RSA from a seed

### 3.1 Ledger OpenPGP app, "seed mode"

Source: [GPG Card Add-on Developer Guide, §3.1.1](https://openpgp.apps.ledger.com/gpgcard-addon.html)

- `Sn = BIP32_derive(/0x80475047'/n')` (the index spells "GPG"), then `Sk[i] = SHAKE256(SHA256("kdf2" | Sn | key_name | int16(i) | int8(len(ctx)) | ctx), length)`. Here `key_name` is `sig `, `dec ` or `aut `, and `ctx` holds the algorithm and modulus size.
- RSA: two seeds `Sp`, `Sq`, each half the key size. Set the top two bits, then `p = next_prime(Sp)`, `q = next_prime(Sq)`, `n = p·q`.
- This is the same shape as ours: seed, then KDF with labels, then prime search. Ledger wrote its own fixed prime search instead of passing a stream to a general library.
- The same page has a warning about an older derivation: **"A legacy RSA key can be factored from its public key alone."** The page we read doesn't say what the flaw was. It is real evidence that hand-made deterministic RSA can go badly wrong, even at a hardware-wallet vendor.

### 3.2 C2SP `det-keygen` (the spec built for this)

Sources: [c2sp.org/det-keygen](https://github.com/C2SP/C2SP/blob/main/det-keygen.md), Go implementation [filippo.io/keygen](https://pkg.go.dev/filippo.io/keygen) (v1.0.0, ISC)

- Purpose: *"a deterministic … seed-based key generation process for ECDSA and RSA"*, compliant with FIPS 186-5 (Appendix A.1.3) and SP 800-90A HMAC_DRBG, with test vectors in the [C2SP repo](https://github.com/C2SP/C2SP/tree/main/det-keygen).
- RSA steps:
  1. Set up HMAC_DRBG (SHA-256) with the seed and personalization `"det RSA key gen" ‖ uint16(bits)`.
  2. Each candidate is `bits/16` bytes of DRBG output, with the top two bits and the low three bits set.
  3. Test each candidate with trial division by primes up to 1619, then 3–5 Miller-Rabin rounds. If it isn't prime, update the DRBG and draw again.
  4. Reject the pair if `gcd(p−1, q−1) ≥ 2³²`.
  5. Compute `d` modulo λ (Carmichael), with `e = 65537`.
- Seed: at least 128 bits, *should* be 192 or more. FIPS compliance needs 168 bits for RSA-2048.
- Miller-Rabin bases are "randomly-selected" and the spec doesn't say where they come from. That's fine: they only decide prime vs. not prime, which has the same answer except with negligible probability. So they don't affect which key you get.
- The key point: **the output is defined by the spec, not by one library's code.** Anyone (Go, Python, or the user in 20 years) can reproduce the key from the seed and check it against the published vectors.

### 3.3 Keyfork (Distrust)

Source: [git.distrust.co/public/keyfork](https://git.distrust.co/public/keyfork). The site blocked automated reading, so this section only covers what search results showed.

- An offline toolchain that derives OpenPGP and other keys from a BIP-39 mnemonic (`keyfork derive openpgp`). It mentions audits by NCC and Cure53.
- **Not verified:** which OpenPGP algorithms it uses (probably Ed25519/Cv25519 rather than RSA) and its derivation path. Read the repo directly before relying on it.

---

## 4. Comparison

| | Our code | trezor-agent GPG | Ledger seed mode | C2SP det-keygen |
| --- | --- | --- | --- | --- |
| Key type | RSA-2048 (+ ML-DSA/ML-KEM) | P-256 / Ed25519 + ECDH | RSA and ECC | RSA and ECDSA |
| Seed to key material | HKDF-SHA256, labelled | SLIP-0013/17 BIP-32 path from a hash of the user ID | BIP-32 + SHAKE256 KDF, labelled | caller supplies the seed |
| How the RSA prime search is fixed | **by PyCryptodome 4.2.0's internal code** | n/a (no RSA) | Ledger's own `next_prime` | **by the spec** |
| Can someone reproduce it without our code? | Only with the exact PyCryptodome version | Yes (SLIP specs) | Partly (prime test not published) | Yes (spec + test vectors) |
| Known-answer test in repo | ML-DSA yes; **RSA no** (only "same twice in one run") | — | — | published vectors |
| Fixed creation time for the PGP fingerprint | yes (2026-01-01) | yes (`--time`, default 0) | n/a (card) | n/a |
| Passphrase changes keys | yes | yes | n/a | n/a |
| Private key leaves the device | No (stays on the SeedSigner, in RAM) | No | No | n/a |
| Review status | ours only | "experimental", no audit claimed | vendor; one past RSA derivation flaw | public spec, FIPS-aligned |

---

## 5. Assessment

**What is fine:**

- No algorithm was modified. We pass a stream through a public library parameter, which is the approach PyCryptodome's docs allow and the approach the `pgp-options.md` notes recommended.
- HKDF with distinct labels, one stream per key, and the OS RNG for everything else is sound. It mirrors Trezor's SLIP-0021 labels and Ledger's `key_name` labels.
- The HMAC counter stream is secure as a pseudorandom generator: HMAC-SHA256 under a secret key is a PRF. Prime quality doesn't need anything more than that.
- ML-DSA and ML-KEM follow their FIPS seeded key generation exactly.
- The fixed PGP timestamp is the same approach trezor-agent uses.

**The real risk is recoverability, not secrecy.**

- `RSA.generate` in PyCryptodome uses the stream for prime candidates (`Integer.random`) **and** for Miller-Rabin bases (`miller_rabin_test` with the same `randfunc`), through filters and loop conditions in `RSA.py` and `Primality.py`. Any change in a future release changes the key a seed produces. Examples: a different sieve, a different Miller-Rabin round count, a different byte order in `Integer.random`, or a different `p`/`q` distance check.
- Nothing would fail loudly. The current test ([test_message_crypto.py:95](seedsigner/tests/test_message_crypto.py#L95)) checks that the same seed gives the same key twice in one run, which stays true after such a change. Users would silently get a *different* RSA/PGP identity after an upgrade, and old messages to their old public key couldn't be decrypted from the seed.
- This is exactly the problem `det-keygen` exists to solve. Trezor never faced it because it doesn't do RSA.

**Entropy note (applies to everyone):** a 12-word mnemonic carries 128 bits of entropy. That's below `det-keygen`'s "should be 192 bits" and its FIPS RSA-2048 minimum of 168, though it matches what Bitcoin and Trezor themselves rely on. 24 words (256 bits) meets every threshold.

---

## 6. Options (for a later decision; no code changed)

1. **Keep the current scheme, and freeze it properly.**
   Add a known-answer test that checks the exact RSA modulus for the `abandon…` seed (as ML-DSA already has). Pin PyCryptodome exactly, which is already done. Optionally vendor a frozen copy of the prime-generation path so a library upgrade can't change it. This is the cheapest option and keeps existing keys. It's still "our scheme".

2. **Switch RSA to C2SP `det-keygen` as a new scheme id (`seedsigner-msg/2`).**
   Keep HKDF and its labels to produce the seed (32 bytes, ≥192 bits, fine), then follow the spec's HMAC_DRBG and prime search. It's about 60 lines of Python on top of PyCryptodome's primality test and HMAC, and can be checked against the published vectors and against `filippo.io/keygen`. Keys change, so v1 would need to stay readable or be migrated. This removes the library dependency and uses a reviewed, FIPS-aligned design. **This is the option the research points to if RSA stays.**

3. **Add trezor-agent-compatible ECC PGP keys (Ed25519 sign + Cv25519 encrypt via SLIP-0013/0017/SLIP-10).**
   Derivation is trivial and specified by SLIPs, with no prime search. The same mnemonic and user ID on a Trezor with trezor-agent should give the same GPG key, which would be a strong external cross-check and recovery path. Two caveats: the BIP-39 passphrase and the exact user-ID string must match, and this hasn't been tested. Open questions: whether PGPy 0.6.0 with cryptography 3.3.2 on the Pi can build and use EdDSA/ECDH-Curve25519 keys, and how the key is presented to recipients who expect RSA.

4. **Do nothing.** This is acceptable for a test card that never holds a real seed (per this repo's own warnings), but not before real use.

Options 1 and 2 aren't exclusive: add the known-answer test now (it costs nothing and catches drift), and decide on 2 or 3 before any real-seed use.

---

## Sources

- Trezor firmware: [u2f.c](https://github.com/trezor/trezor-firmware/blob/main/legacy/firmware/u2f.c), [config.c](https://github.com/trezor/trezor-firmware/blob/main/legacy/firmware/config.c), [fido2.py](https://github.com/trezor/trezor-firmware/blob/main/core/src/apps/webauthn/fido2.py), [credential.py](https://github.com/trezor/trezor-firmware/blob/main/core/src/apps/webauthn/credential.py), [crypto/ecdsa.c](https://github.com/trezor/trezor-firmware/blob/main/crypto/ecdsa.c)
- trezor-agent: [README](https://github.com/romanz/trezor-agent), [README-GPG.md](https://github.com/romanz/trezor-agent/blob/master/doc/README-GPG.md), [DESIGN.md](https://github.com/romanz/trezor-agent/blob/master/doc/DESIGN.md), [libagent/gpg/](https://github.com/romanz/trezor-agent/tree/master/libagent/gpg), [libagent/device/interface.py](https://github.com/romanz/trezor-agent/blob/master/libagent/device/interface.py)
- SLIPs: [SLIP-0013](https://github.com/satoshilabs/slips/blob/master/slip-0013.md), [SLIP-0017](https://github.com/satoshilabs/slips/blob/master/slip-0017.md), [SLIP-0021](https://github.com/satoshilabs/slips/blob/master/slip-0021.md)
- Ledger: [GPG Card Add-on Developer Guide](https://openpgp.apps.ledger.com/gpgcard-addon.html)
- C2SP: [det-keygen](https://github.com/C2SP/C2SP/blob/main/det-keygen.md), [filippo.io/keygen](https://pkg.go.dev/filippo.io/keygen); discussion: [CFRG list](https://mailarchive.ietf.org/arch/msg/cfrg/V28CQmMZJN585AoO9rh5kmRLd4M/), [metzdowd cryptography list](https://www.metzdowd.com/pipermail/cryptography/2024-September/038497.html)
- Keyfork: [git.distrust.co/public/keyfork](https://git.distrust.co/public/keyfork) (not read directly; blocked)
- Local: `third_party/pycryptodome/lib/Crypto/PublicKey/RSA.py` (`generate`), `lib/Crypto/Math/Primality.py` (`generate_probable_prime`, `miller_rabin_test`), version 4.2.0
