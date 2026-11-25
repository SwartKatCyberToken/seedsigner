"""Controller routing into the message menu.

Does not generate keys. Screen return values are supplied by FlowTest, the
same way the other SeedSigner view tests run on a PC.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from base import FlowStep, FlowTest
from PIL import Image, ImageDraw

from seedsigner.gui.components import FontAwesomeIconConstants
from seedsigner.gui.renderer import Renderer
from seedsigner.gui.screens.message_screens import (
    MessageKeyboardScreen,
    _break_long_tokens,
    _fit_scroll_window,
    scroll_cues,
)
from seedsigner.gui.screens.screen import RET_CODE__MESSAGE_MENU
from seedsigner.hardware.buttons import HardwareButtonsConstants as Keys
from seedsigner.message_crypto.flow import (
    ACTION_ENCRYPT,
    ACTION_PUBLIC,
    ACTION_SIGN,
    ACTION_VERIFY,
    encrypt_notice,
)
from seedsigner.models.seed import Seed
from seedsigner.views.message_collect_views import (
    MessageInputChoiceView,
    MessageReviewView,
    MessageTextEntryView,
)
from seedsigner.message_crypto.key_catalog import ROLE_IMPORTED, ROLE_OWN, ROLE_PRELOADED
from seedsigner.views.message_views import (
    MessageAlgorithmView,
    MessageEncryptNoticeView,
    MessageKeyListView,
    MessageMenuView,
    _algorithms_for,
    _icon_for,
)
from seedsigner.views.message_run_views import (
    MessageExecuteView,
    MessageResultFormatView,
    MessageResultTextView,
    result_text,
)
from seedsigner.views.view import ErrorView, MainMenuView


def _type_on_message_keyboard(presses: list) -> str:
    """Run MessageKeyboardScreen against a real canvas with these button presses."""
    canvas = Image.new("RGB", (240, 240))
    renderer = MagicMock(canvas_width=240, canvas_height=240, canvas=canvas, draw=ImageDraw.Draw(canvas))
    with patch.object(Renderer, "get_instance", return_value=renderer):
        screen = MessageKeyboardScreen(title="Message")
        screen.hw_inputs = MagicMock()
        screen.hw_inputs.wait_for.side_effect = presses
        return screen._run()


def test_joystick_reaches_the_check_button_and_clicks_it():
    # "a", then Right past the 9th column onto the check button, then click.
    assert _type_on_message_keyboard([Keys.KEY_PRESS] + [Keys.KEY_RIGHT] * 9 + [Keys.KEY_PRESS]) == "a"


def test_left_from_the_check_button_returns_to_the_keyboard():
    presses = [Keys.KEY_PRESS] + [Keys.KEY_RIGHT] * 9 + [Keys.KEY_LEFT, Keys.KEY_PRESS, Keys.KEY2]
    assert _type_on_message_keyboard(presses) == "ai"


def test_space_key_and_key2_submit():
    # Bottom row is . , ? ! then the 2-wide space key at column 4.
    presses = (
        [Keys.KEY_PRESS]
        + [Keys.KEY_DOWN] * 4 + [Keys.KEY_RIGHT] * 4 + [Keys.KEY_PRESS]
        + [Keys.KEY_UP] * 4 + [Keys.KEY_PRESS]
        + [Keys.KEY2]
    )
    assert _type_on_message_keyboard(presses) == "a e"


def test_result_text_is_the_pgp_armor_alone():
    block = "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\nhi\n-----BEGIN PGP SIGNATURE-----\nxyz\n-----END PGP SIGNATURE-----"
    armor = "-----BEGIN PGP MESSAGE-----\nxyz\n-----END PGP MESSAGE-----"
    assert result_text({"op": "sig-pgp", "armor": block, "msg": "hi"}) == block
    assert result_text({"op": "enc-pgp", "armor": armor}) == armor
    assert '"sig":"AA"' in result_text({"op": "sig-rsa", "msg": "hi", "sig": "AA"}).replace(" ", "")


def test_algorithm_lists_put_pgp_first_and_rsa_last():
    encrypt = [button.button_label for button in _algorithms_for(ACTION_ENCRYPT)]
    sign = [button.button_label for button in _algorithms_for(ACTION_SIGN)]
    public = [button.button_label for button in _algorithms_for(ACTION_PUBLIC)]
    assert encrypt == ["PGP", "ML-KEM (quantum)", "RSA encrypt"]
    assert sign == ["PGP", "ML-DSA (quantum)", "RSA sign"]
    assert [button.button_label for button in _algorithms_for(ACTION_VERIFY)] == sign
    assert public == [
        "PGP",
        "ML-KEM (quantum)",
        "ML-DSA (quantum)",
        "RSA encrypt",
        "RSA sign",
    ]


def test_message_menu_uses_distinct_icons():
    icons = [
        MessageMenuView.ENCRYPT.icon_name,
        MessageMenuView.DECRYPT.icon_name,
        MessageMenuView.SIGN.icon_name,
        MessageMenuView.VERIFY.icon_name,
        MessageMenuView.PUBLIC.icon_name,
    ]
    assert icons == [
        FontAwesomeIconConstants.LOCK,
        FontAwesomeIconConstants.UNLOCK,
        FontAwesomeIconConstants.FILE_SIGNATURE,
        FontAwesomeIconConstants.CIRCLE_CHECK,
        FontAwesomeIconConstants.ADDRESS_BOOK,
    ]
    assert len(set(icons)) == 5


def test_overflowing_text_reserves_chevron_space():
    _top, visible = _fit_scroll_window(3, 20, 240, 48, 10)
    top_more, visible_more = _fit_scroll_window(40, 20, 240, 48, 10)
    assert visible_more < visible
    assert top_more > 48
    assert scroll_cues(0, visible_more, 40) == (False, True)
    assert scroll_cues(2, visible_more, 40)[0] is True
    assert scroll_cues(40 - visible_more, visible_more, 40) == (True, False)


def test_long_key_text_breaks_onto_more_than_one_line():
    lines = _break_long_tokens("A" * 80).split("\n")
    assert len(lines) > 1
    assert all(len(line) <= 22 for line in lines)


def test_key_roles_use_different_icons():
    icons = {_icon_for(ROLE_OWN), _icon_for(ROLE_IMPORTED), _icon_for(ROLE_PRELOADED)}
    assert len(icons) == 3


def test_encrypt_warning_is_shown_before_the_keyboard():
    notice = encrypt_notice()
    assert "their public key" in notice["text"]
    assert notice["headline"] == "Not your seed"


def _load_abandon(view):
    view.controller.storage.seeds.append(Seed(mnemonic=["abandon"] * 11 + ["about"]))


class TestMessageMenuFlows(FlowTest):
    def setUp(self):
        super().setUp()
        self._ini = Path(__file__).resolve().parent / "_flow_preloaded.ini"
        self._ini.write_text(
            "[rsa-encrypt]\nlabel = alice\ndocument = "
            '{"v":1,"op":"pub","alg":"rsa-encrypt","n":"AQ","e":65537}\n'
            "[rsa-sign]\nlabel = alice\ndocument = "
            '{"v":1,"op":"pub","alg":"rsa-sign","n":"AQ","e":65537}\n',
            encoding="utf-8",
        )
        os.environ["SEEDSIGNER_PRELOADED_KEYS"] = str(self._ini)

    def tearDown(self):
        os.environ.pop("SEEDSIGNER_PRELOADED_KEYS", None)
        self._ini.unlink(missing_ok=True)
        super().tearDown()

    def test_repeated_right_opens_the_message_menu(self):
        self.run_sequence([
            FlowStep(MainMenuView, screen_return_value=RET_CODE__MESSAGE_MENU),
            FlowStep(MessageMenuView),
        ])

    def test_encrypt_does_not_require_a_seed(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.ENCRYPT),
            FlowStep(MessageEncryptNoticeView, button_data_selection=MessageEncryptNoticeView.CONTINUE),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.RSA_ENCRYPT),
            FlowStep(MessageKeyListView),
        ])

    def test_encrypt_selects_a_key_before_the_message(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.ENCRYPT),
            FlowStep(MessageEncryptNoticeView, button_data_selection=MessageEncryptNoticeView.CONTINUE),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.RSA_ENCRYPT),
            FlowStep(MessageKeyListView, screen_return_value=0),
            FlowStep(MessageInputChoiceView, button_data_selection=MessageInputChoiceView.KEYBOARD),
            FlowStep(MessageTextEntryView, screen_return_value="hello"),
            FlowStep(MessageReviewView),
        ])

    def test_sign_selects_an_own_key_before_the_message(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.SIGN),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.RSA_SIGN),
            FlowStep(MessageKeyListView, before_run=_load_abandon, screen_return_value=0),
            FlowStep(MessageInputChoiceView, button_data_selection=MessageInputChoiceView.KEYBOARD),
            FlowStep(MessageTextEntryView, screen_return_value="hello"),
            FlowStep(MessageReviewView),
        ])

    def test_signature_can_be_shown_as_text(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.SIGN),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.ML_DSA),
            FlowStep(MessageKeyListView, before_run=_load_abandon, screen_return_value=0),
            FlowStep(MessageInputChoiceView, button_data_selection=MessageInputChoiceView.KEYBOARD),
            FlowStep(MessageTextEntryView, screen_return_value="hello"),
            FlowStep(MessageReviewView, button_data_selection=MessageReviewView.CONTINUE),
            FlowStep(MessageExecuteView, is_redirect=True),
            FlowStep(MessageResultFormatView, button_data_selection=MessageResultFormatView.TEXT),
            FlowStep(MessageResultTextView),
        ])

    def test_verify_selects_a_signer_key_before_the_signature(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.VERIFY),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.RSA_SIGN),
            FlowStep(MessageKeyListView, screen_return_value=0),
            FlowStep(MessageInputChoiceView),
        ])

    def test_view_public_key_opens_the_key_list_without_a_seed(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.PUBLIC),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.RSA_ENCRYPT),
            FlowStep(MessageKeyListView),
        ])

    def test_decrypt_without_a_seed_reports_an_error(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.DECRYPT),
            FlowStep(MessageKeyListView, is_redirect=True),
            FlowStep(ErrorView),
        ])

    def test_sign_without_a_seed_reports_an_error(self):
        self.run_sequence([
            FlowStep(MessageMenuView, button_data_selection=MessageMenuView.SIGN),
            FlowStep(MessageAlgorithmView, button_data_selection=MessageAlgorithmView.RSA_SIGN),
            FlowStep(MessageKeyListView, is_redirect=True),
            FlowStep(ErrorView),
        ])
