# SeedSigner Encryptor

A fork of [SeedSigner](https://github.com/SeedSigner/seedsigner) that adds **message encryption, decryption, signing and verification**. The keys come from the same BIP-39 seed you load for Bitcoin, but they are derived separately. Private keys stay on the air-gapped device. Public keys, ciphertext and signatures move by QR code or over a one-way [USB relay](#usb-relay), and you can type messages on a USB keyboard.

> **Prototype.** Don't use a real seed or a real secret message with it yet. `dilithium-py` and `kyber-py` are learning implementations, and the derivation scheme hasn't had a security review.

## What it does

| Action | Algorithms | Key used |
| --- | --- | --- |
| Encrypt | RSA-OAEP + AES-256-GCM, ML-KEM-512 + AES-256-GCM, PGP | Their public key |
| Decrypt | the same | Your seed |
| Sign | RSA, ML-DSA-44, PGP | Your seed |
| Verify | the same | Their public key |
| View Public Key | any of the above | Your seed or a contact |

**Opening the menu:** Home still has Scan, Seeds, Tools and Settings. Press **Right** on Seeds or Settings, or **Down** on Tools or Settings, to open Messages. Left or Right goes back Home.

**Keys:** Sign and Decrypt use **Own (Seed)**, a BIP-39 seed loaded from Seeds. Electrum seeds are rejected. Encrypt and Verify use a contact key, which can be:
- **Contact (preloaded)** from `seedsigner/preloaded-public-keys.ini`.
- **Contact (imported)**, scanned, typed or received over the USB relay during this session.

**Checking a key:** a contact key that has just been scanned, typed or received over the relay first shows its fingerprint, with **It matches** and **Doesn't match**. Compare it with the one the key's owner gives you some other way, for example on a call or on their own screen. The key is used, and kept for the session, only if it matches. **Doesn't match** is the default button, so one click without reading doesn't accept the key. **View Public Key → Fingerprint** shows any key's fingerprint, including your own for others to check, and the key list labels imported keys with the first two groups. For PGP it's the standard OpenPGP fingerprint, the same digits gpg and SHAP show, in gpg's ten groups of four. The other key types have no standard fingerprint, so they show the first 40 hex digits of a SHA-256: of the DER public key for RSA (`openssl pkey -pubin -outform DER | sha256sum`), and of the raw key bytes for ML-DSA and ML-KEM. `test-data/check-helper.py expected` prints the test seed's fingerprints.

**One PGP public key:** like SHAP and other PGP apps, the device has one PGP public key block. Its main key signs and its subkey encrypts. **View Public Key → PGP** shows it, and the same block is used to encrypt to you and to check your signatures. Other apps' PGP keys work the same way at both steps.

**Interop with other PGP apps:** at the public-key step, the device accepts a bare `PGP PUBLIC KEY BLOCK`. At the decrypt step, it accepts a bare `PGP MESSAGE`. Either can be typed, received over the USB relay, or scanned as an animated `ur:bytes` QR (the format SHAP uses) or a plain text QR, such as one made by pasting into a QR generator app. Copy damage is repaired: line breaks, typed `\n`, odd spaces, control characters and invisible characters. PGP signing makes a standard cleartext block (`BEGIN PGP SIGNED MESSAGE`), which SHAP can verify, and the verify step accepts those blocks from other apps. The message lines in a block are kept exactly as they arrive, so copy damage to them makes the check fail. Spaces and tabs at the end of a line aren't part of a PGP signature, so they're removed when signing.

## How the keys are made

```
BIP-39 seed (64 bytes, includes the passphrase)
  └─ HKDF-SHA256, salt "seedsigner-msg/1", one label per key
       ├─ rsa-sign / rsa-encrypt → HMAC stream → PyCryptodome RSA.generate(2048)
       │                                          └─ PGPy makes one PGP key: rsa-sign primary, rsa-encrypt subkey (fixed date 2026-01-01)
       ├─ ml-dsa-44  → ML_DSA_44.key_derive   (FIPS 204 seeded keygen)
       └─ ml-kem-512 → ML_KEM_512.key_derive  (FIPS 203 seeded keygen)
```

Only key generation is deterministic. Nonces, salts and AES keys come from the OS random generator. A passphrase changes every message key. The full specification is in [seedsigner/docs/message_key_derivation.md](seedsigner/docs/message_key_derivation.md).

**Open issue:** the RSA and PGP keys depend on PyCryptodome 4.2.0's internal prime search. A library upgrade could silently change the key a seed produces. Before real use, either add a known-answer test and freeze that code, or switch to [C2SP det-keygen](https://github.com/C2SP/C2SP/blob/main/det-keygen.md). [docs/Trezor-vs-own-deterministic-pgp.md](docs/Trezor-vs-own-deterministic-pgp.md) explains why.

## Repository layout

| Path | Contents |
| --- | --- |
| `seedsigner/` | The app. The message code is in `src/seedsigner/message_crypto/`, `views/message_*.py`, `hardware/usb_keyboard.py`, `hardware/usb_relay.py` and `views/relay_views.py`. |
| `third_party/` | `dilithium-py` and `kyber-py`, copied into the repository at pinned commits (see [third_party/README.md](third_party/README.md)). `pycryptodome` is a reference copy that isn't downloaded by default. To get it, run `git submodule update --init --checkout seedsigner-encryptor/third_party/pycryptodome` from the repository root. |
| `seedsigner-os/` | SeedSigner OS (Buildroot), changed for a USB keyboard, the USB relay and the crypto packages |
| `pi-dev-setup/` | Scripts for a Raspberry Pi OS **test card** |
| `pi-prod-setup/` | Docker build of the **production image** |
| `test-data/` | A public test mnemonic, plus helpers to derive, check and decrypt |
| `docs/` | Design notes, setup guides, troubleshooting and research |

## Run it on a PC

Desktop mode opens a Tk window. Use the arrow keys, Enter for the joystick click, and F1 to F3 for the three buttons.

Linux:

```bash
cd seedsigner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-message.txt
export PYTHONPATH=src
python src/main.py --desktop
```

Windows (Command Prompt):

```text
cd seedsigner
pip install -r requirements.txt
pip install -r requirements-message.txt
set PYTHONPATH=src
python src/main.py --desktop
```

The two `pip` commands must stay separate, because `requirements.txt` is hash-locked. PGPy 0.6.0 needs Python 3.12 or older. If your distribution ships a newer Python, create the venv with an older one, for example `python3.12 -m venv .venv`. On Linux, Tk may be a separate package (`python3-tkinter` on Fedora, `python3-tk` on Debian and Ubuntu).

**Tests:** from `seedsigner/`, with `PYTHONPATH=src` (`export` on Linux, `set` on Windows):

```text
python -m pytest tests/test_message_crypto.py tests/test_message_flow.py tests/test_message_views.py tests/test_message_pgp_text_qr.py tests/test_message_fingerprint.py tests/test_key_catalog.py tests/test_hidden_menu.py tests/test_usb_keyboard.py tests/test_usb_relay.py
```

**Test-data helpers:** `python test-data/testhelper.py` derives keys from the public test seed in `test-data/testseed.txt` and writes them to the preloaded contacts. `check-helper.py` prints the values a Pi should show. `decrypt-helper.py` decrypts an envelope.

## Run it on a Pi Zero

There are two kinds of SD card.

### Test card (Raspberry Pi OS Buster)

This card is for development. It is **not air-gapped**: it has SSH, swap and logs on the SD card. Full guide: [docs/Setup.md](docs/Setup.md), written for Windows. Each script has a Linux version next to it:

| Step | Linux | Windows (PowerShell) |
| --- | --- | --- |
| Download | `pi-dev-setup/download-for-pi.sh` | `pi-dev-setup\download-for-pi.ps1` |
| Gadget mode | `pi-dev-setup/sd-usb-mode.sh gadget` | `pi-dev-setup\sd-usb-mode.ps1 -Mode gadget` |
| Host mode | `pi-dev-setup/sd-usb-mode.sh host` | `pi-dev-setup\sd-usb-mode.ps1 -Mode host` |

1. Run the download script. It downloads the checked Buster Lite 2023-05-03 image, Python 3.10.10 and the other dependencies into `pi-dev-setup/downloads/`, and bundles the repository as `seedsigner-encryptor.tar.gz`.
2. Flash the image with Raspberry Pi Imager (**Use custom**, no customisation). On Linux you can also use `xzcat 2023-05-03-raspios-buster-armhf-lite.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress`, after checking the device name with `lsblk`.
3. Run gadget mode. The Pi's USB port then acts as a network adapter for the PC. Share the PC's internet with that adapter. On Linux, the SD card's boot partition must be mounted first (click it in the file manager). The script finds it under `/run/media/$USER` or `/media`, or you pass `--boot DIR`. On the PC, the Pi appears as a new network interface (`usb0` or `enx…`). To share the internet with NetworkManager: `nmcli connection add type ethernet ifname <interface> ipv4.method shared ipv6.method ignore`.
4. Copy the files over with `scp`, then run `pi-setup.sh` under `nohup`. It takes **3–4 hours**. Add `SEEDSIGNER_CAMERA=1` to also compile numpy for the camera.
5. Run host mode. Plug the keyboard into **USB** through an OTG adapter, and power into **PWR**.

**Updating code:** you don't need to reinstall. Switch to gadget mode, `scp` the changed `seedsigner/src/seedsigner`, then switch back to host mode. To make more test cards, clone the finished card. Shrink the image first with PiShrink if the new card might be smaller.

### Production image (SeedSigner OS)

This is the image for real use later. It runs from RAM, writes nothing to the SD card, and has no network, SSH or swap. Full guide: [pi-prod-setup/README.md](pi-prod-setup/README.md).

Linux:

```bash
pi-prod-setup/build-prod-image.sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File pi-prod-setup\build-prod-image.ps1
```

- **Build:** everything compiles in Docker on the PC. The first build takes 1–3 hours. On Linux, later builds reuse the compiled OS part, either from the build volume or from a snapshot in the conserve library, and take minutes. On Windows, add `-Fast` after app-only changes. See [OS snapshots](pi-prod-setup/README.md#os-snapshots-linux).
- **Output:** `pi-prod-setup/output/seedsigner_os.encryptor.pi0.img`, about 50 MB. It fits any SD card and flashes in minutes.
- **Changes to SeedSigner OS:** USB in host-only mode, with only the keyboard and Leonardo serial (CDC-ACM) drivers, so there's no USB storage, networking or gadget mode. The app starts with `--usb-keyboard`. pycryptodome and PGPy are added as packages.
- **Contacts:** none by default. To include test contacts, add `--preloaded-keys seedsigner/preloaded-public-keys.ini` (Linux) or `-PreloadedKeys seedsigner\preloaded-public-keys.ini` (Windows).

A USB keyboard or Leonardo adds a small BadUSB risk. Use only your own plain wired keyboard and boards you flashed yourself.

## Keyboard keys (desktop and `--usb-keyboard`)

| Key | Does |
| --- | --- |
| Arrow keys | Joystick directions |
| Enter | Joystick click |
| F1, F2, F3 | The three buttons. F3 is **Save** on a message keyboard. |
| Letters, Backspace, Shift+Enter | Type text, on message keyboard screens only |

Seed words are entered with the arrows and Enter, not by typing.

## USB relay

The third way in and out, next to QR codes and the keyboard. It uses the [mechanical](https://gitlab.com/software1015210/mechanical) link: two Arduino Leonardos joined only by a relay contact. Data can physically go only from the sender board to the receiver board, so each direction needs its own pair.

```text
Computer --USB--> sender Leonardo --relay--> receiver Leonardo --USB--> Pi        (into the device)
Pi       --USB--> sender Leonardo --relay--> receiver Leonardo --USB--> Computer  (out of the device)
```

The Pi tells the boards apart by their `READY TX` / `READY RX` greeting, so the order and port don't matter. Plug them in through an OTG adapter, or an OTG hub for both directions or a keyboard as well. Use a powered hub if the boards reset during a transfer. Flash the boards with the current mechanical firmware, with `kBitUs = 9000` in `src/sender/config.h` on every sender. Receivers measure the speed themselves, and the Pi reads it from the sender. You only need the direction you use, for example QR out and relay in.

**Where it appears:** a **Receive by USB** or **Send by USB** button appears wherever data goes in or out, but only while a Leonardo is plugged in. Receiving needs the receiver board and sending needs the sender board. Without one, the screens are the same as before. Desktop mode (`--desktop`) always shows the button so you can try the screens, though the relay itself works only on the Pi and on Linux. On Windows, choosing it shows an error.

| Direction | Screen | What travels |
| --- | --- | --- |
| In | Scan, Scan Transaction, Scan descriptor, Scan address | PSBT (base64, binary or `ur:`), descriptor, address, settings, sign-message request |
| In | Messages: key list (their public key), plaintext, ciphertext, signature | Same text you could type: PGP armor, PEM, base64 or a JSON envelope |
| Out | Signed PSBT | Base64 PSBT |
| Out | Export Xpub | `[fingerprint/path]xpub...` |
| Out | Sign Message result, Address Explorer | Signature, address |
| Out | Messages: public key, signature, encrypted message | Same text as **Show text** |

**Never on the relay:** seeds and decrypted plaintext. Seed-entry screens don't offer it, and a seed that arrives through general Scan is refused, because it has already been on a computer.

**Using it:** from the mechanical repository on the computer, choose **Receive by USB** or **Send by USB** on the device first, then:

```text
python tools/relay_send.py --file unsigned.psbt     # into the device
python tools/relay_receive.py                       # out of the device; prints the text
```

If the computer has both a sender and a receiver plugged in, these tools stop with "More than one Arduino found". Add `--port` to choose the board.

- **Speed:** 111 bits/s (9 ms per bit). After packet overhead and 2 copies of each packet, that's about 3 bytes a second. A 1-input PSBT takes a few minutes. An RSA PGP public key takes about 9 minutes. The device shows progress, and **Left** cancels. A cancelled send still finishes the bytes already on the board, which can take about 25 seconds, so that they can't join onto the next message. Sending a binary `.psbt` is 25% quicker than base64.
- **End of a message:** `relay_send.py` and the device add a header with the message's length and CRC-32, so the receiving side finishes as soon as all of it arrives and checks it. `relay_receive.py` prints a message from the device only once it's whole, so a long one shows nothing until the end. Add `--debug` to watch its packets arrive. Data with no header (`--raw`, or typed keys) has no end marker, so the device finishes after 12 seconds with no activity. Start the computer's sender only after the device shows **Waiting**.
- **Between transfers:** the device closes the port and resets its USB connection after every send or receive, including a cancelled or failed one, so the next transfer starts clean in either direction. If a search finds no answer, it resets USB and searches once more. The sketch on the board keeps running through a reset, and a keyboard on the same hub isn't touched.
- **On screen while receiving:** bytes received, packets OK, damaged and lost, whether the message can be checked, and the last two lines of text to arrive.
- **Errors:** packets carry a CRC and are numbered. If a packet is reported lost, the numbers skip, there are more damaged copies than the last packet can account for, or the transfer started before the device was listening, the device discards the message and asks you to send it again. Once in a while this happens because of noise on the line or a loss at the end of the previous message, and sending again fixes it. The data then goes through the same checks as a scanned QR.
- **Shortened messages:** a message with a header that's cut short or damaged is refused. Without a header (the device shows **No header: can't check it's whole**), a last packet that disappears completely can't be detected, and neither can packets sent before the device started listening. If the device restarts during a send, the board also finishes what it holds, and that can join onto the next message. PSBTs and keys will usually fail their checks, but plain text can arrive shortened, so **read messages to the end on screen before you sign or encrypt them**.

The link itself passed a hardware speed sweep with mechanical's test tool: 3 of 3 short messages at every speed from 40 ms down to 5 ms per bit, so 9 ms has margin. Sending and receiving on the Pi have both worked on real boards. The USB reset between transfers hasn't been confirmed on real boards yet. Open firmware issues are in [the protocol review](docs/usb-relay-protocol-review.md).

## More documentation

| Document | Covers |
| --- | --- |
| [docs/README.md](docs/README.md) | Original design: goals, library choices, why not BIP-32 ECC, OpenPGP or Rust, testing plan, milestones |
| [docs/Setup.md](docs/Setup.md) | Step-by-step Pi Zero 1.3 test card, plus test procedures A–D |
| [docs/Troubleshoot.md](docs/Troubleshoot.md) | Drive letters, RNDIS and COM port, SSH and network sharing, setup-script errors |
| [seedsigner/README.md](seedsigner/README.md) | Upstream SeedSigner, including flashing stock 0.8.7 |
| [docs/Trezor-vs-own-deterministic-pgp.md](docs/Trezor-vs-own-deterministic-pgp.md) | Our deterministic RSA compared with Trezor, Ledger and C2SP det-keygen |
