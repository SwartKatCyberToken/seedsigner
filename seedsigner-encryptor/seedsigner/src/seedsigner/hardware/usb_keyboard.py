"""USB keyboard next to the GPIO joystick on a Raspberry Pi.

Does not replace the joystick or the three buttons; both work at the same
time. main.py --usb-keyboard is the caller, before HardwareButtons is used.
A background thread reads /dev/input/event* (Linux evdev, standard library
only) and passes keys to desktop_env.note_key_press, so the Pi and the
desktop window share one key map: arrows and Enter are the joystick, F1-F3
are the buttons, printable keys type only on a message keyboard screen.

The layout is US. Each keyboard is grabbed (EVIOCGRAB) so keystrokes do not
also reach the Linux console login on tty1. The pi user needs read access to
/dev/input, which the default "input" group membership gives.
"""

import glob
import logging
import os
import select
import struct
import threading
import time

from seedsigner.hardware.desktop_env import (
    install_paste_hook,
    key_pin_held,
    note_key_press,
    note_key_release,
    release_all_keys,
)

logger = logging.getLogger(__name__)

# struct input_event: timeval (two native longs), __u16 type, __u16 code, __s32 value.
_EVENT = struct.Struct("llHHi")
_EV_KEY = 1
_RELEASE, _PRESS, _REPEAT = 0, 1, 2
# _IOW('E', 0x90, int) from linux/input.h.
_EVIOCGRAB = 0x40044590
_RESCAN_SECONDS = 2.0

_SHIFT_CODES = {42, 54}
_CONTROL_CODES = {29, 97}
_CAPSLOCK = 58

# Linux key codes that are joystick or button keys, as desktop Tk keysyms.
_KEYSYMS = {
    103: "Up",
    108: "Down",
    105: "Left",
    106: "Right",
    28: "Return",
    96: "Return",
    59: "F1",
    60: "F2",
    61: "F3",
    14: "BackSpace",
}

# Linux key code -> (unshifted, shifted) on a US layout.
_CHARS = {
    2: ("1", "!"), 3: ("2", "@"), 4: ("3", "#"), 5: ("4", "$"), 6: ("5", "%"),
    7: ("6", "^"), 8: ("7", "&"), 9: ("8", "*"), 10: ("9", "("), 11: ("0", ")"),
    12: ("-", "_"), 13: ("=", "+"),
    16: ("q", "Q"), 17: ("w", "W"), 18: ("e", "E"), 19: ("r", "R"), 20: ("t", "T"),
    21: ("y", "Y"), 22: ("u", "U"), 23: ("i", "I"), 24: ("o", "O"), 25: ("p", "P"),
    26: ("[", "{"), 27: ("]", "}"),
    30: ("a", "A"), 31: ("s", "S"), 32: ("d", "D"), 33: ("f", "F"), 34: ("g", "G"),
    35: ("h", "H"), 36: ("j", "J"), 37: ("k", "K"), 38: ("l", "L"),
    39: (";", ":"), 40: ("'", '"'), 41: ("`", "~"), 43: ("\\", "|"),
    44: ("z", "Z"), 45: ("x", "X"), 46: ("c", "C"), 47: ("v", "V"), 48: ("b", "B"),
    49: ("n", "N"), 50: ("m", "M"),
    51: (",", "<"), 52: (".", ">"), 53: ("/", "?"),
    57: (" ", " "),
}


class KeyTranslator:
    """Turns evdev key events into note_key_press and note_key_release calls."""

    def __init__(self, press=note_key_press, release=note_key_release):
        self._press = press
        self._release = release
        self._shift = set()
        self._control = set()
        self._caps = False

    def handle(self, event_type: int, code: int, value: int) -> None:
        if event_type != _EV_KEY:
            return
        if code in _SHIFT_CODES:
            self._track(self._shift, code, value)
            return
        if code in _CONTROL_CODES:
            self._track(self._control, code, value)
            return
        if code == _CAPSLOCK:
            if value == _PRESS:
                self._caps = not self._caps
            return
        keysym = _KEYSYMS.get(code)
        if value == _RELEASE:
            if keysym:
                self._release(keysym)
            return
        if value == _REPEAT and keysym and keysym != "BackSpace":
            # A held joystick key stays pressed; HardwareButtons does its own repeat.
            return
        char = char_for(code, bool(self._shift), self._caps)
        self._press(keysym or "", char, bool(self._shift), bool(self._control), "")

    @staticmethod
    def _track(held: set, code: int, value: int) -> None:
        if value == _RELEASE:
            held.discard(code)
        else:
            held.add(code)


def char_for(code: int, shift: bool, caps: bool) -> str:
    """The character a US keyboard types for this key code, or "" for none."""
    pair = _CHARS.get(code)
    if pair is None:
        return ""
    lower, upper = pair
    if lower.isalpha():
        return upper if shift != caps else lower
    return upper if shift else lower


def install_usb_keyboard() -> None:
    """Let a USB keyboard act as the joystick and type message text.

    Call before HardwareButtons reads input. Real GPIO keeps working: a pin
    reads LOW when the physical button or the matching keyboard key is down.
    """
    import RPi.GPIO as GPIO

    gpio_input = GPIO.input

    def input_with_keyboard(pin):
        if key_pin_held(pin):
            return GPIO.LOW
        return gpio_input(pin)

    GPIO.input = input_with_keyboard
    install_paste_hook()
    thread = threading.Thread(target=_read_forever, name="seedsigner-usb-keyboard", daemon=True)
    thread.start()


def _read_forever() -> None:
    translator = KeyTranslator()
    devices = {}
    refused = set()
    next_scan = 0.0
    while True:
        now = time.monotonic()
        if now >= next_scan:
            _open_new_devices(devices, refused)
            next_scan = now + _RESCAN_SECONDS
        if not devices:
            select.select([], [], [], _RESCAN_SECONDS)
            continue
        ready, _w, _x = select.select(list(devices), [], [], _RESCAN_SECONDS)
        for fd in ready:
            try:
                data = os.read(fd, _EVENT.size * 64)
            except OSError:
                _close_device(devices, fd)
                continue
            if not data:
                _close_device(devices, fd)
                continue
            for offset in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                _sec, _usec, event_type, code, value = _EVENT.unpack_from(data, offset)
                translator.handle(event_type, code, value)


def _open_new_devices(devices: dict, refused: set) -> None:
    """Open event devices not yet read. refused keeps one warning per path."""
    known = set(devices.values())
    for path in sorted(glob.glob("/dev/input/event*")):
        if path in known:
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            if path not in refused:
                logger.warning("cannot open %s: %s", path, exc)
                refused.add(path)
            continue
        refused.discard(path)
        try:
            import fcntl
            fcntl.ioctl(fd, _EVIOCGRAB, 1)
        except OSError:
            logger.info("could not grab %s; keys may also reach the console", path)
        devices[fd] = path
        logger.info("reading keyboard input from %s", path)


def _close_device(devices: dict, fd: int) -> None:
    path = devices.pop(fd, None)
    try:
        os.close(fd)
    except OSError:
        pass
    release_all_keys()
    logger.info("keyboard input %s closed", path)
