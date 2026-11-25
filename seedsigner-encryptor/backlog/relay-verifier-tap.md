# An independent checker on the relay line

## Problem

People can't judge what crosses the relay by eye, even on the 7-segment build, where it shows as hex digits. A simple, independent machine can. The original design had a human watching the line because the signing Arduino had no screen. This puts a checker back on the line, but one that understands what it sees.

## Idea

A third board reads the same relay contacts as the receiving board, in parallel. Each contact is a switch, so reading its state can't affect the sender, and the sender can't tell it's being read. The board has its own small screen and no link to either computer. For data leaving the device, it shows:

- **What crossed:** how many messages, how many bytes, and whether anything arrived outside a complete, checked message.
- **What it was:** the device's outputs are text, either PGP armor or JSON envelopes. For a PGP cleartext signature, it shows the signed message itself.
- **Whether it checks out:** for a signature, "valid signature from C2DE 9E47 …, only valid value, nothing else sent". This needs [checkable-signatures.md](checkable-signatures.md): if more than one valid signature exists, validity says nothing about hidden data.

The value is that Jo can read the message and the verdict on a screen whose firmware is a few hundred lines anyone can audit, instead of trusting the Pi's whole software stack or the PC.

## Done when

1. **Wiring:** a documented way to put a third board on the line that doesn't load it. See [Wiring the tap](#wiring-the-tap).
2. **Decoding:** the tap reuses `relay_uart` from the mechanical firmware to decode packets, and `relay_digits` too for the 7-segment build. It handles the sender's two copies and the CRCs exactly as the receiver does.
3. **Display:** it shows the byte count, the message boundaries, and anything it couldn't decode.
4. **Verification:** it verifies PGP RSA signatures against a public key loaded once, for example from the device's View Public Key text, with its fingerprint shown on the tap so you can compare.
5. **Docs** say what it proves and what it doesn't:
   - Encryption output can't be checked.
   - A key loaded into the tap is only as trustworthy as the fingerprint check done when it was loaded.

## Wiring the tap

Each receiver input is one point in the circuit. A closed contact pulls it up to the receiving board's 5V, and a 10k resistor pulls it down to that board's GND. On `main`, a 330Ω resistor and the status LED also hang from that point. On the 7-segment build, each input has a 330Ω resistor and a display segment. A tap can read the same point, but not with a plain wire:

- **Voltage:** an RP2040's pins work at 3.3V and can't take 5V, so a direct wire would damage it.
- **Ground:** a direct wire also joins the tap's GND to the receiving board's GND, and through USB to that board's computer. The tap would then no longer be separate from either computer.
- **Likely answer:** one optocoupler per contact, such as a PC817. Its LED goes in series with about 1k, from the input to the receiving board's GND. That draws about 4 mA through each closed contact from the receiving board's 5V. When the contact is open, the 10k keeps the input at 0 V and the optocoupler's LED stays off, so the receiver still reads LOW. The tap's side of the optocoupler runs from the tap's own 3.3V and GND.
- **Load:** `main` has one contact per direction. The 7-segment build has seven, which adds about 28 mA to the 65 mA its README gives for a board's 5V with all segments lit. Check that against the relay contacts' rating and the board's 5V supply.
- **Speed:** a PC817 switches in tens of microseconds. That's well within the 9 ms bit on `main` and the 9 ms step on the 7-segment build.
- **Independence:** the tap reads the contacts themselves, not the receiving Leonardo's USB output, so it doesn't depend on the receiving board's firmware.

## Hardware

- **Leonardo:** too small for 2048-bit RSA verification, with 2.5 KB of RAM.
- **Raspberry Pi Pico (RP2040):** has the memory and speed, and has no radio. This is the likely choice.
- **ESP32, Pico W:** avoid. They have Wi-Fi and Bluetooth, which would undo the point of the air gap.
- **Screen:** a small SPI screen, such as the 240×240 ST7789 SeedSigner uses, so the text looks familiar.

## Open questions

- **Into the device too?** Showing data going into the device (for example the text of a message about to be signed) would help against injection, but only for text a person can read.
- **One board or two?** One tap per direction, or one board that can sit on either pair?
- **Keys:** should the tap hold more than one public key?
