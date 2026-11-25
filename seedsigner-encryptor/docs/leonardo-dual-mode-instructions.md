# Leonardo dual-mode firmware: instructions

For the agent working in the `mechanical` repository (`CyberToken/mechanical`, branch `main`). Read `README.md`, `src/sender/main.cpp`, `src/receiver/main.cpp` and `lib/relay_uart/relay_uart.h` first.

## Goal

Today each Leonardo has one fixed job, so changing direction means moving USB cables between boards. That's awkward, and it undermines the separation between the hot and cold ends.

Replace this with **one firmware on both boards**. Each computer stays plugged into its own Leonardo, and a single DPDT switch sets the direction.

| Switch position | Leonardo A | Signal path | Leonardo B |
| --- | --- | --- | --- |
| A sends, B receives | Mode pin on: send | A D5 → relay unit A → B D10 | Mode pin off: receive |
| B sends, A receives | Mode pin off: receive | B D5 → relay unit B → A D10 | Mode pin on: send |

## Mode pin: use A0, not a number

The mode pin is the **A0 header pin**, the first pin of the analog group, on the same header as VIN and below it. Define it once, in `config.h`, using the header name:

```cpp
const uint8_t kModePin = A0;
```

Never write a number for this pin. On a Leonardo, `A0` is pin 18. Pin 14 is MISO on the ICSP header, so code using `14` would compile and read the wrong pin. In docs and comments, call it A0, because the D numbers on the diagrams disagree:

| Header pin | AVR port | Number in Arduino's Leonardo pinout and core | Label on `Docs/pinout.jpg` |
| --- | --- | --- | --- |
| **A0** | PF7 | **D18** | D14 |
| A1 | PF6 | D19 | D15 |
| A2 | PF5 | D20 | D16 |
| A3 | PF4 | D21 | D17 |
| A4 | PF1 | D22 | D18 |
| A5 | PF0 | D23 | D19 |

`Docs/pinout.jpg` has the Leonardo's AVR ports but the Uno's D numbers, so don't use it for pin numbers. D5 and D10 mean the same thing in every source. A0 works as a digital input: PF7 is also a JTAG pin, but the Leonardo's fuses (`high_fuses=0xd8`) leave JTAG off.

### Sources

- [Arduino Leonardo full pinout (A000057)](https://docs.arduino.cc/resources/pinouts/A000057-full-pinout.pdf), also at `Docs/A000057-full-pinout.pdf`: A0 to A5 are D18 to D23.
- [`variants/leonardo/pins_arduino.h`, ArduinoCore-avr](https://github.com/arduino/ArduinoCore-avr/blob/master/variants/leonardo/pins_arduino.h), also at `Docs/pins_arduino.h`: `PIN_A0` is 18. D14 to D17 are the SPI pins, and D24 to D30 are second names for other pins.
- `framework-arduino-avr` 5.4.0, as installed by PlatformIO for this build: its `variants/leonardo/pins_arduino.h` is identical to `Docs/pins_arduino.h`, and its `boards.txt` has the fuse setting above. This is what the firmware compiles against.
- [`variants/standard/pins_arduino.h`, ArduinoCore-avr](https://github.com/arduino/ArduinoCore-avr/blob/master/variants/standard/pins_arduino.h), the Uno: `PIN_A0` is 14 and `PIN_A5` is 19, the numbering on `Docs/pinout.jpg`.

## Do not change

The Pi software is finished for this stage and expects these exactly. If one has to change, stop and raise it with the owner, because the Pi must change too.

- **USB:** serial at 115200 baud.
- **Send-mode output:** `READY TX <bit_us> <copies>`, `SENT <sequence> <length>`, `IDLE`.
- **Receive-mode output:** `READY RX`, `INCOMING <bit_us> <offset_us>`, `DATA <sequence> <hex>`, `DUP <sequence>`, `LOST <count>`, `BAD <reason>`, `STATUS <raw> <level> <good> <bad> <dup> <lost>`.
- **Line format, timing and packets:** everything in `relay_uart.h`, and the `RLY1` message header.
- **`STATUS` level:** it still reads 1 when the relay is at rest. The Pi shows "Contact open. Check the wiring." when it reads 0.

The Pi works out a board's mode from what it prints, so **a board must never print a line from the other mode**. Any of `SENT` or `IDLE` means send. Any of `STATUS`, `DATA`, `DUP`, `LOST`, `BAD` or `INCOMING` means receive.

## What the Pi does to the board

The firmware has to keep working through all of this:

1. **Before each transfer:** it opens the port, lowers DTR, waits about 100 ms and raises DTR. It then waits up to 10 s for a line that shows the mode. If it gets none, it resets USB and tries once more.
2. **While sending:** it keeps up to 64 unreported bytes on the board and counts `SENT` lengths. It gives up after at least 60 s without progress.
3. **After every transfer, including a cancelled or failed one:** it drops DTR and closes the port, then disconnects and reconnects the board in software by writing to its sysfs `authorized` file. There's no power cycle. The sketch must keep running with its mode intact and be ready for the next open.

The Pi never asks the board for its mode and doesn't remember it between transfers, so a switch flip between transfers needs nothing from the Pi.

## Firmware behaviour

Build one firmware from one `main.cpp`, and keep the mode logic thin. The classes in `lib/relay_uart` already do the link work.

**Startup, in this order:**

1. Set D5 to its rest level, then make it an output, in both modes. The relay must never click at startup. Rest level and `SENDER_LOW_LEVEL` keep their current meaning.
2. Set up D10 as the input, the mode pin as an input, and `LED_BUILTIN`.
3. Read the mode pin. HIGH is send and LOW is receive.
4. Start `Serial`, and don't wait for a computer.

**Send mode:** today's `src/sender/main.cpp`. Ignore D10.

**Receive mode:** today's `src/receiver/main.cpp`, reading D10 instead of D5. Hold D5 at rest. Keep throwing away USB input, because unread bytes can block a host's writes.

**When the mode pin changes:**

1. Only act once the pin has held its new level for 50 ms, checked without blocking. Ignore shorter changes. Nothing else in `loop()` may stall.
2. Set D5 to rest straight away. A flip takes effect immediately, and a packet in progress is abandoned. The other board reports it as `BAD`.
3. Throw away everything queued, and any unread USB input.
4. Create a fresh `LinkSender`, `LineReceiver` (with `begin()` at the current D10 level) and `SequenceTracker`, and zero the `STATUS` counters. A new sender must flag its first packet, and a new tracker must not report a false `LOST`.
5. If DTR is high, print the new mode's `READY` line, once the board is between packets. If DTR is low, the normal greeting covers it.

Don't reboot or use the watchdog to change mode. That would re-enumerate USB and cut off the connected computer.

**Keep from today's code:** the greeting on a DTR rising edge after `kGreetingDelayUs` (250 ms), cancelling a pending greeting when DTR falls, using USB only during gaps in the signal, and only reading USB bytes when the sender queue has room.

## Wiring to document

Add this to the README, replacing "To change direction, swap which computer is plugged into which board". Have the owner confirm it against the real build.

```text
Relay unit A   coil: Leonardo A D5, A 5V, A GND
               contact: B 5V -> COM, NC -> B D10
               B D10 also has 10k to B GND, plus the status LED and 1k in parallel

Relay unit B   coil: Leonardo B D5, B 5V, B GND
               contact: A 5V -> COM, NC -> A D10
               A D10 also has 10k to A GND, plus the status LED and 1k in parallel

DPDT switch    pole 1 (Leonardo A only): common -> A mode pin, throws -> A 5V and A GND
               pole 2 (Leonardo B only): common -> B mode pin, throws -> B GND and B 5V
               Each mode pin also has 10k to its own board's GND
```

- **Complete electrical isolation, both ways.** This is a firm requirement from the owner. The two poles must not share a wire, and the boards must not share a ground. Between the two sides there's only the relay's coil-to-contact gap and the gap between the switch's poles. Nothing in the design or the tests may add a common connection.
- **Throws are reversed between poles,** so one board is always on and the other off.
- **The 10k on each mode pin** holds it LOW while the switch moves between throws. Without it the pin floats.
- **D10 still needs its pull-down,** for the same reason D5 does today.

## Input source

Data reaches the board only from the connected computer, over the Leonardo's own micro USB port (`KEYBOARD_USB_SERIAL`). No keyboard or USB Host Shield will be connected, so the other `SENDER_KEYBOARD` options are out of scope: don't build, test or extend them for dual mode. In receive mode, USB input is only read to throw it away.

## Other changes in this repository

- **`platformio.ini`:** one environment for the single firmware, replacing `sender` and `receiver`. Check that it fits in flash.
- **`tools/deploy.py` and `deploy.cmd`/`deploy.sh`:** upload the same firmware to each board, and retire `--only sender`.
- **`tools/run.py`:** choose sender or receiver from the board's greeting, not by asking.
- **`tools/relay_send.py`:** on `READY RX`, stop with a message telling the user to flip the switch. `tools/relay_receive.py` does the same on `READY TX`.
- **`README.md`:** wiring, upload steps, the `READY` tables and the new mode behaviour.
- **`data-rate-testor*`:** leave as they are, unless the build changes break them.

## Tests

Extend `test/harness.py`, `test/native/Arduino.cpp` and `test/test_link.py`. The simulator's `digitalRead` has one schedule for all pins, so it needs one per pin. Keep every existing link test passing, running through the new firmware in each mode. Add tests for:

- Starting in each mode prints the right `READY` line, and only lines from that mode.
- D5 is at rest before it becomes an output, in both modes, and it stays at rest through all of receive mode.
- A mode pin bounce under 50 ms changes nothing.
- A flip while sending puts D5 at rest at once, drops the queue, and sends no leftover bytes after flipping back.
- A flip while connected prints the new `READY` line once, between packets.
- A full message goes A to B, flip, B to A, flip, A to B, with no false `LOST` and no bytes from an earlier message.
- A message survives with DTR dropped and raised between transfers, in both modes.
- Unread USB input in receive mode never blocks the loop, as `--waiting-serial-bytes` tests today.

Run `pio run` for the AVR build as well as the simulated tests.

## Check on real hardware

The simulator can't prove these, so ask the owner to run them:

1. With both USB cables unplugged, use a multimeter to confirm there's no continuity between A GND and B GND, or between A 5V and B 5V, in either switch position. Plugging both boards into one computer joins their grounds through that computer, so the final setup needs a separate computer on each side.
2. Flip the switch with the boards idle. Neither relay should click.
3. Send a message from the PC to the Pi, flip, and send from the Pi to the PC, with no cables moved and no resets. Repeat several times.
4. Flip during a send. The relay should stop at once, and the next message should arrive whole.
5. On the Pi, finish a transfer and start the next one straight away, to confirm the board comes through the Pi's USB reset.

## Don't do

- Don't edit anything in `seedsigner-pgp`.
- Don't commit the owner's untracked files in `Docs/` (`pinout.jpg`, `A000057-full-pinout.pdf`, `pins_arduino.h`) unless they ask.
- Don't flash the boards yourself or commit unless the owner asks.
