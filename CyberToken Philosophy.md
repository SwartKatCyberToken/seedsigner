# CyberToken Philosophy

CyberToken starts from one idea: **you should be able to hold your own keys, check your own tools and talk privately without asking anyone's permission.** This repository puts that idea into hardware and code. It extends SeedSigner, an air-gapped Bitcoin signing device, so the same seed that protects your money can also protect your messages.

This page explains the principles behind the project and where each one shows up in the design.

> **Status:** the message features are a prototype. The post-quantum libraries are learning implementations and the key derivation hasn't had a security review. The principles below are what the project is built toward. They are not yet a promise that it is safe for real secrets. See [seedsigner-encryptor/README.md](seedsigner-encryptor/README.md).

---

## 1. Your keys, your identity

Self-sovereignty begins with key ownership. If a company holds your keys, it holds your identity.

- **One seed, many keys.** A single BIP-39 seed, which you write down and keep yourself, produces your Bitcoin keys and, through separate HKDF labels, your RSA, PGP, ML-DSA and ML-KEM message keys. Nothing is registered and no account is created. Your identity is something you can rebuild from 12 or 24 words.
- **Deterministic and recoverable.** The same seed always gives the same keys, so losing the device costs you nothing but the hardware. The full scheme is published in [message_key_derivation.md](seedsigner-encryptor/seedsigner/docs/message_key_derivation.md) so anyone can reproduce it.
- **A passphrase changes everything.** Adding a BIP-39 passphrase gives you a completely different set of keys. You decide how many identities you have and who knows about them.

## 2. Secrets never leave the device

A private key that touches a networked computer is no longer fully yours.

- **Air-gapped by design.** The device has no Wi-Fi or Bluetooth. Data comes in through the camera, a keyboard or a one-way relay, and goes out as QR codes on the screen.
- **Stateless.** Seeds live only in RAM and disappear when power is removed. The production image runs from memory and writes nothing to the SD card.
- **Hard limits on what can travel.** Seeds and decrypted plaintext are never offered on the USB relay. A seed that arrives through a general scan is refused, because it has already been on a computer.

## 3. Physics over promises

Software can claim to be one-way. Hardware can prove it.

- **The USB relay** joins two Arduino boards only by a relay contact. Data can physically move only from sender to receiver, so each direction needs its own pair. You don't have to trust the firmware's intentions. The wiring sets the limit.
- **Experimental relay builds.** Two builds of the mechanical link, which haven't run on real boards yet, replace the two pairs with one pair and a direction switch. One of them also carries each digit on seven relays, so a 7-segment display shows the data as hex. Each relay unit is still one-way by wiring. But both boards stay wired to drive their own relay unit, and the switch only tells the firmware which one sends. So in those builds, the direction depends on firmware. Where the direction matters, use the one-way pairs.
- **A stripped-down OS.** The production SeedSigner OS keeps USB in host-only mode with just the keyboard and serial drivers. There is no USB storage, networking, gadget mode, SSH or swap.
- **Honest trade-offs.** A keyboard or a Leonardo adds a small BadUSB risk, and the documentation says so. Use only your own plain wired keyboard and boards you flashed yourself.

## 4. Verify, don't trust

Autonomy means you can check things yourself instead of believing whoever is speaking loudest.

- **Fingerprint checks before use.** A newly imported contact key first shows its fingerprint. You compare it with one the owner gives you some other way. **Doesn't match** is the default button, so a careless click never accepts a key.
- **Standard, comparable fingerprints.** PGP keys show the same OpenPGP fingerprint as gpg, in the same groups. Other key types show a SHA-256 prefix you can reproduce with `openssl` and `sha256sum`.
- **Open, reproducible code.** Everything is free and open source under the MIT license. Dependencies are pinned and hash-locked, third-party crypto is vendored at known commits, and test helpers let you re-derive and check every value the device should show.
- **Known weaknesses are written down.** For example, the RSA and PGP keys currently depend on PyCryptodome's internal prime search, so a library upgrade could change them. The README names this as an open issue and [Trezor-vs-own-deterministic-pgp.md](seedsigner-encryptor/docs/Trezor-vs-own-deterministic-pgp.md) explains it.

## 5. Open standards, no lock-in

A tool that only talks to itself traps you.

- **Standard formats.** PGP output is ordinary OpenPGP. Signatures are standard cleartext blocks that other apps can verify, and the device accepts keys and messages from them in return.
- **Ordinary transports.** Animated `ur:bytes` QR codes, plain text QR codes, typed text and the relay all carry the same data. Copy damage such as stray line breaks or invisible characters is repaired, so you can move data with whatever tools you have.
- **Room for what comes next.** ML-DSA and ML-KEM sit beside RSA and PGP, so moving to post-quantum algorithms doesn't mean giving up your existing contacts.

## 6. Cheap enough for anyone

Sovereignty that costs a fortune is a privilege, not a right.

- The device is built from inexpensive, publicly available parts, usually under $50: a Raspberry Pi Zero, a small screen and a camera.
- Enclosure designs, setup scripts for Linux and Windows, and a Docker build of the production image are all in the repository. You can build the whole thing yourself, from the case to the OS.
- No company, subscription or online activation is involved. Once built, the device needs nothing from anyone.

## 7. Clear words are part of security

A tool you can't understand is a tool you have to trust blindly.

- Screens and documentation use plain language, and they explain why each step exists. For example: read a relayed message to the end before you sign it, because unchecked plain text can arrive shortened.
- The documentation states limits as clearly as features: what is tested on real hardware, what isn't yet, and what the prototype shouldn't be used for.

## 8. Human verification belongs where people can judge

Being able to check something only helps if a person can understand what they're looking at. This section records how the project's thinking on that changed, and why the mechanical channel stays.

### The original idea

The first design had no cold device with its own screen. You would type a message on a PC. Arduino 1 would send it through relays to Arduino 2, which held the key, signed the message and sent the signature back. In that design, Arduino 2 had no way to show you what it was about to sign. The relays and the 7-segment display were the only place you could see the data. Watching the digits go past was how you'd confirm that the thing sent for signing was the thing you typed, and nothing more.

The idea went further: a 3D-printed channel shaped like a mechanical keyboard, with relays physically pressing keys, so that anyone could watch their message cross the gap letter by letter.

### What changed

SeedSigner became the cold device. It has its own screen, its own keyboard input and its own review step, so the message you sign can be typed and read on the device that signs it. The device's own screen is the place to check what's being signed. The data on the wire isn't.

Most of what crosses the channel can't be judged by eye anyway:

- **Ciphertext and signatures** look random by design. Nobody can tell a clean one from one that hides something.
- **Hex is for engineers.** Knowing that a `4` then a `1` on the 7-segment build's display means the letter `A`, and that nothing else was sent, takes skills most people don't have and shouldn't need.
- **Checksums and error-correction data** can't be checked by hand in any reasonable time.

So reading the channel by eye isn't a security feature for ordinary users. The checks a person can really make are:

- reading the message on the cold device's own screen before signing or encrypting,
- comparing key fingerprints with their owner through another route (section 4),
- reading a Bitcoin transaction's outputs and amounts on the device.

The mechanical keyboard display may still be built. It would show people, more clearly than any diagram, that data is something physical that moves. That makes it a teaching tool, not a security control.

### Why the mechanical channel stays

Human verification was never the only reason for the relays. The relays are also the narrowest air gap the project has, and that still matters:

| | QR codes | Relay channel |
| --- | --- | --- |
| **Into the device** | A camera and an image decoder: a rich sensor and a complex parser. The error-correction area can carry data that nobody can practically inspect. | One relay contact, or seven on the 7-segment build, that is either open or closed. The receiving Leonardo reads it slowly and passes only numbered, checked packets to the device over USB serial. There's far less to parse. |
| **Out of the device** | A screen can leak more than the QR code shows, through flicker, brightness or timing that a person can't see. | Data leaves only as relay states, at a few bytes a second. There's no hidden side channel the size of a screen. |
| **Direction** | Each direction depends on software behaving. | One-way by wiring, with a separate pair for each direction. The switched builds depend on firmware for direction (section 3). |

It's worth being clear about what the relays don't do. They can't stop a compromised device from hiding a few bits inside a legitimate-looking result, such as a random-looking signature or ciphertext. No channel can, because the hiding happens before the data reaches it. The relays limit how much can leak and remove the hidden side channels. They don't guarantee that what's sent is clean.

### Current state

- QR codes, the keyboard and the relay all carry the same data. You choose the channel that fits your threat model.
- People check what they can judge: the message on the device screen, and key fingerprints, which match gpg and SHAP.
- The relay's status LED shows that the link is alive. On the experimental 7-segment build, the display also shows that every wire is connected and lets an engineer read the data. Neither is presented as a way for ordinary users to verify transfers.

### Direction of travel

The open question is how to turn "nobody can check this by eye" into "something simple can check it". Ideas under discussion:

- **A watching third board.** Relay contacts can be read by a third board without the sender being able to tell or interfere. A small, auditable board on the line could record everything that crossed, count it, and check it against what was expected. That's verification by a simple machine you can read the code of, instead of by eye.
- **Outputs that have only one right answer.** A signature can only be checked for hidden data if exactly one valid signature exists for that key and message. RSA PKCS#1 v1.5 signatures have that property. RSA-PSS (with a random salt) and randomised encryption don't. ML-DSA is signed deterministically here, but only someone holding the seed can confirm it, for example a second device or the PC test helper. Choosing schemes like this, and fixing values such as the PGP signature time, would let an independent checker prove that an output carries nothing extra.
- **Keep both channels.** QR codes remain for convenience and compatibility with SeedSigner. The relay is the hardened option for people who want the narrowest gap.

---

## In short

| Principle | How the project practises it |
| --- | --- |
| Own your keys | All keys derived from a seed you hold, with a published scheme |
| Keep secrets offline | Air gap, RAM-only operation, seeds never sent over the relay |
| Rely on physics | One-way relay hardware, minimal host-only USB |
| Verify, don't trust | Fingerprint checks, FOSS, pinned dependencies, documented weaknesses |
| Avoid lock-in | Standard OpenPGP, standard QR formats, post-quantum options |
| Stay accessible | Under $50 in common parts, fully self-buildable |
| Speak plainly | Clear screens and honest documentation |
| Check what people can judge | Read the message on the device, compare fingerprints, and let simple machines check the rest |

Digital autonomy isn't a feature you switch on. It is the result of many small choices that each leave control with you. CyberToken tries to make every one of those choices in your favour.
