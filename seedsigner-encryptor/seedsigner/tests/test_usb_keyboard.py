"""USB keyboard key translation and typed-text editing.

Does not open /dev/input or import RPi.GPIO. KeyTranslator is fed raw evdev
values and records what it would pass to desktop_env.
"""

from seedsigner.hardware import desktop_env
from seedsigner.hardware.usb_keyboard import KeyTranslator, char_for

EV_KEY = 1
KEY_A = 30
KEY_1 = 2
KEY_LEFTSHIFT = 42
KEY_CAPSLOCK = 58
KEY_UP = 103
KEY_ENTER = 28
KEY_BACKSPACE = 14
KEY_F3 = 61


def _recorder():
    presses, releases = [], []
    translator = KeyTranslator(
        press=lambda keysym, char, shift, control, clipboard: presses.append((keysym, char, shift)),
        release=releases.append,
    )
    return translator, presses, releases


def test_char_for_us_layout():
    assert char_for(KEY_A, shift=False, caps=False) == "a"
    assert char_for(KEY_A, shift=True, caps=False) == "A"
    assert char_for(KEY_A, shift=False, caps=True) == "A"
    assert char_for(KEY_A, shift=True, caps=True) == "a"
    assert char_for(KEY_1, shift=True, caps=True) == "!"
    assert char_for(KEY_UP, shift=False, caps=False) == ""


def test_shift_applies_while_held():
    translator, presses, _releases = _recorder()
    translator.handle(EV_KEY, KEY_LEFTSHIFT, 1)
    translator.handle(EV_KEY, KEY_A, 1)
    translator.handle(EV_KEY, KEY_LEFTSHIFT, 0)
    translator.handle(EV_KEY, KEY_A, 1)
    assert presses == [("", "A", True), ("", "a", False)]


def test_capslock_toggles_letters():
    translator, presses, _releases = _recorder()
    translator.handle(EV_KEY, KEY_CAPSLOCK, 1)
    translator.handle(EV_KEY, KEY_CAPSLOCK, 0)
    translator.handle(EV_KEY, KEY_A, 1)
    assert presses == [("", "A", False)]


def test_joystick_keys_press_and_release_without_repeat():
    translator, presses, releases = _recorder()
    translator.handle(EV_KEY, KEY_UP, 1)
    translator.handle(EV_KEY, KEY_UP, 2)
    translator.handle(EV_KEY, KEY_UP, 0)
    translator.handle(EV_KEY, KEY_F3, 1)
    translator.handle(EV_KEY, KEY_ENTER, 1)
    assert presses == [("Up", "", False), ("F3", "", False), ("Return", "", False)]
    assert releases == ["Up"]


def test_non_key_events_are_ignored():
    translator, presses, releases = _recorder()
    translator.handle(4, 4, 458756)
    translator.handle(0, 0, 0)
    assert presses == [] and releases == []


def test_backspace_repeats_while_held():
    translator, presses, _releases = _recorder()
    translator.handle(EV_KEY, KEY_BACKSPACE, 1)
    translator.handle(EV_KEY, KEY_BACKSPACE, 2)
    assert presses == [("BackSpace", "", False), ("BackSpace", "", False)]


def test_apply_typed_text_handles_backspace():
    assert desktop_env.apply_typed_text("ab", "c\b\bd") == "ad"
    assert desktop_env.apply_typed_text("", "\b\bx") == "x"


def test_capture_queues_text_and_backspace_but_not_joystick():
    desktop_env.drain_pasted_text()
    desktop_env.set_capture_text(True)
    try:
        desktop_env.note_key_press("h", "h", False, False, "")
        desktop_env.note_key_press("i", "i", False, False, "")
        desktop_env.note_key_press("BackSpace", "", False, False, "")
        assert desktop_env.drain_pasted_text() == "hi\b"
    finally:
        desktop_env.set_capture_text(False)
    desktop_env.note_key_press("BackSpace", "", False, False, "")
    assert desktop_env.drain_pasted_text() == ""


def test_joystick_key_holds_the_matching_pin():
    desktop_env.note_key_press("Up", "", False, False, "")
    try:
        assert desktop_env.key_pin_held(31) is True
    finally:
        desktop_env.note_key_release("Up")
    assert desktop_env.key_pin_held(31) is False
