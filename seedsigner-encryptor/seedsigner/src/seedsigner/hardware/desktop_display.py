"""Tk window that shows the SeedSigner framebuffer on a PC.

Does not read the joystick itself. desktop_env.install_desktop_hardware
selects this driver instead of the SPI panel. Frames arrive from the
renderer thread; this file owns the Tk thread and forwards key events.
"""

import logging
import threading
from dataclasses import dataclass

from seedsigner.hardware.desktop_env import note_key_press, note_key_release, wait_frame
from seedsigner.hardware.displays.display_driver import BaseDisplayDriver

logger = logging.getLogger(__name__)

# The Pi has a joystick and three buttons. F1, F2, and F3 are those buttons.
# Each screen decides what they do, so this hint stays general.
DESKTOP_KEY_HINT = (
    "Arrows move. Enter clicks. Interact with F1, F2, and F3.\n"
    "Messages: Right on Seeds or Settings, or Down on Tools or Settings. "
    "Left or Right on that list returns Home."
)


@dataclass
class DesktopDisplay(BaseDisplayDriver):
    """240x240 RGB window, scaled 2x so the UI is readable on a desktop."""

    def __post_init__(self):
        self._thread = threading.Thread(target=self._run_window, name="seedsigner-desktop", daemon=True)
        self._thread.start()

    def show_image(self, image, x_start: int = 0, y_start: int = 0):
        from seedsigner.hardware.desktop_env import push_frame
        push_frame(image)

    def _run_window(self) -> None:
        import tkinter as tk
        from PIL import ImageTk

        try:
            root = tk.Tk()
        except Exception:
            logger.exception("desktop window failed to open")
            return
        root.title("SeedSigner desktop")
        root.geometry("520x640")
        root.lift()
        root.attributes("-topmost", True)
        root.after(500, lambda: root.attributes("-topmost", False))
        label = tk.Label(root, bg="black")
        label.pack(fill="both", expand=True)
        tk.Label(
            root,
            text=DESKTOP_KEY_HINT,
            justify="left",
            anchor="w",
            wraplength=500,
            padx=8,
            pady=6,
        ).pack(fill="x")
        state = {"photo": None}

        def paint() -> None:
            frame = wait_frame(0.01)
            if frame is not None:
                scaled = frame.convert("RGB").resize((self.width * 2, self.height * 2))
                state["photo"] = ImageTk.PhotoImage(scaled)
                label.configure(image=state["photo"])
            root.after(30, paint)

        def on_press(event) -> None:
            clipboard = ""
            if event.state & 0x4 and event.keysym.lower() == "v":
                try:
                    clipboard = root.clipboard_get()
                except tk.TclError:
                    clipboard = ""
            note_key_press(
                event.keysym,
                event.char or "",
                bool(event.state & 0x1),
                bool(event.state & 0x4),
                clipboard,
            )

        def on_release(event) -> None:
            note_key_release(event.keysym)

        root.bind("<KeyPress>", on_press)
        root.bind("<KeyRelease>", on_release)
        paint()
        root.mainloop()
