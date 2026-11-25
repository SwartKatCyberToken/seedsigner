# Backlog

Planned work that isn't started. Each file states the problem, what done looks like, and what's still open. The reasoning behind these items is in section 8 of [CyberToken Philosophy.md](../../CyberToken%20Philosophy.md).

| Item | Summary | Depends on |
| --- | --- | --- |
| [threat-model.md](threat-model.md) | Decide whether keeping bad input out or stopping a compromised device leaking data comes first. This sets the order of the rest. | Nothing. Decide first. |
| [checkable-signatures.md](checkable-signatures.md) | Make every signature the device sends the only valid one, so nothing can hide in it | Nothing |
| [reproducible-image.md](reproducible-image.md) | The same commit always builds the same image hash | Nothing |
| [relay-verifier-tap.md](relay-verifier-tap.md) | A third, independent board on the relay line that shows what crossed and checks it | checkable-signatures.md |
| [mechanical-keyboard-display.md](mechanical-keyboard-display.md) | A 3D-printed, keyboard-shaped relay display that shows data moving. A teaching piece, not a security control. | Nothing. It must not block the others. |

Suggested order: checkable signatures, then the reproducible image, then the verifier tap. The threat model may change that.
