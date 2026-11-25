"""On-screen keyboard, a scrolling text page, and a key fingerprint page.

Does not decide what the text means. Message views supply the title and the
body. The keyboard has a space key. Right off its right edge selects the
check button; a joystick click there or KEY2 submits. Up and Down scroll
the text page.
A chevron shows when more lines sit above or below the page. Joystick click
closes it.
"""

from dataclasses import dataclass

from PIL import Image, ImageDraw

from seedsigner.gui.components import Fonts, GUIConstants, TextArea, reflow_text_for_width
from seedsigner.gui.keyboard import Keyboard
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON, BaseTopNavScreen, ButtonListScreen, KeyboardScreen
from seedsigner.hardware.buttons import HardwareButtonsConstants

# 40 character keys, a 2-wide space and a 3-wide backspace fill a 5x9 grid (45 slots).
_MESSAGE_KEYS = "abcdefghijklmnopqrstuvwxyz0123456789.,?!"


@dataclass
class MessageKeyboardScreen(KeyboardScreen):
    def __post_init__(self):
        self.rows = 5
        self.cols = 9
        self.keys_charset = _MESSAGE_KEYS
        self.show_save_button = True
        self.save_key = HardwareButtonsConstants.KEY2
        self.save_button_navigable = True
        self.custom_additional_keys = [Keyboard.KEY_SPACE_2, Keyboard.KEY_BACKSPACE]
        super().__post_init__()


@dataclass
class MessageScrollScreen(BaseTopNavScreen):
    """Several wrapped lines, moved with Up and Down. Click closes the page."""

    body: str = ""

    def __post_init__(self):
        super().__post_init__()
        width = self.canvas_width - (2 * GUIConstants.EDGE_PADDING)
        font_size = GUIConstants.get_body_font_size()
        self._font = Fonts.get_font(GUIConstants.get_body_font_name(), font_size)
        self._line_height = font_size + GUIConstants.BODY_LINE_SPACING
        wrapped = _break_long_tokens(self.body or "")
        self._lines = [
            item["text"] for item in reflow_text_for_width(wrapped, width, font_size=font_size)
        ] or [""]
        self._chevron_h = 10
        self._text_top, self._visible = _fit_scroll_window(
            line_count=len(self._lines),
            line_height=self._line_height,
            canvas_height=self.canvas_height,
            top_nav_height=self.top_nav.height,
            chevron_h=self._chevron_h,
        )
        self._offset = 0
        self._up_chevron = _chevron_image(pointing="up")
        self._down_chevron = _chevron_image(pointing="down")

    def _render(self):
        super()._render()
        y = self._text_top
        for line in self._lines[self._offset:self._offset + self._visible]:
            self.image_draw.text(
                (GUIConstants.EDGE_PADDING, y),
                line,
                font=self._font,
                fill=GUIConstants.BODY_FONT_COLOR,
            )
            y += self._line_height
        show_up, show_down = scroll_cues(self._offset, self._visible, len(self._lines))
        center_x = int(self.canvas_width / 2) - self._up_chevron.width // 2
        if show_up:
            self.canvas.paste(self._up_chevron, (center_x, self.top_nav.height))
        if show_down:
            self.canvas.paste(
                self._down_chevron,
                (center_x, self.canvas_height - self._chevron_h),
            )

    def _run(self):
        while True:
            self._render()
            self.renderer.show_image()
            user_input = self.hw_inputs.wait_for(
                HardwareButtonsConstants.KEYS__LEFT_RIGHT_UP_DOWN + HardwareButtonsConstants.KEYS__ANYCLICK
            )
            if user_input == HardwareButtonsConstants.KEY_UP and self._offset > 0:
                self._offset -= 1
            elif user_input == HardwareButtonsConstants.KEY_DOWN and self._offset + self._visible < len(self._lines):
                self._offset += 1
            elif user_input == HardwareButtonsConstants.KEY_LEFT:
                return RET_CODE__BACK_BUTTON
            elif user_input in HardwareButtonsConstants.KEYS__ANYCLICK:
                return 0


# Five groups of four, the half of a fingerprint gpg prints before its double space,
# fit the 224 px between the edge paddings in this fixed-width font.
FINGERPRINT_FONT_SIZE = 18


@dataclass
class MessageFingerprintScreen(ButtonListScreen):
    """A key's fingerprint, five groups of four to a line in a fixed-width font, above the buttons."""

    kind: str = ""
    fingerprint_lines: str = ""
    note: str = ""

    def __post_init__(self):
        self.is_bottom_list = True
        super().__post_init__()
        y = self.top_nav.height
        headline = TextArea(
            text=self.kind,
            width=self.canvas_width,
            screen_y=y,
            font_color=GUIConstants.ACCENT_COLOR,
            auto_line_break=False,
        )
        self.components.append(headline)
        y += headline.height + GUIConstants.COMPONENT_PADDING
        for line in self.fingerprint_lines.split("\n"):
            digits = TextArea(
                text=line,
                width=self.canvas_width,
                screen_y=y,
                font_name=GUIConstants.FIXED_WIDTH_EMPHASIS_FONT_NAME,
                font_size=FINGERPRINT_FONT_SIZE,
                auto_line_break=False,
            )
            self.components.append(digits)
            y += digits.height + GUIConstants.BODY_LINE_SPACING
        if self.note:
            y += GUIConstants.COMPONENT_PADDING - GUIConstants.BODY_LINE_SPACING
            self.components.append(TextArea(
                text=self.note,
                width=self.canvas_width,
                height=self.buttons[0].screen_y - y,
                screen_y=y,
            ))


def scroll_cues(offset: int, visible: int, total: int) -> tuple:
    """Whether a chevron should show above the page and below it."""
    return offset > 0, offset + visible < total


def _fit_scroll_window(line_count: int, line_height: int, canvas_height: int, top_nav_height: int, chevron_h: int) -> tuple:
    """Return (text_top, visible_lines). Leave room for chevrons when the text overflows."""
    def fit(reserve: bool) -> tuple:
        text_top = top_nav_height + (chevron_h if reserve else 2)
        bottom = chevron_h if reserve else GUIConstants.EDGE_PADDING
        visible = max(1, (canvas_height - text_top - bottom) // line_height)
        return text_top, visible

    text_top, visible = fit(False)
    if line_count > visible:
        text_top, visible = fit(True)
    return text_top, visible


def _chevron_image(pointing: str) -> Image.Image:
    """Same two-line chevron the scrolling button lists use."""
    image = Image.new("RGBA", size=(20, 8), color="black")
    draw = ImageDraw.Draw(image)
    color = GUIConstants.BUTTON_FONT_COLOR
    if pointing == "up":
        draw.line((10, 1, 0, 7), fill=color)
        draw.line((10, 1, 20, 7), fill=color)
    else:
        draw.line((10, 7, 0, 1), fill=color)
        draw.line((10, 7, 20, 1), fill=color)
    return image


def _break_long_tokens(text: str, limit: int = 22) -> str:
    """Split unbroken key material so a line can move onto the next row."""
    lines = []
    for line in text.split("\n"):
        if len(line) <= limit:
            lines.append(line)
        else:
            lines.extend(line[index:index + limit] for index in range(0, len(line), limit))
    return "\n".join(lines)
