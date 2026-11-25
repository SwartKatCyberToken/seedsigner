# SeedSigner Extension: Deterministic Message Signing and Encryption

## 1. Project Overview

The goal is to extend a personal fork of [SeedSigner](https://github.com/SeedSigner/seedsigner) with functionality for signing, verifying, encrypting and decrypting user messages.

SeedSigner already provides a Bitcoin wallet workflow, BIP-39 mnemonic handling, QR-code scanning and display, and an air-gapped operating environment. The extension will reuse these existing components wherever possible.

The user will use the **same BIP-39 seed phrase already entered into SeedSigner for Bitcoin operations** as the starting point for deriving separate, deterministic cryptographic keys for messages.

The extension will support:

- **Encrypt** — encrypt a message for another party using their public key.
- **Decrypt** — decrypt a message using the user's private key.
- **Sign** — digitally sign a message using the user's private signing key.
- **Verify** — verify a message and signature using the sender's public key.

The intention is to keep private keys on the air-gapped device while allowing public keys, messages, ciphertext and signatures to be transferred using QR codes.

## 2. Cryptographic Libraries

The initial implementation will use Python libraries, matching SeedSigner's existing language and avoiding an unnecessary language migration.

### 2.1 RSA — PyCryptodome

**Source:** [PyCryptodome — RSA.py](https://github.com/Legrandin/pycryptodome/blob/master/lib/Crypto/PublicKey/RSA.py)

PyCryptodome provides an RSA implementation with an injectable randomness function.

The relevant interface is:

```python
RSA.generate(bits, randfunc=None, e=65537)
```

The implementation defaults to a cryptographically secure random-byte source:

```python
if randfunc is None:
    randfunc = Random.get_random_bytes
```

The proposed implementation will supply a deterministic `randfunc` derived from key material obtained from the SeedSigner mnemonic-derived seed.

This function must behave as a cryptographic random-byte stream, returning the requested number of bytes. It must not simply return the seed repeatedly.

The objective is to generate the same RSA keypair when the same mnemonic-derived material, derivation specification and compatible implementation are used.

Relevant documentation:

- [RSA key generation API](https://pycryptodome.readthedocs.io/en/latest/src/public_key/rsa.html)
- [PyCryptodome source repository](https://github.com/Legrandin/pycryptodome)

RSA will be used for digital signatures and, if selected for the initial encryption implementation, public-key encryption using a standard padding scheme such as RSA-OAEP. For longer messages, a hybrid encryption design using RSA to protect a symmetric key and authenticated symmetric encryption for the message is preferable.

### 2.2 Post-Quantum Digital Signatures — ML-DSA

**Source:** [dilithium-py — ml_dsa.py](https://github.com/GiacomoPope/dilithium-py/blob/main/src/dilithium_py/ml_dsa/ml_dsa.py)

ML-DSA is the post-quantum digital-signature algorithm standardised in NIST FIPS 204.

The implementation's ordinary key-generation method contains:

```python
def keygen(self):
    zeta = self.random_bytes(32)
    pk, sk = self._keygen_internal(zeta)
    return (pk, sk)
```

The library also provides a seed-based `key_derive()` path. That explicit interface should be evaluated before modifying the ordinary randomness source.

The proposed implementation will derive the required seed material from the SeedSigner mnemonic-derived seed using a documented, domain-separated derivation scheme.

This provides a route to reproducible ML-DSA keypairs without changing the underlying signature mathematics.

References:

- [dilithium-py repository](https://github.com/GiacomoPope/dilithium-py)
- [NIST FIPS 204 — ML-DSA](https://csrc.nist.gov/pubs/fips/204/final)

**Implementation caveat:** `dilithium-py` is intended for learning and experimentation, not production cryptographic use. It is useful for inspecting and prototyping the seed-derivation approach, but a production release must use an appropriately vetted implementation.

### 2.3 Post-Quantum Encryption — ML-KEM

**Source:** [kyber-py repository](https://github.com/GiacomoPope/kyber-py)

ML-KEM is the post-quantum key-encapsulation mechanism standardised in NIST FIPS 203.

It will be evaluated as the post-quantum counterpart to RSA-based encryption. ML-KEM establishes a shared secret; it does not directly encrypt an arbitrary-length message. The shared secret must be used with authenticated symmetric encryption.

References:

- [kyber-py source code](https://github.com/GiacomoPope/kyber-py)
- [NIST FIPS 203 — ML-KEM](https://csrc.nist.gov/pubs/fips/203/final)

As with `dilithium-py`, the pure-Python reference implementation is a starting point for investigation and testing, not a production deployment recommendation.

## 3. Deterministic Key Derivation

The same mnemonic phrase will serve as the user's starting recovery secret, but Bitcoin keys and message-cryptography keys must be derived separately.

The intended process is:

1. SeedSigner processes the BIP-39 mnemonic using its existing wallet workflow.
2. The extension obtains the appropriate seed material without changing Bitcoin's existing derivation or signing operations.
3. A documented key-derivation scheme derives separate material for each algorithm and purpose.
4. RSA key generation receives a deterministic random-byte stream through its `randfunc` interface.
5. ML-DSA and ML-KEM use their supported seed-based key-derivation interfaces where available.
6. Public and private keys are serialised into documented formats for storage, display and transfer.

The derivation scheme must use domain separation so that RSA signing, RSA encryption, ML-DSA signing and ML-KEM encryption do not accidentally reuse the same derived material.

It must also define the precise derivation algorithm, inputs, output lengths and versioning rules. These details are necessary for interoperability and recovery across software versions.

**Security consideration:** using the same mnemonic as the root secret means that compromise of the mnemonic can compromise both Bitcoin funds and message keys. Separate derivation prevents accidental key reuse, but does not eliminate this shared-root risk.

Deterministic key generation must not be implemented by replacing a cryptographic random-number source with the mnemonic itself or by blindly making every random operation deterministic. In particular, key generation and signature generation are distinct operations and may have different randomness requirements.

## 4. Why Not Extend BIP-39/BIP-32 to Use Elliptic-Curve Keys?

BIP-39 and BIP-32 are useful standards for mnemonic handling and deterministic hierarchical wallet-key derivation. However, BIP-32's standard derivation scheme is designed around particular elliptic-curve key material, notably secp256k1 in Bitcoin wallets.

The objective of this project is to derive RSA and post-quantum keys, not to create another elliptic-curve wallet scheme.

The reasons for this decision are:

- **Algorithm choice:** RSA and the selected post-quantum algorithms have different mathematical foundations and key-generation requirements.
- **Parameter transparency:** RSA's prime-generation and modular-arithmetic foundations are easier for the project author to inspect and reason about than the provenance of some elliptic-curve parameters.
- **Post-quantum support:** ML-DSA and ML-KEM do not rely on conventional elliptic-curve discrete-logarithm security.
- **Separation of concerns:** Bitcoin's existing BIP-32 derivation remains untouched; the extension defines separate derivation rules for message cryptography.

This is a project design preference, not a claim that elliptic-curve cryptography is inherently insecure. The important requirement is to use well-reviewed algorithms with documented parameters and a precisely specified derivation process.

## 5. Why Not Extend OpenPGP?

OpenPGP provides standard message formats, public-key representations, signatures, encryption, recipient handling and interoperability between compatible implementations.

However, the primary goal here is to integrate message cryptography directly into the SeedSigner user interface and reuse the device's existing mnemonic, QR-code and air-gap workflows.

A complete OpenPGP integration would introduce additional format and protocol requirements, and deterministic mnemonic-to-key derivation would still need its own specification.

The initial project will therefore investigate direct use of RSA, ML-DSA and ML-KEM with standard cryptographic encodings and a documented message format.

This does not mean OpenPGP is unsuitable. If interoperability with existing OpenPGP users becomes a requirement, a later implementation could add OpenPGP-compatible message handling while keeping deterministic key derivation as a separate, explicitly specified component.

## 6. Why Python Instead of Rust?

SeedSigner is already written in Python, and the proposed extension will reuse its existing Python code and libraries.

Rust's memory-safety properties are valuable, particularly for operating-system components, drivers, network services and software that parses hostile input. However, switching languages does not automatically make cryptography more secure.

For this project:

- The existing application and user-interface logic are Python-based.
- The proposed cryptographic libraries expose Python APIs.
- The device is air-gapped, reducing exposure to remote network attacks, although it does not eliminate risks from malicious input, compromised software or physical access.
- The most important immediate requirements are correct cryptographic algorithms, secure derivation, reliable key handling and thorough testing.

Python is therefore a reasonable choice for the extension. Production deployment must still use appropriately vetted cryptographic implementations; language choice alone is not a substitute for cryptographic review.

## 7. User Interface

The extension will add a new menu to SeedSigner's existing interface.

The initial navigation proposal is to reveal the additional menu after the user repeatedly presses the joystick to the right, subject to compatibility with SeedSigner's existing navigation and accessibility conventions.

The new menu will contain:

- Encrypt
- Decrypt
- Sign
- Verify

### Encrypt

The user enters a message and supplies the recipient's public key.

Message input options:

- Scan a QR code containing the plaintext.
- Type the plaintext using a USB keyboard connected to the SeedSigner device.

**Preferred workflow:** enter the plaintext using the connected keyboard. This avoids first putting the plaintext onto another, potentially internet-connected device merely to generate a QR code.

The device encrypts the message locally and presents the resulting ciphertext for transfer, such as through a QR code.

### Decrypt

The user supplies ciphertext, normally by scanning a QR code, and decrypts it locally using their private key.

A keyboard-input mode should also be available for development and testing, allowing ciphertext to be pasted rather than requiring camera input.

Decryption must reject invalid ciphertext and report errors without exposing private-key material.

### Sign

The user enters or scans a message and signs it using their private signing key.

Keyboard input is supported, but is less critical than for encryption because the message is not necessarily secret. The private signing key remains on the air-gapped device.

The interface should make clear exactly which message bytes are being signed and provide a transferable signature and the information required for verification.

### Verify

The user supplies a message, signature and the signer's public key.

The public key will normally be scanned from a QR code because it may be too long to enter manually. Keyboard input should also be supported for development and simulation, allowing public-key data to be pasted into the interface.

The result must clearly distinguish a valid signature from an invalid signature or malformed input. Verification confirms consistency with the supplied public key; it does not independently establish the real-world identity of its owner.

## 8. Testing Strategy

Testing will be divided into unit tests, PC-based user-interface testing and hardware integration testing.

### Stage 1 — Unit tests

Test the cryptographic functions independently of SeedSigner's graphical interface.

Tests will cover:

- Identical inputs and derivation parameters produce identical keypairs.
- Different algorithm labels produce distinct derived material.
- RSA keys can sign and verify messages.
- RSA encryption and decryption recover the original plaintext.
- ML-DSA signatures verify correctly and fail verification after message or signature alteration.
- ML-KEM establishes matching shared secrets for valid encapsulation and decapsulation.
- Malformed inputs and invalid keys are rejected.
- Key formats and message encodings can be serialised and parsed consistently.
- Derivation test vectors remain stable across compatible software versions.

### Stage 2 — PC-based interface testing

The next step is to test the actual SeedSigner interface on a PC before repeatedly rebuilding and installing the operating-system image.

Two candidate tools are:

- [SeedSigner Emulator](https://github.com/SeedSigner/seedsigner-emulator)
- [SeedSigner Desktop Simulation Mode](https://3rditeration.github.io/seedsigner/desktop_simulation.html)

The first task is to establish which tool is compatible with the chosen fork and its current dependencies. Follow its documented setup instructions and use the same application code wherever possible.

The desktop environment should be used to test:

- Navigation into and out of the new menu.
- Keyboard message entry and paste operations.
- QR-code input and output, where supported by the simulator.
- Public-key and ciphertext handling.
- Success, cancellation and error screens.
- Long messages, large keys and malformed input.
- Repeated operations and returning to the main menu.

A keyboard-input path is especially useful in the simulator because it avoids depending on a physical camera or a simulated camera feed during early development.

### Stage 3 — Raspberry Pi integration testing

Once the interface and cryptographic operations work in the PC environment, test the extension on the intended SeedSigner hardware and operating-system image.

Hardware tests should confirm:

- Actual joystick navigation and button behaviour.
- Camera-based QR scanning.
- QR-code display and readability.
- Keyboard compatibility, if supported by the device's hardware setup.
- Memory usage and performance during RSA key generation and post-quantum operations.
- Correct operation without a network connection.
- That private keys and plaintext secrets are not inadvertently persisted, logged or displayed in unintended contexts.

The PC simulator is a development aid, not a replacement for final hardware and air-gap testing.

## 9. Initial Implementation Milestones

1. Fork SeedSigner and establish a working development environment.
2. Run the existing application using a compatible desktop simulation or emulator.
3. Add a menu entry and implement navigation without cryptographic functionality.
4. Implement and test the separate mnemonic-derived key-material interface.
5. Integrate RSA signing, verification, encryption and decryption.
6. Prototype ML-DSA signing and verification using the seed-based API.
7. Prototype ML-KEM key establishment and authenticated message encryption.
8. Add keyboard and QR-code workflows.
9. Run the full unit and user-interface test suite.
10. Perform hardware integration, performance testing and a cryptographic security review before considering real-world use.

## 10. Scope and Security Principles

The first objective is a working, testable prototype that reuses SeedSigner's existing components and keeps the original Bitcoin wallet functionality unchanged.

The project will keep deterministic key derivation separate from message formats and cryptographic algorithms. It will document the derivation process, preserve test vectors, use standard algorithms and encodings where practical, and avoid ad hoc changes to cryptographic mathematics.

No real funds or sensitive messages should depend on the extension until the deterministic derivation scheme, cryptographic implementations and complete message workflows have received appropriate security review.

## 11. Where this prototype lives

The SeedSigner tree in `seedsigner/` is the application. Message cryptography is a separate derivation from Bitcoin's BIP-32 keys:

- Derivation contract: `seedsigner/docs/message_key_derivation.md`
- Algorithms and envelopes: `seedsigner/src/seedsigner/message_crypto/`
- Menu, keyboard, and QR screens: `seedsigner/src/seedsigner/views/message_views.py` and the `message_collect_views` / `message_run_views` modules

Home stays Scan, Seeds, Tools, and Settings. The message menu is not a fifth icon. Press Right while **Seeds** or **Settings** is highlighted, or Down while **Tools** or **Settings** is highlighted. That opens Encrypt, Decrypt, Sign, Verify, and View Public Key. The list uses Up and Down. Left or Right returns to Home.

Choosing Encrypt says immediately that your seed holds your own keys and encryption needs their public key. It does not ask for a seed. After the algorithm, pick their key from the list, then type the message. The list names every key, including when there is only one: **Own (Seed)** for a loaded seed, **Contact (imported)** for a key scanned or typed in this session, and **Contact (preloaded)** for `seedsigner/preloaded-public-keys.ini`. Each kind has its own icon. Scan QR and Enter key are on that same list. Before a result QR appears, a screen says whether it is the encrypted message, the signature, or the public key. Public-key text scrolls with Up and Down.

Sign and decrypt do use your private key, so they list **Own (Seed)** before the message or ciphertext. Verify lists the signer's public key before the signature. View Public Key uses the same list, so a contact key can be shown without a seed loaded. `test-data/testhelper.py` fills the INI from `test-data/testseed.txt`. `seedsigner/tools/preload_pub_keys.py` appends a key you paste from the device's View Public Key text screen.

Encrypt, decrypt, sign, and verify can use RSA, the post-quantum envelopes (ML-KEM for encrypt, ML-DSA for sign), or PGP. PGP is PGPy 0.6.0 wrapping the same seed RSA keys: the encryption key for encrypt and decrypt, the signing key for sign and verify. That is the compromise. pysequoia is newer and can mint its own hybrid keys, but it cannot take these already-derived RSA, ML-DSA-44, or ML-KEM-512 keys. PGPy cannot carry the post-quantum keys either, so those stay on the existing envelopes. PGPy imports `imghdr`, which Python 3.13 removed; the PGP module installs a stub before import on those versions. The same seed exports the same PGP armor because the key timestamp is fixed at 2026-01-01 UTC.

Desktop mode is a Tk window. It runs on Linux as well as Windows when Tk is installed (`python3-tk` on Debian and Ubuntu) and the message requirements are installed. There is no Windows-only call in that window.

Desktop keys, with the SeedSigner window focused:

- Arrow keys move the highlight. Enter is the joystick click.
- F1, F2, and F3 interact with the three hardware buttons. The current screen decides what each one does.

The upstream `seedsigner-emulator` repository currently contains no emulator code, so PC UI testing uses this tree's `--desktop` flag:

```text
cd seedsigner
pip install -r requirements-message.txt
set PYTHONPATH=src
python src/main.py --desktop
```

Unit tests, from `seedsigner/` with `PYTHONPATH=src`:

```text
python -m pytest tests/test_message_crypto.py tests/test_message_flow.py tests/test_key_catalog.py tests/test_hidden_menu.py tests/test_message_views.py tests/test_usb_keyboard.py
```

On a Pi, `python3 main.py --usb-keyboard` reads a USB keyboard alongside the joystick, with the same keys as desktop mode. [Updated Setup Guide.md](Updated%20Setup%20Guide.md) walks through a Pi Zero 1.3 test card. Problems hit during that setup, and their fixes, are in [troubleshoot.md](troubleshoot.md).

`dilithium-py` and `kyber-py` are the learning implementations named above, wired through their `key_derive` methods. They are not a production cryptography choice. Device RSA keys are 2048-bit; the unit tests generate 1024-bit RSA keys so the suite stays short.

`test-data/` holds a public BIP-39 test mnemonic and helpers. `testhelper.py` derives keys with the seedsigner code and writes `rsa/`, `ml-kem/`, and `pgp/` (`pub`, `priv`, and `test-signed-message.txt`; the PGP `pub` and `priv` are each one key block, with the encryption key as a subkey), then copies the public keys into `seedsigner/preloaded-public-keys.ini`. ML-KEM does not sign, so its message file is a ciphertext with a note. `decrypt-helper.py` decrypts an envelope by calling the same code:

```text
python test-data/testhelper.py
python test-data/decrypt-helper.py test-data/ml-kem/test-signed-message.txt
```

