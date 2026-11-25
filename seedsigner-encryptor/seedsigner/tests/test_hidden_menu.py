"""The one-press edges that open the message menu.

Does not construct a screen. MainMenuScreen is the only caller. Home is a
2x2 grid: Scan 0, Seeds 1, Tools 2, Settings 3.
"""

from seedsigner.gui.hidden_menu import opens_on_down, opens_on_right


def test_right_on_the_right_column_opens_messages():
    assert opens_on_right(1) is True
    assert opens_on_right(3) is True
    assert opens_on_right(0) is False
    assert opens_on_right(2) is False


def test_down_on_the_bottom_row_opens_messages():
    assert opens_on_down(2) is True
    assert opens_on_down(3) is True
    assert opens_on_down(0) is False
    assert opens_on_down(1) is False
