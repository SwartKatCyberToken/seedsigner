"""USB relay as a third way in and out, next to QR codes and the keyboard.

Does not decide what data means. Callers pass public data to RelaySendView and
parse what receive_from_relay returns. The relay is offered only while a USB
serial device is plugged in, so a Pi without one sees the same screens as before.
"""

from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON, ButtonListScreen, ButtonOption, LargeIconStatusScreen
from seedsigner.hardware import usb_relay
from seedsigner.hardware.usb_relay import RelayError
from seedsigner.views.view import BackStackView, Destination, ErrorView, MainMenuView, View

SHOW_QR = ButtonOption("Show QR")
SCAN_QR = ButtonOption("Scan QR")
SEND_USB = ButtonOption("Send by USB")
RECEIVE_USB = ButtonOption("Receive by USB")

OUTPUT_QR = "qr"
OUTPUT_RELAY = "relay"
INPUT_CAMERA = "camera"
INPUT_RELAY = "relay"


def relay_error(text: str) -> Destination:
    """Show text, then go back to the screen that offered the relay."""
    return Destination(
        ErrorView,
        view_args=dict(
            title="USB relay",
            status_headline="Transfer failed",
            text=text,
            button_text="Back",
            next_destination=Destination(BackStackView),
        ),
    )


def choose_output(view: View, title: str) -> str:
    """QR or relay. With no relay plugged in this goes straight to the QR."""
    if not usb_relay.attached():
        return OUTPUT_QR
    button_data = [SHOW_QR, SEND_USB]
    selected = view.run_screen(ButtonListScreen, title=title, button_data=button_data, show_back_button=False)
    return OUTPUT_RELAY if button_data[selected] == SEND_USB else OUTPUT_QR


def choose_input(view: View, title: str) -> str | None:
    """Camera or relay, or None for Back. With no relay this is the camera."""
    if not usb_relay.attached():
        return INPUT_CAMERA
    button_data = [SCAN_QR, RECEIVE_USB]
    selected = view.run_screen(ButtonListScreen, title=title, button_data=button_data)
    if selected == RET_CODE__BACK_BUTTON:
        return None
    return INPUT_RELAY if button_data[selected] == RECEIVE_USB else INPUT_CAMERA


def _with_spinner(text: str, work):
    from seedsigner.gui.screens.screen import LoadingScreenThread

    spinner = LoadingScreenThread(text=text)
    spinner.start()
    try:
        return work()
    finally:
        spinner.stop()


def _open_port(role: str):
    if not usb_relay.can_open_ports():
        raise RelayError("The USB relay works on the Pi and on Linux, not on Windows.")
    return _with_spinner("Finding relay...", lambda: usb_relay.find_port(role))


def _release_port(port) -> None:
    """Close the port and reset USB, so the next transfer starts clean in either direction."""
    devices = usb_relay.usb_devices()
    port.close()
    if devices:
        _with_spinner("Resetting USB...", lambda: usb_relay.reset_usb(devices))


def _run_transfer(view: View, title: str, transfer) -> int:
    from seedsigner.gui.screens.relay_screens import RelayTransferScreen

    try:
        return view.run_screen(RelayTransferScreen, title=title, transfer=transfer)
    finally:
        # A long transfer must not start the screensaver the moment it ends.
        view.controller.reset_screensaver_timeout()


def receive_from_relay(view: View, title: str = "USB relay") -> bytes | None:
    """One message from the receiver board. None if the user cancelled."""
    port = _open_port(usb_relay.ROLE_RX)
    try:
        receiver = usb_relay.RelayReceiver(port)
        if _run_transfer(view, title, receiver) == RET_CODE__BACK_BUTTON:
            return None
        return receiver.result()
    finally:
        _release_port(port)


class RelaySendView(View):
    """Send public data to the sender board, then continue at next_destination."""

    def __init__(self, data: bytes, title: str = "USB relay", next_destination: Destination = None, on_done=None):
        super().__init__()
        self.data = data
        self.title = title
        self.next_destination = next_destination
        self.on_done = on_done

    def run(self):
        try:
            port = _open_port(usb_relay.ROLE_TX)
            try:
                sender = usb_relay.RelaySender(port, usb_relay.frame_message(self.data))
                if _run_transfer(self, self.title, sender) == RET_CODE__BACK_BUTTON:
                    if sender.queued:
                        _with_spinner("Finishing queued data...", sender.drain)
                    return Destination(BackStackView)
            finally:
                _release_port(port)
        except RelayError as exc:
            # Off the back stack, so Back returns to the choice and does not resend.
            destination = relay_error(str(exc))
            destination.skip_current_view = True
            return destination
        if self.on_done:
            self.on_done()
        self.run_screen(
            LargeIconStatusScreen,
            title=self.title,
            status_headline="Sent",
            text=f"{len(self.data)} bytes went through the relay.",
            button_data=[ButtonOption("Done")],
            show_back_button=False,
        )
        return self.next_destination or Destination(MainMenuView, clear_history=True)
