"""Which home-grid edges open the message menu.

Does not read GPIO or draw. MainMenuScreen calls the matching function
when the joystick cannot move the highlight any further. One press is
enough. Seeds is index 1, Tools is index 2, Settings is index 3.
"""

RIGHT_EDGE_INDEXES = (1, 3)
BOTTOM_EDGE_INDEXES = (2, 3)


def opens_on_right(selected_index: int) -> bool:
    """Right from Seeds or Settings opens Messages."""
    return selected_index in RIGHT_EDGE_INDEXES


def opens_on_down(selected_index: int) -> bool:
    """Down from Tools or Settings opens Messages."""
    return selected_index in BOTTOM_EDGE_INDEXES
