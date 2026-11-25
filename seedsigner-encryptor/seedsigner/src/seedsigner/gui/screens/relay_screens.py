"""Progress for a transfer over the USB relay.

Does not know the protocol. The transfer object supplies poll(), done, status(),
notes() and preview(). Polling here, rather than in wait_for, also keeps the screensaver off
for the many minutes a transfer can take. Left cancels; a click is ignored so
the press that opened this screen cannot cancel it.
"""

import time
from dataclasses import dataclass

from seedsigner.gui.components import Fonts, GUIConstants
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON, BaseTopNavScreen
from seedsigner.hardware.buttons import HardwareButtonsConstants

RET_CODE__TRANSFER_DONE = 0
_REDRAW_SECONDS = 1.0
_HEADLINE_SIZE_EXTRA = 4
_SMALL_FONT_SIZE = 14
_PREVIEW_LINES = 2
_BAR_HEIGHT = 8


@dataclass
class RelayTransferScreen(BaseTopNavScreen):
    transfer: object = None

    def __post_init__(self):
        super().__post_init__()
        self._body_size = GUIConstants.get_body_font_size()
        self._headline_size = self._body_size + _HEADLINE_SIZE_EXTRA
        self._body_font = Fonts.get_font(GUIConstants.get_body_font_name(), self._body_size)
        self._headline_font = Fonts.get_font(GUIConstants.get_body_font_name(), self._headline_size)
        self._small_font = Fonts.get_font(GUIConstants.get_body_font_name(), _SMALL_FONT_SIZE)

    def _render(self):
        super()._render()
        headline, detail, fraction = self.transfer.status()
        center = self.canvas_width // 2
        y = self.top_nav.height
        self.image_draw.text((center, y), headline, font=self._headline_font, fill=GUIConstants.BODY_FONT_COLOR, anchor="ma")
        y += GUIConstants.COMPONENT_PADDING + self._headline_size
        width = self.canvas_width - 2 * GUIConstants.EDGE_PADDING
        for line in _wrap(self.image_draw, detail, self._body_font, width):
            self.image_draw.text((center, y), line, font=self._body_font, fill=GUIConstants.BODY_FONT_COLOR, anchor="ma")
            y += self._body_size + GUIConstants.BODY_LINE_SPACING
        if fraction is not None:
            self._draw_bar(y, fraction)
            y += _BAR_HEIGHT + GUIConstants.COMPONENT_PADDING
        line_height = _SMALL_FONT_SIZE + 3
        for line in self.transfer.notes():
            self.image_draw.text((center, y), line, font=self._small_font, fill=GUIConstants.BODY_FONT_COLOR, anchor="ma")
            y += line_height
        cancel_y = self.canvas_height - GUIConstants.EDGE_PADDING
        self.image_draw.text((center, cancel_y), "Left to cancel", font=self._small_font, fill=GUIConstants.BODY_FONT_COLOR, anchor="ms")
        lines = _tail_lines(self.image_draw, self.transfer.preview(), self._small_font, width, _PREVIEW_LINES)
        y = cancel_y - _SMALL_FONT_SIZE - GUIConstants.COMPONENT_PADDING - len(lines) * line_height
        for line in lines:
            self.image_draw.text((GUIConstants.EDGE_PADDING, y), line, font=self._small_font, fill=GUIConstants.ACCENT_COLOR)
            y += line_height

    def _draw_bar(self, y: int, fraction: float) -> None:
        left = GUIConstants.EDGE_PADDING
        right = self.canvas_width - GUIConstants.EDGE_PADDING
        bottom = y + _BAR_HEIGHT
        self.image_draw.rectangle((left, y, right, bottom), outline=GUIConstants.BODY_FONT_COLOR)
        filled = left + int((right - left) * min(fraction, 1.0))
        if filled > left:
            self.image_draw.rectangle((left, y, filled, bottom), fill=GUIConstants.ACCENT_COLOR)

    def _snapshot(self) -> tuple:
        return self.transfer.status(), self.transfer.notes(), self.transfer.preview()

    def _run(self):
        shown = self._snapshot()
        next_redraw = time.monotonic() + _REDRAW_SECONDS
        while not self.transfer.done:
            self.transfer.poll(0.1)
            if self.hw_inputs.check_for_low(HardwareButtonsConstants.KEY_LEFT):
                return RET_CODE__BACK_BUTTON
            status = self._snapshot()
            if status != shown and time.monotonic() >= next_redraw:
                with self.renderer.lock:
                    self._render()
                    self.renderer.show_image()
                shown = status
                next_redraw = time.monotonic() + _REDRAW_SECONDS
        return RET_CODE__TRANSFER_DONE


def _tail_lines(draw, text: str, font, width: int, max_lines: int) -> list:
    """The end of text in up to max_lines lines. Keys and base64 have no word breaks."""
    lines, current = [], ""
    for char in reversed(text):
        if draw.textlength(char + current, font=font) > width:
            lines.insert(0, current)
            if len(lines) == max_lines:
                return lines
            current = char
        else:
            current = char + current
    return [current] + lines if current else lines


def _wrap(draw, text: str, font, width: int) -> list:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])
