"""Run one message operation and present the result.

Does not collect input. MessageExecuteView reads controller.message_flow,
which already holds the seed, algorithm, and peer envelope. Private keys
stay in the MessageKeys cache. Plaintext is shown on screen and then dropped
from the flow. It is not written to the SD card.
"""

from seedsigner.gui.components import GUIConstants, SeedSignerIconConstants
from seedsigner.gui.screens.screen import (
    RET_CODE__BACK_BUTTON,
    ButtonListScreen,
    ButtonOption,
    LargeIconStatusScreen,
    QRDisplayScreen,
)
from seedsigner.hardware import usb_relay
from seedsigner.message_crypto.codec import dumps
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.fingerprint import fingerprint, kind, screen_lines
from seedsigner.message_crypto.flow import (
    ACTION_DECRYPT,
    ACTION_ENCRYPT,
    ACTION_PUBLIC,
    ACTION_SIGN,
    ACTION_VERIFY,
    result_qr_note,
)
from seedsigner.message_crypto.keys import keys_for_seed
from seedsigner.message_crypto.operations import decrypt_with, encrypt_for, export_public, sign_with, verify_with
from seedsigner.models.message_qr import MessageAnimatedQrEncoder
from seedsigner.models.settings_definition import SettingsConstants
from seedsigner.views.message_nav import message_error
from seedsigner.views.view import BackStackView, Destination, MainMenuView, View


class MessageExecuteView(View):
    def run(self):
        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        # Key derivation (first use of a seed) and RSA/PGP math take a while on
        # a Pi Zero; show a spinner so the device does not look frozen.
        from seedsigner.gui.screens.screen import LoadingScreenThread
        self.loading_screen = LoadingScreenThread(text=working_text(flow["action"]))
        self.loading_screen.start()
        try:
            flow["result"] = _execute(flow)
        except MessageCryptoError as exc:
            return message_error(str(exc))
        finally:
            self.loading_screen.stop()
        # skip_current_view keeps Back from landing here and immediately
        # opening the same result screen again.
        if flow["action"] in (ACTION_PUBLIC, ACTION_SIGN, ACTION_ENCRYPT):
            return Destination(MessageResultFormatView, skip_current_view=True)
        if flow["action"] == ACTION_DECRYPT:
            return Destination(MessagePlaintextView, skip_current_view=True)
        return Destination(MessageVerifyResultView, skip_current_view=True)


class MessageResultFormatView(View):
    """Choose on-screen text, a QR, or the USB relay for a public key, signature,
    or ciphertext. The relay carries the same text as Show text. Decrypted
    plaintext has no such choice: it stays on the screen."""

    FINGERPRINT = ButtonOption("Fingerprint")
    TEXT = ButtonOption("Show text")
    QR = ButtonOption("Show QR")
    RELAY = ButtonOption("Send by USB")

    def run(self):
        flow = self.controller.message_flow
        if not flow or not isinstance(flow.get("result"), dict):
            return message_error("There is no result to display")
        button_data = [self.TEXT, self.QR]
        if flow["action"] == ACTION_PUBLIC:
            button_data.insert(0, self.FINGERPRINT)
        if usb_relay.attached():
            button_data.append(self.RELAY)
        selected = self.run_screen(
            ButtonListScreen,
            title=result_title(flow["action"]),
            button_data=button_data,
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        if button_data[selected] == self.FINGERPRINT:
            return Destination(MessagePublicFingerprintView)
        if button_data[selected] == self.TEXT:
            return Destination(MessageResultTextView)
        if button_data[selected] == self.RELAY:
            from seedsigner.views.relay_views import RelaySendView

            def clear_flow():
                self.controller.message_flow = None
                self.controller.message_scanned = None

            return Destination(RelaySendView, view_args=dict(
                data=result_text(flow["result"]).encode("utf-8") + b"\n",
                title=result_title(flow["action"]),
                on_done=clear_flow,
            ))
        return Destination(MessageQrView)


class MessagePublicFingerprintView(View):
    """Show the public key's fingerprint. Back returns to the format list."""

    def run(self):
        flow = self.controller.message_flow
        document = flow.get("result") if flow else None
        if not isinstance(document, dict):
            return message_error("There is no public key to show")
        try:
            digits = fingerprint(document)
        except MessageCryptoError as exc:
            return message_error(str(exc))
        own = flow.get("peer") is None
        from seedsigner.views.message_collect_views import fingerprint_screen
        self.run_screen(
            fingerprint_screen(),
            title="Your key" if own else "Their key",
            kind=kind(document),
            fingerprint_lines=screen_lines(digits),
            note=(
                "Read it to people who use your key."
                if own else "Compare it with the one its owner gives you."
            ),
            button_data=[ButtonOption("Done")],
        )
        return Destination(BackStackView)


class MessageResultTextView(View):
    """Scroll the result as several lines. Armor is shown for PGP."""

    def run(self):
        flow = self.controller.message_flow
        document = flow.get("result") if flow else None
        if not isinstance(document, dict):
            return message_error("There is no result to display")
        selected = self.run_screen(
            _scroll_screen(),
            title=result_title(flow["action"]),
            body=result_text(document),
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        self._clear()
        return Destination(MainMenuView, clear_history=True)

    def _clear(self) -> None:
        self.controller.message_flow = None
        self.controller.message_scanned = None


class MessageQrView(View):
    """Say what the QR contains, then show the animated ssmsg1 code."""

    SHOW = ButtonOption("Show QR")

    def run(self):
        flow = self.controller.message_flow
        if not flow or not isinstance(flow.get("result"), dict):
            return message_error("There is no result to display")
        selected = self.run_screen(
            LargeIconStatusScreen,
            title="QR code",
            status_headline="Next screen",
            text=result_qr_note(flow["action"]),
            button_data=[self.SHOW],
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        encoder = MessageAnimatedQrEncoder(
            payload=dumps(flow["result"]),
            qr_density=self.settings.get_value(SettingsConstants.SETTING__QR_DENSITY),
            qr_speed=self.settings.get_value(SettingsConstants.SETTING__MESSAGE_QR_SPEED),
        )
        self.run_screen(QRDisplayScreen, qr_encoder=encoder)
        self._clear()
        return Destination(MainMenuView, clear_history=True)

    def _clear(self) -> None:
        self.controller.message_flow = None
        self.controller.message_scanned = None


class MessagePlaintextView(View):
    """Scroll decrypted text. The flow is cleared when the page closes."""

    def run(self):
        flow = self.controller.message_flow
        text = flow.get("result") if flow else None
        if not isinstance(text, str) or text == "":
            return message_error("There is no plaintext to show")
        self.run_screen(_scroll_screen(), title="Decrypted", body=text)
        self.controller.message_flow = None
        self.controller.message_scanned = None
        return Destination(MainMenuView, clear_history=True)


class MessageVerifyResultView(View):
    def run(self):
        flow = self.controller.message_flow
        result = flow.get("result") if flow else None
        if not isinstance(result, dict):
            return message_error("There is no verification result")
        valid = bool(result.get("valid"))
        message = result.get("msg") if isinstance(result.get("msg"), str) else ""
        preview = message if len(message) <= 120 else message[:117] + "..."
        detail = "Matches the supplied public key." if valid else "Does not match the supplied public key."
        self.run_screen(
            LargeIconStatusScreen,
            title="Verify",
            status_icon_name=SeedSignerIconConstants.SUCCESS if valid else SeedSignerIconConstants.ERROR,
            status_color=GUIConstants.SUCCESS_COLOR if valid else GUIConstants.ERROR_COLOR,
            status_headline="Valid signature" if valid else "Invalid signature",
            text=preview + "\n\n" + detail,
            button_data=[ButtonOption("Done")],
            show_back_button=False,
        )
        self.controller.message_flow = None
        self.controller.message_scanned = None
        return Destination(MainMenuView, clear_history=True)


def working_text(action: str) -> str:
    return {
        ACTION_ENCRYPT: "Encrypting...",
        ACTION_DECRYPT: "Decrypting...",
        ACTION_SIGN: "Signing...",
        ACTION_VERIFY: "Verifying...",
        ACTION_PUBLIC: "Making key...",
    }.get(action, "Working...")


def result_title(action: str) -> str:
    if action == ACTION_SIGN:
        return "Signature"
    if action == ACTION_ENCRYPT:
        return "Encrypted"
    return "Public key"


def result_text(document: dict) -> str:
    """Armor for PGP, which holds the message when signed. JSON otherwise."""
    armor = document.get("armor")
    return armor if isinstance(armor, str) else dumps(document)


def _scroll_screen():
    from seedsigner.gui.screens.message_screens import MessageScrollScreen
    return MessageScrollScreen


def _execute(flow: dict):
    action = flow["action"]
    if action == ACTION_ENCRYPT:
        return encrypt_for(None, flow["alg"], flow["peer"], flow["text"])
    if action == ACTION_VERIFY:
        return {
            "valid": verify_with(flow["peer"], flow["envelope"]),
            "msg": flow["envelope"].get("msg"),
        }
    if action == ACTION_PUBLIC and flow.get("peer") is not None:
        return flow["peer"]
    if flow.get("seed") is None:
        raise MessageCryptoError("this action needs a loaded seed")
    keys = keys_for_seed(flow["seed"].seed_bytes)
    if action == ACTION_PUBLIC:
        return export_public(keys, flow["alg"])
    if action == ACTION_SIGN:
        return sign_with(keys, flow["alg"], flow["text"])
    if action == ACTION_DECRYPT:
        return decrypt_with(keys, flow["envelope"])
    raise MessageCryptoError(f"unknown message action {action}")
