"""One-way data link through a pair of Arduino Leonardos and a relay.

The link is the "mechanical" project (gitlab.com/software1015210/mechanical).
A sender Leonardo pulses a relay; a receiver Leonardo reads the contact. Each
board is a USB serial device (/dev/ttyACM*) on its own computer, so a Pi that
wants both directions has a sender and a receiver plugged in, usually through
an OTG hub. Nothing here changes the firmware's protocol:

    To the sender:      raw bytes. It replies READY TX <bit_us> <copies>,
                        SENT <seq> <length>, IDLE.
    From the receiver:  READY RX, INCOMING <bit_us> <offset_us>,
                        DATA <seq> <hex>, DUP <seq>, LOST <count>, BAD <reason>,
                        STATUS <raw> <level> <good> <bad> <dup> <lost>.

relay_send.py starts a message with a header (RLY1, then its length and CRC-32,
both big-endian), so that message ends when all of it has arrived and is checked.
Data with no header, such as raw or typed bytes, has no framing: it ends when the
line has been quiet for idle_seconds and can't be checked for completeness. The
link moves about 3 bytes a second, so a progress screen is part of every transfer.

Does not choose what to send. Views pass only public data (public keys,
signatures, ciphertext, signed PSBTs, xpubs, addresses). Seeds never use it.

Standard library only. termios and fcntl are imported on first open so the
desktop app still starts on Windows, where can_open_ports() is False.
"""

import base64
import glob
import logging
import math
import os
import select
import struct
import threading
import time
import zlib

logger = logging.getLogger(__name__)

ROLE_TX = "tx"
ROLE_RX = "rx"

_PORT_GLOB = "/dev/ttyACM*"
_SYS_TTY_GLOB = "/sys/class/tty/ttyACM*"
_MAX_LINE_CHARS = 4096
# A busy sender answers only between packets, and a packet at 15 ms per bit takes 8.6 s.
_PROBE_SECONDS = 10.0
# Time for a board leaving its bootloader to come back on its normal port.
_REENUMERATE_SECONDS = 2.0
# Time for a closing port to lower DTR, and for the kernel to finish with a disconnect.
_RESET_PAUSE_SECONDS = 0.2
_RESET_RETURN_SECONDS = 4.0

# The sender settings this project uses (kBitUs, kCopies in the firmware's
# config.h), for time estimates when no READY TX has reported the real values.
_DEFAULT_BIT_US = 9000
_DEFAULT_COPIES = 2
_PACKET_PAYLOAD = 16
# Break, gap, calibration, 22 framed bytes, and the trailing gap of a full packet.
_PACKET_BITS = 288

# Bytes handed to the sender and not yet reported SENT. Above one packet so the
# firmware never flushes a part-full packet, and small so Cancel stops quickly.
_SEND_WINDOW = 64
_MIN_STALL_SECONDS = 60.0
MIN_IDLE_SECONDS = 12.0
# The receiver prints INCOMING speeds unchecked, and noise can give any value. Below
# this a pulse can't survive the firmware's 2 ms debounce; above it is under 10 bits/s.
_MIN_INCOMING_BIT_US = 2000
_MAX_INCOMING_BIT_US = 100000
MAX_RECEIVE_BYTES = 64 * 1024
# The header from mechanical's frame_message: magic, payload length, payload CRC-32.
_MESSAGE_MAGIC = b"RLY1"
_HEADER_BYTES = 12
_PREVIEW_BYTES = 80

# Set by main.py --desktop, so the relay screens can be tried without a board.
offer_without_board = False


class RelayError(Exception):
    """A transfer failed. The message is safe to show on screen."""


def attached() -> bool:
    """True when a USB serial device is plugged in. Views offer the relay on this."""
    return offer_without_board or bool(glob.glob(_PORT_GLOB))


def can_open_ports() -> bool:
    """False on Windows, which has no termios and no /dev/ttyACM* ports."""
    try:
        import termios  # noqa: F401
    except ImportError:
        return False
    return True


def parse_line(line: str) -> tuple:
    """Split a firmware line into (name, *values). Malformed lines give ("",)."""
    parts = line.split()
    if not parts:
        return ("",)
    name = parts[0]
    try:
        if name == "READY" and len(parts) >= 2:
            return ("READY", parts[1], *(int(part) for part in parts[2:]))
        if name == "DATA" and len(parts) == 3:
            return ("DATA", int(parts[1]), bytes.fromhex(parts[2]))
        if name == "BAD":
            return ("BAD", parts[1] if len(parts) > 1 else "")
        if name in ("SENT", "LOST", "DUP", "INCOMING", "STATUS"):
            return (name, *(int(part) for part in parts[1:]))
        if name == "IDLE":
            return ("IDLE",)
    except ValueError:
        pass
    return ("",)


def _role_of(parsed: tuple) -> str | None:
    name = parsed[0]
    if name == "READY":
        return {"TX": ROLE_TX, "RX": ROLE_RX}.get(parsed[1])
    if name in ("SENT", "IDLE"):
        return ROLE_TX
    if name in ("STATUS", "DATA", "DUP", "LOST", "BAD", "INCOMING"):
        return ROLE_RX
    return None


class SerialPort:
    """A /dev/ttyACM* device in raw mode with line-based reads."""

    def __init__(self, path: str):
        import termios
        import tty

        self.path = path
        self.greeting = None
        self.saw_packets = False
        self._tail = b""
        try:
            self._fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            raise RelayError(f"Cannot open {path}") from exc
        try:
            # Raw straight away: a cooked tty echoes what the board prints back
            # into the board, and the sender would transmit it. VMIN stays 1, so
            # an empty read means the board is gone rather than "no data yet".
            # TCSANOW because setraw's default waits, with no timeout, for output
            # to drain. If the greeting was echoed before this line, a receiver
            # never drains it: its firmware doesn't read, and its USB endpoint
            # holds 2 packets, one for each echoed character.
            tty.setraw(self._fd, termios.TCSANOW)
            attrs = termios.tcgetattr(self._fd)
            attrs[4] = termios.B115200
            attrs[5] = termios.B115200
            termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
            termios.tcflush(self._fd, termios.TCIOFLUSH)
        except (OSError, termios.error) as exc:
            self.close()
            raise RelayError(f"Cannot set up {path}") from exc

    def request_greeting(self) -> None:
        """Lower and raise DTR. The firmware prints READY on the rising edge."""
        import fcntl
        import struct
        import termios

        flag = struct.pack("I", termios.TIOCM_DTR)
        try:
            fcntl.ioctl(self._fd, termios.TIOCMBIC, flag)
            time.sleep(0.1)
            fcntl.ioctl(self._fd, termios.TIOCMBIS, flag)
        except OSError:
            logger.info("could not toggle DTR on %s", self.path)

    def read_lines(self, timeout: float) -> list:
        ready, _w, _x = select.select([self._fd], [], [], timeout)
        if not ready:
            return []
        try:
            chunk = os.read(self._fd, 512)
        except BlockingIOError:
            return []
        except OSError as exc:
            raise RelayError("The USB relay was unplugged") from exc
        if not chunk:
            raise RelayError("The USB relay was unplugged")
        lines = (self._tail + chunk).split(b"\n")
        self._tail = lines.pop()[-_MAX_LINE_CHARS:]
        return [line.decode("ascii", errors="replace").strip() for line in lines]

    def write(self, data: bytes) -> int:
        """Write what fits without blocking. Returns the number of bytes taken."""
        try:
            return os.write(self._fd, data)
        except BlockingIOError:
            return 0
        except OSError as exc:
            raise RelayError("The USB relay was unplugged") from exc

    def close(self) -> None:
        # Closing a tty can wait 30 seconds for that same stuck output, so don't
        # hold up the screen for it. reset_usb ends that wait.
        if self._fd is not None:
            threading.Thread(target=_close_quietly, args=(self._fd,), daemon=True).start()
            self._fd = None


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def usb_devices() -> list:
    """The sysfs folder of each USB device that has a /dev/ttyACM* port."""
    # A tty's device link is its USB interface, and that interface's parent is the device.
    folders = {os.path.realpath(os.path.join(tty, "device", "..")) for tty in glob.glob(_SYS_TTY_GLOB)}
    return sorted(folder for folder in folders if os.path.exists(os.path.join(folder, "authorized")))


def _set_authorized(device: str, value: bool) -> bool:
    try:
        with open(os.path.join(device, "authorized"), "w") as control:
            control.write("1" if value else "0")
    except OSError as exc:
        logger.warning("could not reset USB device %s: %s", device, exc)
        return False
    return True


def reset_usb(devices: list, clock=time.monotonic, sleep=time.sleep) -> None:
    """Disconnect and reconnect these devices in software, as a replug does on the Pi.

    This ends any stuck close, drops pending USB transfers and gives the board fresh
    USB endpoints. The sketch keeps running. Only ports are touched, so a keyboard on
    the same hub stays connected. Writing here needs root, which the Pi image runs as.
    Without it, this does nothing and the port has only been closed.
    """
    if not devices:
        return
    sleep(_RESET_PAUSE_SECONDS)
    disconnected = [device for device in devices if _set_authorized(device, False)]
    if not disconnected:
        return
    sleep(_RESET_PAUSE_SECONDS)
    for device in disconnected:
        _set_authorized(device, True)
    # The menus offer the relay only while a port exists, so wait for it to come back.
    deadline = clock() + _RESET_RETURN_SECONDS
    while len(glob.glob(_PORT_GLOB)) < len(devices) and clock() < deadline:
        sleep(0.1)


def find_port(role: str, open_port=SerialPort, paths=None, probe_seconds: float = _PROBE_SECONDS, clock=time.monotonic, sleep=time.sleep):
    """Open the board that plays this role. It announces its role in its greeting.

    A port that fails or stays silent during the search may be a Leonardo leaving
    its bootloader or a stuck connection, so USB is reset and the search runs once
    more on the ports present by then.
    """
    port, wrong_role, port_failed = _search_ports(role, open_port, paths, probe_seconds, clock)
    if port is None and port_failed:
        reset_usb(usb_devices(), clock, sleep)
        sleep(_REENUMERATE_SECONDS)
        port, wrong_again, _failed = _search_ports(role, open_port, paths, probe_seconds, clock)
        wrong_role = wrong_role or wrong_again
    if port is not None:
        return port
    wanted = "sender" if role == ROLE_TX else "receiver"
    if wrong_role:
        verb, other = ("sends", "receiver") if role == ROLE_TX else ("receives", "sender")
        raise RelayError(f"This step {verb} data, so it needs the {wanted} board. The board plugged in is a {other}.")
    raise RelayError(f"No relay {wanted} found. Check that its Leonardo is plugged in.")


def _search_ports(role: str, open_port, paths, probe_seconds: float, clock) -> tuple:
    """Returns (matching port or None, saw another role, a port failed or stayed silent)."""
    paths = sorted(glob.glob(_PORT_GLOB)) if paths is None else paths
    wrong_role = False
    port_failed = False
    for path in paths:
        try:
            port = open_port(path)
        except RelayError as exc:
            logger.info("%s", exc)
            port_failed = True
            continue
        found = None
        try:
            found = _probe(port, clock, probe_seconds)
        except RelayError as exc:
            logger.info("%s", exc)
            port_failed = True
        if found == role:
            return port, wrong_role, port_failed
        wrong_role = wrong_role or found is not None
        port_failed = port_failed or found is None
        port.close()
    return None, wrong_role, port_failed


def _probe(port, clock, probe_seconds: float) -> str | None:
    port.request_greeting()
    deadline = clock() + probe_seconds
    while clock() < deadline:
        batch = [parse_line(line) for line in port.read_lines(0.2)]
        role = next((role for role in map(_role_of, batch) if role), None)
        if role:
            for parsed in batch:
                if parsed[0] == "READY":
                    port.greeting = parsed
                elif parsed[0] in ("DATA", "DUP"):
                    port.saw_packets = True
            return role
    return None


def frame_message(payload: bytes) -> bytes:
    """payload with the header that lets the receiver check all of it arrived."""
    return _MESSAGE_MAGIC + struct.pack(">II", len(payload), zlib.crc32(payload)) + payload


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return "under a minute"
    minutes = math.ceil(seconds / 60)
    return "about 1 min" if minutes == 1 else f"about {minutes} min"


class RelaySender:
    """Push data through a sender board, tracking its SENT reports."""

    def __init__(self, port, data: bytes, clock=time.monotonic):
        self._port = port
        self._data = bytes(data)
        self._clock = clock
        self._written = 0
        self.sent = 0
        self._bit_us = _DEFAULT_BIT_US
        self._copies = _DEFAULT_COPIES
        greeting = getattr(port, "greeting", None)
        if greeting and len(greeting) >= 4:
            self._bit_us, self._copies = greeting[2], greeting[3]
        self._last_progress = clock()

    @property
    def total(self) -> int:
        return len(self._data)

    @property
    def done(self) -> bool:
        return self.sent >= self.total

    def _packet_seconds(self) -> float:
        return _PACKET_BITS * self._bit_us * self._copies / 1_000_000

    def seconds_left(self) -> float:
        packets = math.ceil(max(self.total - self.sent, 0) / _PACKET_PAYLOAD)
        return packets * self._packet_seconds()

    def poll(self, timeout: float = 0.1) -> None:
        room = _SEND_WINDOW - (self._written - self.sent)
        if room > 0 and self._written < self.total:
            self._written += self._port.write(self._data[self._written:self._written + room])
        self._read_reports(timeout)

    @property
    def queued(self) -> bool:
        """True while the board holds bytes it hasn't finished sending."""
        return self.sent < self._written

    def drain(self) -> None:
        """After a cancel, wait for the bytes already written to go out.

        The firmware has no abort command. Starting another send before this
        finishes would join the two messages and inflate the new SENT count.
        """
        while self.queued:
            self._read_reports(0.2)

    def _read_reports(self, timeout: float) -> None:
        for line in self._port.read_lines(timeout):
            parsed = parse_line(line)
            if parsed[0] == "SENT" and len(parsed) == 3:
                self.sent += parsed[2]
                self._last_progress = self._clock()
        stall_limit = max(_MIN_STALL_SECONDS, 3 * self._packet_seconds())
        if not self.done and self._clock() - self._last_progress > stall_limit:
            raise RelayError("The sender stopped responding. Check the Leonardo.")

    def status(self) -> tuple:
        """(headline, detail, fraction complete) for the progress screen."""
        detail = f"{self.sent} of {self.total} bytes, {_format_duration(self.seconds_left())} left"
        return "Sending", detail, self.sent / self.total if self.total else 1.0

    def notes(self) -> list:
        return []

    def preview(self) -> str:
        return ""


class RelayReceiver:
    """Collect one message from a receiver board. It ends when the line goes quiet."""

    def __init__(self, port, idle_seconds: float = MIN_IDLE_SECONDS, max_bytes: int = MAX_RECEIVE_BYTES, clock=time.monotonic):
        self._port = port
        self._idle_seconds = idle_seconds
        self._max_bytes = max_bytes
        self._clock = clock
        self._data = bytearray()
        self._lost = 0
        self._good_packets = 0
        self._damaged_copies = 0
        self._bit_us = _DEFAULT_BIT_US
        self._contact_open = False
        # Copies of the current packet accounted for, and damaged copies since.
        self._copies_heard = 0
        self._pending_bad = 0
        self._last_sequence = None
        # When we last saw proof that an earlier part of this stream was missed.
        self._late_start_at = clock() if getattr(port, "saw_packets", False) is True else None
        self._last_activity = clock()

    @property
    def received(self) -> int:
        return len(self._data)

    @property
    def done(self) -> bool:
        header = self._header()
        if header and self.received >= _HEADER_BYTES + header[0]:
            return True
        return bool(self._data) and self._clock() - self._last_activity > self._idle_seconds

    def _header(self) -> tuple | None:
        """(payload length, CRC-32), once a whole message header has arrived."""
        if self.received < _HEADER_BYTES or not self._data.startswith(_MESSAGE_MAGIC):
            return None
        return struct.unpack(">II", self._data[len(_MESSAGE_MAGIC):_HEADER_BYTES])

    def _may_have_header(self) -> bool:
        """True until the first bytes rule out a header."""
        return self._data[:len(_MESSAGE_MAGIC)] == _MESSAGE_MAGIC[:self.received]

    def poll(self, timeout: float = 0.1) -> None:
        for line in self._port.read_lines(timeout):
            self._handle(parse_line(line))
        header = self._header()
        over = header[0] > self._max_bytes if header else self.received > self._max_bytes
        if over:
            raise RelayError(f"Message is over the {self._max_bytes} byte limit")

    def _handle(self, parsed: tuple) -> None:
        name = parsed[0]
        if name == "DATA":
            self._on_data(parsed[1], parsed[2])
        elif name == "DUP" and len(parsed) == 2:
            self._on_repeat(parsed[1])
        elif name == "BAD":
            self._pending_bad += 1
            self._damaged_copies += 1
        elif name == "LOST" and len(parsed) == 2:
            # Before the first DATA this may be the end of the previous message,
            # but it may be this message's start, so it has to count as a loss.
            self._lost += parsed[1]
        elif name == "INCOMING" and len(parsed) >= 2:
            if _MIN_INCOMING_BIT_US <= parsed[1] <= _MAX_INCOMING_BIT_US:
                self._bit_us = parsed[1]
                stretched = 2.5 * _PACKET_BITS * parsed[1] / 1_000_000
                self._idle_seconds = max(self._idle_seconds, stretched)
        else:
            if name == "STATUS" and len(parsed) >= 3:
                self._contact_open = parsed[2] == 0
            return
        self._last_activity = self._clock()

    def _on_data(self, sequence: int, payload: bytes) -> None:
        if self._data:
            # A second check on the firmware's LOST lines.
            if sequence != (self._last_sequence + 1) & 0xFF:
                self._lost += 1
        elif self._late_start_at is not None and self._clock() - self._late_start_at <= self._idle_seconds:
            self._lost += 1
        self._data.extend(payload)
        self._good_packets += 1
        self._last_sequence = sequence
        self._copies_heard = self._pending_bad + 1
        self._pending_bad = 0

    def _on_repeat(self, sequence: int) -> None:
        # A real repeat is a copy of the packet just seen. Any other number means
        # the firmware's tracker is calling new packets old, and dropping them.
        if self._last_sequence is not None and sequence != self._last_sequence:
            raise RelayError("The receiver board dropped packets. Replug both boards and send again.")
        if not self._data:
            # The first copy of this packet came before this port was listening.
            self._late_start_at = self._clock()
        self._last_sequence = sequence
        self._copies_heard += self._pending_bad + 1
        self._pending_bad = 0

    def result(self) -> bytes:
        """The message, or RelayError if part of it is missing."""
        if self._data.startswith(_MESSAGE_MAGIC):
            return self._checked_payload()
        # A BAD beyond the last packet's copies belongs to a further packet, which
        # is gone. The copy count is only reported by the sender board, which on this
        # path is plugged into the computer, so this assumes the project's setting.
        if self._lost or self._copies_heard + self._pending_bad > _DEFAULT_COPIES:
            raise RelayError("Part of the message was lost on the relay. Send it again.")
        return bytes(self._data)

    def _checked_payload(self) -> bytes:
        # The length and CRC-32 cover every byte, so they replace the packet checks.
        header = self._header()
        if header is None:
            raise RelayError("The message stopped in its header. Send it again.")
        length, crc = header
        payload = bytes(self._data[_HEADER_BYTES:_HEADER_BYTES + length])
        if len(payload) < length:
            raise RelayError(f"The message stopped after {len(payload)} of {length} bytes. Send it again.")
        if self.received > _HEADER_BYTES + length:
            raise RelayError("More data followed the message. Send it again.")
        if zlib.crc32(payload) != crc:
            raise RelayError("The message failed its CRC-32 check. Send it again.")
        return payload

    def status(self) -> tuple:
        if not self._data:
            return "Waiting", "Start sending from the computer now.", None
        header = self._header()
        if header is None:
            return "Receiving", f"{self.received} bytes so far", None
        length = header[0]
        got = min(self.received - _HEADER_BYTES, length)
        packets = math.ceil((length - got) / _PACKET_PAYLOAD)
        left = packets * _PACKET_BITS * self._bit_us * _DEFAULT_COPIES / 1_000_000
        detail = f"{got} of {length} bytes, {_format_duration(left)} left"
        return "Receiving", detail, got / length if length else 1.0

    def notes(self) -> list:
        """The checks so far, one short line each, for the progress screen."""
        if not self._data:
            return ["Contact open. Check the wiring."] if self._contact_open else []
        counts = f"{self._good_packets} packets OK, {self._damaged_copies} damaged, {self._lost} lost"
        if self._header():
            return [counts, "CRC-32 is checked at the end"]
        if self._may_have_header():
            return [counts]
        return [counts, "No header: can't check it's whole"]

    def preview(self) -> str:
        """The latest text to arrive. Header bytes and control characters don't show."""
        if self._may_have_header() and self._header() is None:
            return ""
        start = _HEADER_BYTES if self._header() else 0
        tail = bytes(self._data[start:])[-_PREVIEW_BYTES:]
        text = tail.decode("utf-8", errors="replace")
        return "".join(char if char.isprintable() else " " for char in text)


def decode_text(data: bytes) -> str:
    """Decode a received file. Windows tools often save text as UTF-16 with a BOM."""
    if len(data) > 2 and data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8")


def decoder_segments(data: bytes) -> list:
    """Turn a received file into what DecodeQR.add_data expects, one QR at a time.

    A binary PSBT is the smallest thing to send, so it becomes base64 here. An
    animated UR saved with one part per line is fed line by line. Copy damage is
    repaired first, except in a sign-message request, whose text gets signed.
    """
    from seedsigner.message_crypto.sanitize import clean_text, split_base64

    if data.startswith(b"psbt\xff"):
        return [base64.b64encode(data).decode("ascii")]
    try:
        original = decode_text(data)
    except UnicodeDecodeError:
        return [data]
    text = clean_text(original)
    if text.startswith("signmessage"):
        return [original.lstrip("\ufeff").strip()]
    parts = split_base64(text)
    if "".join(parts).startswith("cHNidP"):
        return ["".join(parts)]
    if len(parts) > 1 and parts[0].lower().startswith("ur:"):
        return parts
    return [text]
