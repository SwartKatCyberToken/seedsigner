"""Collect a message, envelope, or public key by keyboard, QR, or USB relay.

Does not run the cryptographic operation. message_crypto.flow.accept_typed
and accept_document decide whether the input matches the current expect
value. Scanning uses ScanView's decoder and accepts only ssmsg1 frames. Relay
text is handled exactly like typed text.
"""

from seedsigner.gui.components import GUIConstants, SeedSignerIconConstants
from seedsigner.gui.screens.screen import (
    RET_CODE__BACK_BUTTON,
    ButtonListScreen,
    ButtonOption,
    LargeIconStatusScreen,
)
from seedsigner.hardware import usb_relay
from seedsigner.hardware.desktop_env import set_capture_text
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.fingerprint import fingerprint, kind, screen_lines
from seedsigner.message_crypto.flow import (
    EXPECT_ENVELOPE,
    EXPECT_PEER,
    EXPECT_SIGNATURE,
    EXPECT_TEXT,
    accept_copied,
    accept_document,
    accept_typed,
    advance,
)
from seedsigner.message_crypto.key_catalog import remember_contact
from seedsigner.views.message_nav import destination_for, message_error
from seedsigner.views.scan_views import ScanView
from seedsigner.views.view import BackStackView, Destination, View


class MessageInputChoiceView(View):
    KEYBOARD = ButtonOption("Keyboard")
    ENTER = ButtonOption("Enter key")
    SCAN = ButtonOption("Scan QR")
    RELAY = ButtonOption("Receive by USB")

    def run(self):
        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        choice = choice_for(flow)
        if choice["explain"]:
            selected = self.run_screen(
                LargeIconStatusScreen,
                title=choice["title"],
                status_headline=choice["headline"],
                text=choice["text"],
                status_icon_name=SeedSignerIconConstants.INFO,
                status_icon_size=28,
                status_color=GUIConstants.INFO_COLOR,
                button_data=choice["buttons"],
            )
        else:
            selected = self.run_screen(
                ButtonListScreen,
                title=choice["title"],
                button_data=choice["buttons"],
            )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        chosen = choice["buttons"][selected]
        if chosen == self.SCAN:
            return Destination(MessageScanView)
        if chosen == self.RELAY:
            return Destination(MessageRelayReceiveView)
        return Destination(MessageTextEntryView)


class MessageRelayReceiveView(View):
    """Take one message from the USB relay, handled like typed text."""

    def run(self):
        from seedsigner.views.relay_views import receive_from_relay, relay_error

        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        try:
            data = receive_from_relay(self, title=entry_title(flow.get("expect")))
        except usb_relay.RelayError as exc:
            destination = relay_error(str(exc))
            destination.skip_current_view = True
            return destination
        if data is None:
            return Destination(BackStackView)
        try:
            step = accept_copied(flow, usb_relay.decode_text(data))
        except UnicodeDecodeError:
            return message_error("The relay data is not UTF-8 text")
        except MessageCryptoError as exc:
            return message_error(str(exc))
        destination = destination_for(step)
        # Back from the next screen should not start listening again.
        destination.skip_current_view = True
        return destination


class MessageTextEntryView(View):
    def run(self):
        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        title = entry_title(flow.get("expect"))
        set_capture_text(True)
        try:
            entered = self.run_screen(
                _keyboard_screen(),
                title=title,
            )
        finally:
            set_capture_text(False)
        if entered == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        try:
            step = accept_typed(flow, entered)
        except MessageCryptoError as exc:
            return message_error(str(exc))
        return destination_for(step)


class MessageFingerprintView(View):
    """Show a key that just came in by its fingerprint, to compare with its owner's.

    The key is kept as a contact for this session only once it matches. Doesn't
    match ends the flow without using it.
    """

    MATCHES = ButtonOption("It matches")
    NO_MATCH = ButtonOption("Doesn't match")

    def run(self):
        flow = self.controller.message_flow
        peer = flow.get("peer") if flow else None
        if not isinstance(peer, dict):
            return message_error("There is no public key to check")
        try:
            digits = fingerprint(peer)
        except MessageCryptoError as exc:
            return message_error(str(exc))
        button_data = [self.MATCHES, self.NO_MATCH]
        selected = self.run_screen(
            fingerprint_screen(),
            title="Check their key",
            kind=kind(peer),
            fingerprint_lines=screen_lines(digits),
            note="Compare it with the one its owner gives you.",
            button_data=button_data,
            # One click without reading mustn't accept the key.
            selected_button=button_data.index(self.NO_MATCH),
        )
        if selected == RET_CODE__BACK_BUTTON:
            flow["peer"] = None
            return Destination(BackStackView)
        if button_data[selected] == self.NO_MATCH:
            return message_error(
                "The key wasn't used or kept. Get it again from its owner.",
                "Key doesn't match",
            )
        self.controller.message_contacts = remember_contact(self.controller.message_contacts, peer)
        return destination_for(advance(flow, "fingerprint"))


class MessageReviewView(View):
    """Show the exact UTF-8 bytes that encrypt or sign will use."""

    CONTINUE = ButtonOption("Continue")
    CANCEL = ButtonOption("Cancel")

    def run(self):
        flow = self.controller.message_flow
        if not flow or not flow.get("text"):
            return message_error("No message to confirm")
        text = flow["text"]
        raw = text.encode("utf-8")
        preview = text if len(text) <= 120 else text[:117] + "..."
        button_data = [self.CONTINUE, self.CANCEL]
        selected = self.run_screen(
            LargeIconStatusScreen,
            title="Confirm bytes",
            status_headline=f"{len(raw)} UTF-8 bytes",
            text=preview,
            button_data=button_data,
        )
        if selected == RET_CODE__BACK_BUTTON or button_data[selected] == self.CANCEL:
            return Destination(BackStackView)
        return destination_for(advance(flow, "review"))


class MessageScanView(ScanView):
    """ScanView that accepts an ssmsg1 message QR, or a QR holding text as
    ur:bytes or plain text (such as an armored PGP key from another PGP app,
    or anything pasted into a QR generator app)."""

    from seedsigner.helpers.l10n import mark_for_translation as _mft
    instructions_text = _mft("Scan message QR")
    invalid_qr_type_message = _mft("Expected a message or PGP text QR")
    accepts_message_text = True
    # MessageInputChoiceView already offers the relay.
    allow_relay = False

    def __init__(self):
        from seedsigner.models.decode_qr import DecodeQR

        super().__init__()
        self.decoder = DecodeQR(wordlist_language_code=self.wordlist_language_code, accept_plain_text=True)
        self.instructions_text = scan_prompt(self.controller.message_flow or {})

    @property
    def is_valid_qr_type(self):
        return self.decoder.is_message_crypto or self.decoder.is_message_text


class MessageIngestQrView(View):
    """Apply the QR DecodeQR just stored on the controller."""

    def run(self):
        document = self.controller.message_scanned
        flow = self.controller.message_flow
        if not flow:
            return message_error(
                "Open the message menu before using this QR.",
                "No message in progress",
            )
        try:
            if isinstance(document, str):
                # Text from a QR: a message, JSON, or PGP armor.
                step = accept_copied(flow, document)
            elif isinstance(document, dict):
                step = accept_document(flow, document)
            else:
                return message_error("Message QR did not contain an envelope")
        except MessageCryptoError as exc:
            return message_error(str(exc))
        return destination_for(step)


def choice_for(flow: dict) -> dict:
    """Title and buttons for keyboard, QR, or relay entry. Key picking is a separate list."""
    expect = flow.get("expect")
    relay = [MessageInputChoiceView.RELAY] if usb_relay.attached() else []
    if expect == EXPECT_PEER:
        return {
            "title": "Their public key",
            "buttons": [MessageInputChoiceView.ENTER, MessageInputChoiceView.SCAN] + relay,
            "explain": False,
        }
    if expect == EXPECT_ENVELOPE:
        title = "Ciphertext"
    elif expect == EXPECT_SIGNATURE:
        title = "Signature"
    else:
        title = "Plaintext"
    return {
        "title": title,
        "buttons": [MessageInputChoiceView.KEYBOARD, MessageInputChoiceView.SCAN] + relay,
        "explain": False,
    }



def entry_title(expect: str) -> str:
    if expect == EXPECT_PEER:
        return "Their public key"
    if expect == EXPECT_ENVELOPE:
        return "Paste ciphertext"
    if expect == EXPECT_SIGNATURE:
        return "Paste signature"
    return "Message"


def scan_prompt(flow: dict) -> str:
    expect = flow.get("expect")
    if expect == EXPECT_PEER:
        return "Scan their public key"
    if expect == EXPECT_ENVELOPE:
        return "Scan the ciphertext"
    if expect == EXPECT_SIGNATURE:
        return "Scan the signature"
    return "Scan message QR"


def fingerprint_screen():
    from seedsigner.gui.screens.message_screens import MessageFingerprintScreen
    return MessageFingerprintScreen


def _keyboard_screen():
    from seedsigner.gui.screens.message_screens import MessageKeyboardScreen
    return MessageKeyboardScreen
