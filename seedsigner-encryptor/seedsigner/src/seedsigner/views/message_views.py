"""Message menu, algorithm choice, and the key list.

Does not encrypt or sign. Those views live in message_run_views. The menu is
reached from MainMenuView by one Right on Seeds or Settings, or one Down on
Tools or Settings. Left or Right on this list returns Home. Bitcoin seed
loading stays on the existing Seeds menu. Encrypt and verify pick a contact
public key. Sign and decrypt pick an own seed.
"""

from seedsigner.gui.components import FontAwesomeIconConstants, GUIConstants, SeedSignerIconConstants
from seedsigner.gui.screens.screen import (
    RET_CODE__BACK_BUTTON,
    ButtonListScreen,
    ButtonOption,
    LargeIconStatusScreen,
)
from seedsigner.hardware import usb_relay
from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    same_key_type,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.flow import (
    ACTION_ENCRYPT,
    ACTION_PUBLIC,
    ACTION_SIGN,
    ACTION_VERIFY,
    EXPECT_PEER,
    advance,
    encrypt_notice,
    ensure_bip39,
    new_flow,
)
from seedsigner.message_crypto.key_catalog import (
    ROLE_IMPORTED,
    ROLE_OWN,
    ROLE_PRELOADED,
    choices_for,
)
from seedsigner.models.settings import SettingsConstants
from seedsigner.views.message_nav import destination_for, message_error
from seedsigner.views.view import BackStackView, Destination, View


class MessageMenuView(View):
    ENCRYPT = ButtonOption("Encrypt", FontAwesomeIconConstants.LOCK)
    DECRYPT = ButtonOption("Decrypt", FontAwesomeIconConstants.UNLOCK)
    SIGN = ButtonOption("Sign", FontAwesomeIconConstants.FILE_SIGNATURE)
    VERIFY = ButtonOption("Verify", FontAwesomeIconConstants.CIRCLE_CHECK)
    PUBLIC = ButtonOption("View Public Key", FontAwesomeIconConstants.ADDRESS_BOOK)

    def run(self):
        button_data = [self.ENCRYPT, self.DECRYPT, self.SIGN, self.VERIFY, self.PUBLIC]
        selected = self.run_screen(
            ButtonListScreen,
            title="Messages",
            button_data=button_data,
            show_back_button=False,
            show_power_button=False,
            exit_on_horizontal=True,
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        self.controller.message_flow = new_flow(_action_for(button_data[selected]))
        return destination_for(advance(self.controller.message_flow, "menu"))


class MessageEncryptNoticeView(View):
    """Say that encryption needs their key before the keyboard is opened."""

    CONTINUE = ButtonOption("Continue")

    def run(self):
        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        notice = encrypt_notice()
        selected = self.run_screen(
            LargeIconStatusScreen,
            title=notice["title"],
            status_headline=notice["headline"],
            text=notice["text"],
            status_icon_name=SeedSignerIconConstants.INFO,
            status_icon_size=28,
            status_color=GUIConstants.INFO_COLOR,
            button_data=[self.CONTINUE],
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        return destination_for(advance(flow, "notice"))


class MessageAlgorithmView(View):
    PGP = ButtonOption("PGP")
    ML_KEM = ButtonOption("ML-KEM (quantum)")
    ML_DSA = ButtonOption("ML-DSA (quantum)")
    RSA_ENCRYPT = ButtonOption("RSA encrypt")
    RSA_SIGN = ButtonOption("RSA sign")

    def run(self):
        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        button_data = _algorithms_for(flow["action"])
        selected = self.run_screen(
            ButtonListScreen,
            title="Algorithm",
            button_data=button_data,
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        flow["alg"] = _alg_for(button_data[selected], flow["action"])
        return destination_for(advance(flow, "alg"))


class MessageKeyListView(View):
    """Pick an own seed or a contact key. Scan, Enter and the relay add another contact."""

    SCAN = ButtonOption("Scan QR", icon_name=SeedSignerIconConstants.SCAN)
    ENTER = ButtonOption("Enter key")
    RELAY = ButtonOption("Receive by USB")

    def run(self):
        flow = self.controller.message_flow
        if not flow:
            return message_error("Message flow is not active")
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        own = [
            {"seed": seed, "fingerprint": seed.get_fingerprint(network)}
            for seed in self.controller.storage.seeds
        ]
        catalog = choices_for(
            flow["action"],
            flow.get("alg"),
            own,
            self.controller.message_contacts or [],
        )
        if catalog["blocked"]:
            return message_error(catalog["blocked"], "No seed loaded")
        button_data = [
            ButtonOption(entry["label"], icon_name=_icon_for(entry["role"]), return_data=entry)
            for entry in catalog["entries"]
        ]
        if catalog["allow_other"]:
            button_data.extend([self.SCAN, self.ENTER])
            if usb_relay.attached():
                button_data.append(self.RELAY)
        if not button_data:
            return message_error("There is no public key for this algorithm")
        selected = self.run_screen(
            ButtonListScreen,
            title=catalog["title"],
            is_button_text_centered=False,
            button_data=button_data,
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        chosen = button_data[selected]
        if chosen == self.SCAN:
            flow["expect"] = EXPECT_PEER
            from seedsigner.views.message_collect_views import MessageScanView
            return Destination(MessageScanView)
        if chosen == self.ENTER:
            flow["expect"] = EXPECT_PEER
            from seedsigner.views.message_collect_views import MessageTextEntryView
            return Destination(MessageTextEntryView)
        if chosen == self.RELAY:
            flow["expect"] = EXPECT_PEER
            from seedsigner.views.message_collect_views import MessageRelayReceiveView
            return Destination(MessageRelayReceiveView)
        entry = chosen.return_data
        if entry.get("seed") is not None:
            try:
                ensure_bip39(entry["seed"])
            except MessageCryptoError as exc:
                return message_error(str(exc))
            flow["seed"] = entry["seed"]
        else:
            document = entry["document"]
            if flow.get("alg") and not same_key_type(document.get("alg"), flow["alg"]):
                return message_error("That public key is for a different algorithm")
            flow["peer"] = document
        return destination_for(advance(flow, "keys"))


def _action_for(button: ButtonOption) -> str:
    from seedsigner.message_crypto.flow import (
        ACTION_DECRYPT,
        ACTION_ENCRYPT,
        ACTION_PUBLIC,
        ACTION_SIGN,
        ACTION_VERIFY,
    )

    if button == MessageMenuView.ENCRYPT:
        return ACTION_ENCRYPT
    if button == MessageMenuView.DECRYPT:
        return ACTION_DECRYPT
    if button == MessageMenuView.SIGN:
        return ACTION_SIGN
    if button == MessageMenuView.VERIFY:
        return ACTION_VERIFY
    if button == MessageMenuView.PUBLIC:
        return ACTION_PUBLIC
    raise MessageCryptoError("message menu button was not recognized")


def _alg_for(button: ButtonOption, action: str) -> str:
    if button == MessageAlgorithmView.RSA_ENCRYPT:
        return ALG_RSA_ENCRYPT
    if button == MessageAlgorithmView.RSA_SIGN:
        return ALG_RSA_SIGN
    if button == MessageAlgorithmView.ML_KEM:
        return ALG_ML_KEM
    if button == MessageAlgorithmView.ML_DSA:
        return ALG_ML_DSA
    if button == MessageAlgorithmView.PGP and action == ACTION_ENCRYPT:
        return ALG_PGP_ENCRYPT
    if button == MessageAlgorithmView.PGP and action in (ACTION_SIGN, ACTION_VERIFY, ACTION_PUBLIC):
        # View Public Key shows the one PGP block, which both signs and encrypts.
        return ALG_PGP_SIGN
    raise MessageCryptoError("algorithm button was not recognized")


def _icon_for(role: str) -> str:
    if role == ROLE_OWN:
        return SeedSignerIconConstants.SEEDS
    if role == ROLE_IMPORTED:
        return SeedSignerIconConstants.SCAN
    if role == ROLE_PRELOADED:
        return SeedSignerIconConstants.MICROSD
    raise MessageCryptoError("key role was not recognized")


def _algorithms_for(action: str) -> list:
    """PGP, then the post-quantum choice, then RSA. The same order on every menu."""
    if action == ACTION_ENCRYPT:
        return [
            MessageAlgorithmView.PGP,
            MessageAlgorithmView.ML_KEM,
            MessageAlgorithmView.RSA_ENCRYPT,
        ]
    if action in (ACTION_SIGN, ACTION_VERIFY):
        return [
            MessageAlgorithmView.PGP,
            MessageAlgorithmView.ML_DSA,
            MessageAlgorithmView.RSA_SIGN,
        ]
    if action == ACTION_PUBLIC:
        return [
            MessageAlgorithmView.PGP,
            MessageAlgorithmView.ML_KEM,
            MessageAlgorithmView.ML_DSA,
            MessageAlgorithmView.RSA_ENCRYPT,
            MessageAlgorithmView.RSA_SIGN,
        ]
    raise MessageCryptoError(f"action {action} does not choose an algorithm")
