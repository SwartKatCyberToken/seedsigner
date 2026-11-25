# A mechanical keyboard display for the relay

## What it is

A 3D-printed channel laid out like a keyboard. The relays physically press keys as the data passes, so anyone can watch a message cross the air gap letter by letter instead of reading hex on a 7-segment display.

## What it's for

It's a teaching piece and a demonstration, not a security control. It makes the idea of an air gap concrete: data is something physical that moves, and here you can see it move.

It doesn't let an ordinary user verify a transfer, for the reasons in section 8 of [CyberToken Philosophy.md](../../CyberToken%20Philosophy.md):
- Most of what crosses is ciphertext, signatures or key material, which nobody can judge by eye.
- Typed text can be read on the device's own screen before it's signed.
- Checking that nothing extra was sent is a job for [relay-verifier-tap.md](relay-verifier-tap.md).

So nothing else in the backlog waits for it, and the docs must not describe it as a way to verify transfers.

## Design notes

- **Speed:** the 7-segment link sends each byte as two hex digits, and the slowest knob setting gives about half a second per digit. A keyboard display that shows whole characters needs its own encoding, for example one key per character instead of hex. That would be a different link format, so the receiver and the computer tools would need to know it.
- **Text only:** it only makes sense for readable text. For anything else it could show what kind of data is passing, such as "signature" or "key", instead of individual keys.
- **Wear:** at hundreds of presses per message, relay and key wear matter.
- **Wiring:** keep the existing link the reference design. The keyboard display could be driven from the receiving side, like the status LED, or the 7-segment build's display, already is, so it adds no new path into either device.
