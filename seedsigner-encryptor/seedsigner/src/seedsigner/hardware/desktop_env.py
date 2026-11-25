"""Desktop window stand-in for the SeedSigner display and joystick.

Does not derive keys or replace the Pi drivers unless install_desktop_hardware
runs before those drivers are imported. main.py --desktop is the caller.
Arrow keys and Enter are the joystick; F3 confirms a keyboard screen.
Printable keys are delivered only while a message keyboard asks for them.
Backspace is queued as "\\b" and removes one character.

usb_keyboard.py feeds a Pi USB keyboard through the same note_key_press
and note_key_release calls, so both modes share one key map.
"""

import queue
import sys
import threading
import types

_pressed = set()
_lock = threading.Lock()
_paste = []
_capture_text = False
_image_queue = queue.Queue(maxsize=2)

# BCM-style board pins from HardwareButtons on a 40-pin header.
_JOYSTICK_PINS = {
    "Up": 31,
    "Down": 35,
    "Left": 29,
    "Right": 37,
    "Return": 33,
    "F1": 40,
    "F2": 38,
    "F3": 36,
}


def set_capture_text(enabled: bool) -> None:
    """When enabled, printable desktop keys are queued as message text."""
    global _capture_text
    _capture_text = enabled


def drain_pasted_text() -> str:
    """Return and clear text typed or pasted into the desktop window."""
    with _lock:
        if not _paste:
            return ""
        text = "".join(_paste)
        _paste.clear()
        return text


def apply_typed_text(current: str, typed: str) -> str:
    """Append typed text to current. Each "\\b" removes the last character."""
    for char in typed:
        if char == "\b":
            current = current[:-1]
        else:
            current += char
    return current


def key_pin_held(pin: int) -> bool:
    """True while a keyboard key mapped to this joystick or button pin is down."""
    with _lock:
        return pin in _pressed


def release_all_keys() -> None:
    """Forget held keys. Called when a USB keyboard is unplugged mid-press."""
    with _lock:
        _pressed.clear()


def install_desktop_hardware() -> None:
    """Install the GPIO stub, display, and paste hook. Call before other imports."""
    _install_gpio_module()
    _install_display()
    install_paste_hook()


def _install_gpio_module() -> None:
    gpio = types.ModuleType("RPi.GPIO")
    gpio.RPI_INFO = {"P1_REVISION": 3}
    gpio.BOARD = "BOARD"
    gpio.BCM = "BCM"
    gpio.IN = "IN"
    gpio.OUT = "OUT"
    gpio.PUD_UP = "PUD_UP"
    gpio.PUD_DOWN = "PUD_DOWN"
    gpio.LOW = 0
    gpio.HIGH = 1
    gpio.setmode = lambda mode: None
    gpio.setup = lambda *args, **kwargs: None
    gpio.cleanup = lambda *args, **kwargs: None
    gpio.setwarnings = lambda *args, **kwargs: None
    gpio.input = _gpio_input
    package = types.ModuleType("RPi")
    package.GPIO = gpio
    sys.modules["RPi"] = package
    sys.modules["RPi.GPIO"] = gpio


def _gpio_input(pin: int) -> int:
    return 0 if key_pin_held(pin) else 1


def _install_display() -> None:
    from seedsigner.hardware.displays.display_driver import DisplayDriverFactory
    from seedsigner.hardware.desktop_display import DesktopDisplay

    def instantiate(cls, display_type: str = "", width: int = 240, height: int = 240):
        return DesktopDisplay(_width=240, _height=240)

    DisplayDriverFactory.instantiate_display_driver = classmethod(instantiate)


def install_paste_hook() -> None:
    """Let HardwareButtons.wait_for return PASTE_READY when text is queued."""
    from seedsigner.hardware.buttons import HardwareButtons, HardwareButtonsConstants

    def paste_ready(self):
        with _lock:
            if _capture_text and _paste:
                return HardwareButtonsConstants.PASTE_READY
        return None

    HardwareButtons._desktop_paste_ready = paste_ready


def note_key_press(keysym: str, char: str, shift: bool, control: bool, clipboard: str) -> None:
    """Record one desktop key. clipboard is used for Control-v."""
    if _capture_text and control and keysym.lower() == "v":
        _append(clipboard)
        return
    if _capture_text and shift and keysym == "Return":
        _append("\n")
        return
    if _capture_text and keysym == "BackSpace":
        _append("\b")
        return
    if _capture_text and char and char.isprintable():
        _append(char)
        return
    pin = _JOYSTICK_PINS.get(keysym)
    if pin is None:
        return
    with _lock:
        _pressed.add(pin)


def note_key_release(keysym: str) -> None:
    pin = _JOYSTICK_PINS.get(keysym)
    if pin is None:
        return
    with _lock:
        _pressed.discard(pin)


def _append(text: str) -> None:
    if text:
        with _lock:
            _paste.append(text)


def push_frame(image) -> None:
    """Keep only the newest frame so a slow window does not queue up."""
    if image is None:
        return
    try:
        while True:
            _image_queue.get_nowait()
    except queue.Empty:
        pass
    _image_queue.put(image.copy())


def wait_frame(timeout: float = 0.05):
    try:
        return _image_queue.get(timeout=timeout)
    except queue.Empty:
        return None
