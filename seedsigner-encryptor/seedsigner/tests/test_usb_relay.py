"""USB relay protocol handling and where the relay appears in the views.

Does not open a serial port. FakePort plays back what the mechanical firmware
prints, in the formats from its src/sender and src/receiver main.cpp.
"""

import base64
import struct
import zlib
from unittest.mock import MagicMock, patch

import pytest
from base import BaseTest

from seedsigner.hardware import usb_relay
from seedsigner.hardware.usb_relay import (
    ROLE_RX,
    ROLE_TX,
    RelayError,
    RelayReceiver,
    RelaySender,
    decoder_segments,
    find_port,
    parse_line,
)
from seedsigner.message_crypto.flow import ACTION_DECRYPT, ACTION_ENCRYPT, ACTION_PUBLIC, ACTION_SIGN, ACTION_VERIFY, EXPECT_PEER, EXPECT_TEXT, new_flow
from seedsigner.views import relay_views, scan_views
from seedsigner.views.message_collect_views import MessageInputChoiceView, MessageRelayReceiveView, MessageReviewView, choice_for
from seedsigner.views.message_run_views import MessageResultFormatView
from seedsigner.views.message_views import MessageKeyListView
from seedsigner.views.view import BackStackView, Destination, ErrorView, MainMenuView


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakePort:
    """Gives one scripted batch of lines per read and records writes."""

    def __init__(self, batches=(), greeting=None, take=None):
        self.batches = list(batches)
        self.greeting = greeting
        self.written = bytearray()
        self.take = take
        self.closed = False

    def request_greeting(self):
        pass

    def read_lines(self, timeout):
        return self.batches.pop(0) if self.batches else []

    def write(self, data):
        count = len(data) if self.take is None else min(self.take, len(data))
        self.written.extend(data[:count])
        return count

    def close(self):
        self.closed = True


def test_parse_line_matches_the_firmware_formats():
    assert parse_line("READY TX 15000 2") == ("READY", "TX", 15000, 2)
    assert parse_line("READY RX") == ("READY", "RX")
    assert parse_line("DATA 5 48656C6C6F") == ("DATA", 5, b"Hello")
    assert parse_line("SENT 3 16") == ("SENT", 3, 16)
    assert parse_line("LOST 2") == ("LOST", 2)
    assert parse_line("BAD CRC") == ("BAD", "CRC")
    assert parse_line("IDLE") == ("IDLE",)
    assert parse_line("") == ("",)
    assert parse_line("DATA 5 nothex") == ("",)
    assert parse_line("noise") == ("",)


def test_find_port_picks_the_board_by_its_greeting():
    ports = {
        "/dev/ttyACM0": FakePort([["READY RX"]]),
        "/dev/ttyACM1": FakePort([["READY TX 15000 2"]]),
    }
    found = find_port(ROLE_TX, open_port=ports.get, paths=sorted(ports))
    assert found is ports["/dev/ttyACM1"]
    assert found.greeting == ("READY", "TX", 15000, 2)
    assert ports["/dev/ttyACM0"].closed
    assert not found.closed


def test_find_port_recognises_a_receiver_that_is_already_running():
    port = FakePort([["STATUS 0 1 0 0 0 0"]])
    assert find_port(ROLE_RX, open_port=lambda path: port, paths=["/dev/ttyACM0"]) is port


def test_find_port_explains_a_missing_role():
    port = FakePort([["READY RX"]])
    with pytest.raises(RelayError, match="sends data, so it needs the sender board. The board plugged in is a receiver"):
        find_port(ROLE_TX, open_port=lambda path: port, paths=["/dev/ttyACM0"])
    with pytest.raises(RelayError, match="receives data, so it needs the receiver board. The board plugged in is a sender"):
        find_port(ROLE_RX, open_port=lambda path: FakePort([["READY TX 9000 2"]]), paths=["/dev/ttyACM0"])
    with pytest.raises(RelayError, match="No relay receiver"):
        find_port(ROLE_RX, paths=[])


class FailingPort(FakePort):
    """A Leonardo in its bootloader: silent, then gone from this port."""

    def read_lines(self, timeout):
        raise RelayError("The USB relay was unplugged")


def test_find_port_searches_again_after_a_port_fails():
    ports = [FailingPort(), FakePort([["READY RX"]])]
    naps = []
    found = find_port(ROLE_RX, open_port=lambda path: ports.pop(0), paths=["/dev/ttyACM0"], sleep=naps.append)
    assert found.greeting == ("READY", "RX")
    assert naps == [usb_relay._REENUMERATE_SECONDS]


def test_find_port_reports_a_failure_after_the_second_search():
    naps = []
    with pytest.raises(RelayError, match="No relay receiver"):
        find_port(ROLE_RX, open_port=lambda path: FailingPort(), paths=["/dev/ttyACM0"], sleep=naps.append)
    assert len(naps) == 1


def test_an_empty_port_is_not_reported_as_unplugged():
    port = usb_relay.SerialPort.__new__(usb_relay.SerialPort)
    port._fd = 3
    port._tail = b""
    with patch.object(usb_relay.select, "select", return_value=([3], [], [])):
        with patch.object(usb_relay.os, "read", side_effect=BlockingIOError):
            assert port.read_lines(0.1) == []
        with patch.object(usb_relay.os, "read", side_effect=OSError):
            with pytest.raises(RelayError, match="unplugged"):
                port.read_lines(0.1)


def test_sender_writes_everything_within_the_window():
    data = bytes(range(100))
    port = FakePort([[], ["SENT 0 16"], ["SENT 1 16", "IDLE"], ["SENT 2 16"], ["SENT 3 16"], ["SENT 4 16"], ["SENT 5 16"], ["SENT 6 4", "IDLE"]])
    sender = RelaySender(port, data, clock=FakeClock())
    sender.poll()
    assert len(port.written) == usb_relay._SEND_WINDOW
    for _batch in range(7):
        sender.poll()
    assert sender.done
    assert bytes(port.written) == data
    assert sender.sent == 100


def test_sender_handles_a_short_write():
    port = FakePort(take=1)
    sender = RelaySender(port, b"abc", clock=FakeClock())
    sender.poll()
    sender.poll()
    assert bytes(port.written) == b"ab"


def test_sender_reports_time_from_the_firmware_speed():
    fast = RelaySender(FakePort(greeting=("READY", "TX", 15000, 2)), bytes(160), clock=FakeClock())
    slow = RelaySender(FakePort(greeting=("READY", "TX", 30000, 2)), bytes(160), clock=FakeClock())
    assert abs(fast.seconds_left() - 86.4) < 0.001
    assert abs(slow.seconds_left() - 172.8) < 0.001
    headline, detail, fraction = fast.status()
    assert (headline, fraction) == ("Sending", 0.0)
    assert "0 of 160 bytes" in detail and "about 2 min" in detail


def test_sender_estimates_111_bits_per_second_without_a_greeting():
    sender = RelaySender(FakePort(), bytes(160), clock=FakeClock())
    assert abs(sender.seconds_left() - 51.84) < 0.001


def test_drain_waits_for_everything_written():
    port = FakePort([[], ["SENT 0 16"], [], ["SENT 1 16"]], take=32)
    sender = RelaySender(port, bytes(100), clock=FakeClock())
    sender.poll()
    assert sender.queued
    sender.drain()
    assert not sender.queued
    assert sender.sent == 32


def test_drain_gives_up_when_the_board_stops_reporting():
    clock = FakeClock()
    sender = RelaySender(FakePort(), bytes(100), clock=clock)
    sender.poll()
    clock.now = 61
    with pytest.raises(RelayError, match="stopped responding"):
        sender.drain()


def test_sender_gives_up_when_the_board_stops_reporting():
    clock = FakeClock()
    sender = RelaySender(FakePort(), b"abc", clock=clock)
    sender.poll()
    clock.now = 61
    with pytest.raises(RelayError, match="stopped responding"):
        sender.poll()


def _receive(lines):
    clock = FakeClock()
    receiver = RelayReceiver(FakePort([[line] for line in lines]), clock=clock)
    for _line in lines:
        receiver.poll()
    return receiver, clock


def test_receiver_joins_packets_and_ignores_duplicates_and_status():
    receiver, _clock = _receive([
        "READY RX", "INCOMING 15000 10", "DATA 1 4869", "DUP 1", "STATUS 0 1 1 0 1 0", "INCOMING 15000 9", "DATA 2 21",
    ])
    assert receiver.result() == b"Hi!"
    assert receiver.status() == ("Receiving", "3 bytes so far", None)


def test_receiver_finishes_only_after_a_quiet_line():
    receiver, clock = _receive(["DATA 1 4869"])
    assert not receiver.done
    clock.now = usb_relay.MIN_IDLE_SECONDS + 1
    assert receiver.done


def test_receiver_waits_forever_for_the_first_byte():
    receiver, clock = _receive(["READY RX"])
    clock.now = 1000
    assert not receiver.done
    assert receiver.status()[0] == "Waiting"


def test_status_lines_do_not_keep_a_finished_message_open():
    clock = FakeClock()
    receiver = RelayReceiver(FakePort([["DATA 1 4869"], ["STATUS 0 1 1 0 0 0"]]), clock=clock)
    receiver.poll()
    clock.now = usb_relay.MIN_IDLE_SECONDS + 1
    receiver.poll()
    assert receiver.done


def test_a_slow_link_stretches_the_quiet_time():
    clock = FakeClock()
    receiver = RelayReceiver(FakePort([["INCOMING 100000 0"], ["DATA 1 4869"]]), clock=clock)
    receiver.poll()
    receiver.poll()
    clock.now = 60
    assert not receiver.done
    clock.now = 73
    assert receiver.done


def test_receiver_fails_on_lost_before_the_first_packet():
    receiver, _clock = _receive(["LOST 1", "DATA 41 4869"])
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_receiver_checks_sequence_numbers_itself():
    receiver, _clock = _receive(["DATA 1 4869", "DATA 3 21"])
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_sequence_numbers_wrap_at_256():
    receiver, _clock = _receive(["DATA 255 4869", "DUP 255", "DATA 0 21", "DUP 0"])
    assert receiver.result() == b"Hi!"


def test_receiver_fails_when_it_starts_on_a_second_copy():
    receiver, _clock = _receive(["DUP 7", "DATA 8 4869"])
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_a_stale_repeat_long_before_the_message_is_not_a_failure():
    clock = FakeClock()
    receiver = RelayReceiver(FakePort([["DUP 7"], ["DATA 8 4869"]]), clock=clock)
    receiver.poll()
    clock.now = usb_relay.MIN_IDLE_SECONDS + 1
    receiver.poll()
    assert receiver.result() == b"Hi"


def test_receiver_fails_when_packets_arrived_during_the_board_search():
    clock = FakeClock()
    port = FakePort([["DATA 8 4869"]])
    port.saw_packets = True
    receiver = RelayReceiver(port, clock=clock)
    receiver.poll()
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_find_port_notices_packets_during_the_search():
    clock = FakeClock()
    port = FakePort([["READY RX", "DATA 8 4869"]])
    assert find_port(ROLE_RX, open_port=lambda path: port, paths=["/dev/ttyACM0"], clock=clock) is port
    assert port.saw_packets is True
    assert port.greeting == ("READY", "RX")


@pytest.mark.parametrize("lines", [
    ["DUP 1", "DUP 2"],                 # the firmware calling new packets old
    ["DATA 5 4869", "DUP 6"],
])
def test_receiver_fails_when_the_board_drops_new_packets_as_repeats(lines):
    with pytest.raises(RelayError, match="Replug"):
        _receive(lines)


@pytest.mark.parametrize("bit_us", [1999, 100001, 4000000000, -970])
def test_an_impossible_speed_does_not_delay_the_end_of_a_message(bit_us):
    clock = FakeClock()
    receiver = RelayReceiver(FakePort([[f"INCOMING {bit_us} -970"], ["DATA 1 4869"]]), clock=clock)
    receiver.poll()
    receiver.poll()
    clock.now = usb_relay.MIN_IDLE_SECONDS + 1
    assert receiver.done


def test_receiver_fails_on_a_gap_inside_the_message():
    receiver, _clock = _receive(["DATA 1 4869", "LOST 1", "DATA 3 21"])
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_receiver_fails_when_the_first_packet_is_lost_after_bad_copies():
    receiver, _clock = _receive(["BAD CRC", "BAD CRC", "LOST 1", "DATA 2 21"])
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


@pytest.mark.parametrize("lines, message", [
    (["BAD CRC", "DATA 1 4869"], b"Hi"),
    (["DATA 1 4869", "BAD CRC"], b"Hi"),
    (["DATA 1 41", "DUP 1", "BAD CRC", "DATA 2 42"], b"AB"),
])
def test_one_damaged_copy_is_not_a_failure(lines, message):
    receiver, _clock = _receive(lines)
    assert receiver.result() == message


@pytest.mark.parametrize("lines", [
    ["DATA 1 4869", "DUP 1", "BAD CRC", "BAD FRAMING"],  # both copies of a further packet damaged
    ["DATA 1 4869", "DUP 1", "BAD CRC"],                 # the other copy gave no line at all
    ["DATA 1 4869", "BAD CRC", "BAD CRC"],
    ["BAD CRC", "DATA 1 4869", "BAD CRC"],
])
def test_a_damaged_copy_beyond_the_last_packet_is_a_failure(lines):
    receiver, _clock = _receive(lines)
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_noise_just_before_the_last_packet_fails_safely():
    # Looks the same as a damaged copy, so an intact message is sent again.
    receiver, _clock = _receive(["DATA 1 41", "DUP 1", "BAD CRC", "DATA 2 42", "DUP 2"])
    with pytest.raises(RelayError, match="lost"):
        receiver.result()


def test_receiver_enforces_its_size_limit():
    receiver = RelayReceiver(FakePort([["DATA 1 " + "00" * 11]]), max_bytes=10, clock=FakeClock())
    with pytest.raises(RelayError, match="limit"):
        receiver.poll()


def test_decoder_segments_prepares_each_file_shape():
    assert decoder_segments(b"psbt\xff\x01") == [base64.b64encode(b"psbt\xff\x01").decode()]
    assert decoder_segments(b"cHNidP8B\nAAAA\r\n") == ["cHNidP8BAAAA"]
    assert decoder_segments(b"ur:crypto-psbt/1-2/aa\nur:crypto-psbt/2-2/bb\n") == ["ur:crypto-psbt/1-2/aa", "ur:crypto-psbt/2-2/bb"]
    assert decoder_segments(b"bc1qaddress\n") == ["bc1qaddress"]
    assert decoder_segments(b"\xff\xfe") == [b"\xff\xfe"]


@pytest.mark.parametrize("data, expected", [
    (b"\xef\xbb\xbfcHNidP8B\r\nAAAA\r\n", ["cHNidP8BAAAA"]),
    ("cHNi\u200bdP8B\\nAAAA".encode(), ["cHNidP8BAAAA"]),
    ("cHNi\\ndP8BAAAA".encode(), ["cHNidP8BAAAA"]),
    ("\ufeffur:bytes/1-2/aa\\nur:bytes/2-2/bb\u200e\n".encode(), ["ur:bytes/1-2/aa", "ur:bytes/2-2/bb"]),
    ("\ufeffbc1q\u200bexample\x00\r\n".encode(), ["bc1qexample"]),
    ("bc1qexample\n".encode("utf-16"), ["bc1qexample"]),
])
def test_decoder_segments_repairs_copy_damage(data, expected):
    assert decoder_segments(data) == expected


def test_decoder_segments_keeps_the_text_of_a_sign_message_request():
    request = "signmessage m/84h/0h/0h/0/0 ascii:a\u200db\xa0c"
    assert decoder_segments(("\ufeff" + request + "\n").encode()) == [request]


def test_desktop_mode_offers_the_relay_without_a_board():
    with patch.object(usb_relay.glob, "glob", return_value=[]):
        assert not usb_relay.attached()
        with patch.object(usb_relay, "offer_without_board", True):
            assert usb_relay.attached()


def test_opening_the_relay_on_windows_explains_why_it_cannot_work():
    with patch.object(usb_relay, "can_open_ports", return_value=False):
        with pytest.raises(RelayError, match="not on Windows"):
            relay_views._open_port(ROLE_TX)


def test_relay_is_not_offered_without_a_device():
    with patch.object(usb_relay, "attached", return_value=False):
        view = MagicMock()
        assert relay_views.choose_output(view, "t") == relay_views.OUTPUT_QR
        assert relay_views.choose_input(view, "t") == relay_views.INPUT_CAMERA
        view.run_screen.assert_not_called()
        assert MessageInputChoiceView.RELAY not in choice_for({"expect": EXPECT_TEXT})["buttons"]


def test_relay_is_offered_on_every_message_input():
    with patch.object(usb_relay, "attached", return_value=True):
        assert MessageInputChoiceView.RELAY in choice_for({"expect": EXPECT_TEXT})["buttons"]
        assert MessageInputChoiceView.RELAY in choice_for({"expect": EXPECT_PEER})["buttons"]


class TestScanOverRelay(BaseTest):
    def _run_scan(self, view_cls, data):
        view = view_cls()
        view.run_screen = MagicMock(return_value=1)  # second button: USB relay
        with patch.object(usb_relay, "attached", return_value=True), \
                patch.object(relay_views, "receive_from_relay", return_value=data):
            return view.run(), view

    def test_psbt_in_binary_reaches_the_signing_flow(self):
        from psbt_testing_util import PSBTTestData
        psbt = base64.b64decode(PSBTTestData.SINGLE_SIG_NATIVE_SEGWIT_1_INPUT)
        destination, view = self._run_scan(scan_views.ScanPSBTView, psbt)
        from seedsigner.views.psbt_views import PSBTSelectSeedView
        assert destination.View_cls == PSBTSelectSeedView
        assert view.decoder.is_psbt

    def test_seed_is_refused(self):
        destination, _view = self._run_scan(scan_views.ScanView, b"080115060387063104071857067618681125136207731354\n")
        assert destination.View_cls == ErrorView
        assert "Seeds" in destination.view_args["text"]
        assert self.controller.storage.pending_seed is None

    def test_cancel_goes_back(self):
        destination, _view = self._run_scan(scan_views.ScanView, None)
        assert destination.View_cls == BackStackView

    def test_wrong_type_is_rejected_by_the_existing_check(self):
        destination, _view = self._run_scan(scan_views.ScanPSBTView, b"bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq\n")
        assert destination.View_cls == ErrorView

    def test_seed_scan_flow_never_offers_the_relay(self):
        view = scan_views.ScanSeedQRView()
        view.run_screen = MagicMock()
        with patch.object(usb_relay, "attached", return_value=True), \
                patch.object(relay_views, "choose_input") as choose:
            view.run()
        choose.assert_not_called()


class TestMessageOverRelay(BaseTest):
    def _flow(self, expect):
        flow = new_flow(ACTION_SIGN)
        flow["expect"] = expect
        self.controller.message_flow = flow
        return flow

    def test_plaintext_goes_to_review_without_the_trailing_newline(self):
        flow = self._flow(EXPECT_TEXT)
        with patch.object(relay_views, "receive_from_relay", return_value=b"hello\n"):
            destination = MessageRelayReceiveView().run()
        assert destination.View_cls == MessageReviewView
        assert destination.skip_current_view
        assert flow["text"] == "hello"

    def test_relay_failure_keeps_the_flow_and_shows_the_reason(self):
        flow = self._flow(EXPECT_TEXT)
        with patch.object(relay_views, "receive_from_relay", side_effect=RelayError("broken")):
            destination = MessageRelayReceiveView().run()
        assert destination.View_cls == ErrorView
        assert destination.view_args["text"] == "broken"
        assert self.controller.message_flow is flow

    def test_binary_is_rejected(self):
        self._flow(EXPECT_TEXT)
        with patch.object(relay_views, "receive_from_relay", return_value=b"\xff\xfe"):
            destination = MessageRelayReceiveView().run()
        assert destination.View_cls == ErrorView

    def test_result_is_sent_as_the_same_text_show_text_displays(self):
        armor = "-----BEGIN PGP MESSAGE-----\nabc\n-----END PGP MESSAGE-----"
        self.controller.message_flow = {"action": ACTION_SIGN, "result": {"op": "enc-pgp", "armor": armor}}
        view = MessageResultFormatView()
        view.run_screen = MagicMock(return_value=2)
        with patch.object(usb_relay, "attached", return_value=True):
            destination = view.run()
        assert destination.View_cls == relay_views.RelaySendView
        assert destination.view_args["data"] == armor.encode() + b"\n"
        destination.view_args["on_done"]()
        assert self.controller.message_flow is None


    def test_a_real_pgp_signature_is_sent_as_the_signed_block(self):
        from embit import bip39
        from seedsigner.message_crypto.codec import ALG_PGP_SIGN
        from seedsigner.message_crypto.keys import clear_cache, keys_for_seed
        from seedsigner.message_crypto.operations import export_public, sign_with, verify_with
        from seedsigner.message_crypto.sanitize import WANT_SIGNATURE, parse_input

        clear_cache()
        keys = keys_for_seed(bip39.mnemonic_to_seed("abandon " * 11 + "about"), rsa_bits=1024)
        signed = sign_with(keys, ALG_PGP_SIGN, "two\nlines")
        self.controller.message_flow = {"action": ACTION_SIGN, "result": signed}
        view = MessageResultFormatView()
        view.run_screen = MagicMock(return_value=2)
        with patch.object(usb_relay, "attached", return_value=True):
            destination = view.run()
        sent = destination.view_args["data"]
        assert sent.startswith(b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\ntwo\nlines\n")
        assert sent.endswith(b"-----END PGP SIGNATURE-----\n\n")
        # What arrives at the other end checks out against the device's public key.
        received = parse_input(sent.decode("utf-8"), WANT_SIGNATURE)
        assert received["msg"] == "two\nlines"
        assert verify_with(export_public(keys, ALG_PGP_SIGN), received) is True


class TestKeyListOverRelay(BaseTest):
    def _buttons(self, action, attached=True):
        self.controller.message_flow = new_flow(action)
        view = MessageKeyListView()
        view.run_screen = MagicMock(return_value=0)
        with patch.object(usb_relay, "attached", return_value=attached):
            view.run()
        return view.run_screen.call_args.kwargs["button_data"]

    def test_contact_key_steps_offer_the_relay(self):
        for action in (ACTION_ENCRYPT, ACTION_VERIFY, ACTION_PUBLIC):
            assert MessageKeyListView.RELAY in self._buttons(action)

    def test_no_relay_button_without_a_board(self):
        assert MessageKeyListView.RELAY not in self._buttons(ACTION_ENCRYPT, attached=False)

    def test_choosing_the_relay_waits_for_a_public_key(self):
        flow = new_flow(ACTION_ENCRYPT)
        self.controller.message_flow = flow
        view = MessageKeyListView()
        view.run_screen = MagicMock(side_effect=lambda *a, **k: k["button_data"].index(MessageKeyListView.RELAY))
        with patch.object(usb_relay, "attached", return_value=True):
            destination = view.run()
        assert destination.View_cls == MessageRelayReceiveView
        assert flow["expect"] == EXPECT_PEER

    def test_own_seed_steps_have_no_key_to_receive(self):
        from seedsigner.models.seed import Seed
        self.controller.storage.seeds.append(Seed(["abandon"] * 11 + ["about"]))
        try:
            for action in (ACTION_SIGN, ACTION_DECRYPT):
                assert MessageKeyListView.RELAY not in self._buttons(action)
        finally:
            self.controller.storage.seeds.clear()


class TestRelaySendView(BaseTest):
    def _view(self, **kwargs):
        view = relay_views.RelaySendView(data=b"abc\n", **kwargs)
        view.run_screen = MagicMock(return_value=0)
        return view

    def test_data_goes_out_with_a_message_header(self):
        with patch.object(relay_views, "_open_port", return_value=FakePort()), \
                patch.object(usb_relay, "RelaySender") as sender:
            self._view().run()
        assert sender.call_args[0][1] == usb_relay.frame_message(b"abc\n")

    def test_success_runs_on_done_closes_the_port_and_continues(self):
        port, done = FakePort(), MagicMock()
        next_destination = Destination(MainMenuView)
        with patch.object(relay_views, "_open_port", return_value=port):
            result = self._view(next_destination=next_destination, on_done=done).run()
        assert result is next_destination
        done.assert_called_once()
        assert port.closed

    def test_cancel_returns_to_the_choice_without_on_done(self):
        from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
        port, done = FakePort(), MagicMock()
        view = self._view(on_done=done)
        view.run_screen = MagicMock(return_value=RET_CODE__BACK_BUTTON)
        with patch.object(relay_views, "_open_port", return_value=port):
            assert view.run().View_cls == BackStackView
        done.assert_not_called()
        assert port.closed

    def test_cancel_waits_for_queued_bytes_before_closing(self):
        from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
        port = FakePort([[], ["SENT 0 16"]])  # 4 bytes and the 12 byte header
        view = self._view()

        def cancel_after_writing(_screen, transfer, **_kwargs):
            transfer.poll()
            return RET_CODE__BACK_BUTTON

        view.run_screen = cancel_after_writing
        with patch.object(relay_views, "_open_port", return_value=port), \
                patch.object(relay_views, "_with_spinner", side_effect=lambda _text, work: work()) as spinner:
            assert view.run().View_cls == BackStackView
        spinner.assert_called_once()
        assert port.closed
        assert not port.batches

    def test_drain_failure_on_cancel_shows_the_reason(self):
        from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
        view = self._view()

        def cancel_after_writing(_screen, transfer, **_kwargs):
            transfer.poll()
            return RET_CODE__BACK_BUTTON

        view.run_screen = cancel_after_writing
        port = FakePort()
        with patch.object(relay_views, "_open_port", return_value=port), \
                patch.object(relay_views, "_with_spinner", side_effect=RelayError("The sender stopped responding.")):
            assert view.run().View_cls == ErrorView
        assert port.closed

    def test_missing_sender_shows_the_reason(self):
        with patch.object(relay_views, "_open_port", side_effect=RelayError("No relay sender found.")):
            result = self._view().run()
        assert result.View_cls == ErrorView
        assert result.skip_current_view


def _framed(payload):
    return b"RLY1" + struct.pack(">II", len(payload), zlib.crc32(payload)) + payload


def test_frame_message_matches_the_mechanical_projects_example():
    assert usb_relay.frame_message(b"Hi").hex() == "524c5931000000024d170e0e4869"


def _data_lines(data, size=16):
    return [[f"DATA {index} {data[start:start + size].hex()}"] for index, start in enumerate(range(0, len(data), size))]


def _received(data, clock=None):
    clock = clock or FakeClock()
    receiver = RelayReceiver(FakePort(_data_lines(data)), clock=clock)
    for _ in range(len(data) // 16 + 1):
        receiver.poll()
    return receiver


def test_a_message_with_a_header_ends_when_complete_and_loses_the_header():
    payload = b"-----BEGIN PGP PUBLIC KEY BLOCK-----\nabc\n"
    receiver = _received(_framed(payload))
    assert receiver.done
    assert receiver.result() == payload


def test_an_empty_message_with_a_header_is_complete():
    receiver = _received(_framed(b""))
    assert receiver.done
    assert receiver.result() == b""


def test_a_damaged_message_fails_its_crc():
    framed = bytearray(_framed(b"hello world"))
    framed[-1] ^= 1
    receiver = _received(bytes(framed))
    assert receiver.done
    with pytest.raises(RelayError, match="CRC-32"):
        receiver.result()


def test_a_message_that_stops_early_says_how_far_it_got():
    clock = FakeClock()
    receiver = _received(_framed(bytes(100))[:40], clock)
    assert not receiver.done
    clock.now = usb_relay.MIN_IDLE_SECONDS + 1
    assert receiver.done
    with pytest.raises(RelayError, match="28 of 100 bytes"):
        receiver.result()


def test_a_message_that_stops_in_its_header_is_refused():
    clock = FakeClock()
    receiver = _received(b"RLY1\x00", clock)
    clock.now = usb_relay.MIN_IDLE_SECONDS + 1
    with pytest.raises(RelayError, match="in its header"):
        receiver.result()


def test_data_after_a_message_is_refused():
    receiver = _received(_framed(b"hi") + b"more")
    with pytest.raises(RelayError, match="More data"):
        receiver.result()


def test_a_header_over_the_limit_stops_straight_away():
    header = b"RLY1" + struct.pack(">II", usb_relay.MAX_RECEIVE_BYTES + 1, 0)
    with pytest.raises(RelayError, match="limit"):
        RelayReceiver(FakePort(_data_lines(header)), clock=FakeClock()).poll()


def test_a_stale_loss_does_not_fail_a_message_that_passes_its_crc():
    payload = b"hello"
    lines = [["LOST 1"]] + _data_lines(_framed(payload))
    receiver = RelayReceiver(FakePort(lines), clock=FakeClock())
    for _ in lines:
        receiver.poll()
    assert receiver.result() == payload


def test_status_shows_progress_checks_and_the_latest_text():
    payload = b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n" + b"x" * 200
    framed = _framed(payload)
    receiver = RelayReceiver(FakePort([["BAD CRC"]] + _data_lines(framed[:48])), clock=FakeClock())
    for _ in range(4):
        receiver.poll()
    headline, detail, fraction = receiver.status()
    assert headline == "Receiving"
    assert detail.startswith(f"36 of {len(payload)} bytes")
    assert fraction == 36 / len(payload)
    assert receiver.notes() == ["3 packets OK, 1 damaged, 0 lost", "CRC-32 is checked at the end"]
    assert receiver.preview() == payload[:36].decode()


def test_preview_replaces_itself_and_hides_control_characters():
    receiver = _received(_framed(b"a" * 100 + b"line one\nline two"))
    preview = receiver.preview()
    assert len(preview) == usb_relay._PREVIEW_BYTES
    assert preview.endswith("line one line two")


def test_unframed_data_says_it_cannot_be_checked():
    receiver = _received(b"typed text")
    assert receiver.status()[1] == "10 bytes so far"
    assert "can't check" in receiver.notes()[1]
    assert receiver.preview() == "typed text"


def test_waiting_warns_when_the_contact_reads_open():
    receiver = RelayReceiver(FakePort([["STATUS 0 0 0 0 0 0"], ["STATUS 1 1 0 0 0 0"]]), clock=FakeClock())
    assert receiver.notes() == []
    receiver.poll()
    assert "Contact open" in receiver.notes()[0]
    receiver.poll()
    assert receiver.notes() == []


def test_opening_a_port_does_not_wait_for_output_to_drain():
    termios, tty = MagicMock(), MagicMock()
    termios.error = OSError
    with patch.dict("sys.modules", {"termios": termios, "tty": tty}), \
            patch.object(usb_relay.os, "open", return_value=7), \
            patch.object(usb_relay.os, "O_NOCTTY", 0, create=True), \
            patch.object(usb_relay.os, "O_NONBLOCK", 0, create=True):
        usb_relay.SerialPort("/dev/ttyACM0")
    tty.setraw.assert_called_once_with(7, termios.TCSANOW)


def test_closing_a_port_does_not_block_the_caller():
    import threading

    release = threading.Event()
    closed = threading.Event()

    def stuck_close(_fd):
        release.wait(5)
        closed.set()

    port = usb_relay.SerialPort.__new__(usb_relay.SerialPort)
    port._fd = 7
    with patch.object(usb_relay.os, "close", side_effect=stuck_close):
        port.close()
        assert port._fd is None
        assert not closed.is_set()
        release.set()
        assert closed.wait(5)


def _progress_screen(transfer):
    from PIL import Image, ImageDraw
    from seedsigner.gui.renderer import Renderer
    from seedsigner.gui.screens.relay_screens import RelayTransferScreen

    canvas = Image.new("RGB", (240, 240))
    renderer = MagicMock(canvas_width=240, canvas_height=240, canvas=canvas, draw=ImageDraw.Draw(canvas))
    with patch.object(Renderer, "get_instance", return_value=renderer):
        screen = RelayTransferScreen(title="USB relay", transfer=transfer)
    screen.hw_inputs = MagicMock()
    screen.hw_inputs.check_for_low.return_value = False
    return screen, canvas


def test_progress_screen_draws_and_returns_when_the_transfer_ends():
    from PIL import ImageChops, Image

    port = FakePort([["SENT 0 3"]])
    screen, canvas = _progress_screen(RelaySender(port, b"abc", clock=FakeClock()))
    screen._render()
    assert ImageChops.difference(canvas, Image.new("RGB", (240, 240))).getbbox() is not None
    assert screen._run() == 0
    assert bytes(port.written) == b"abc"


def test_left_cancels_a_receive():
    from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON

    screen, _canvas = _progress_screen(RelayReceiver(FakePort(), clock=FakeClock()))
    screen._render()
    screen.hw_inputs.check_for_low.return_value = True
    assert screen._run() == RET_CODE__BACK_BUTTON


class TestUsbReset:
    def test_finds_the_usb_device_behind_each_port(self, tmp_path, monkeypatch):
        # On the Pi, device is a link to the USB interface. Here it's a real folder, so .. is its parent.
        tty = tmp_path / "ttyACM0"
        (tty / "device").mkdir(parents=True)
        (tty / "authorized").write_text("1")
        monkeypatch.setattr(usb_relay, "_SYS_TTY_GLOB", str(tmp_path / "ttyACM*"))
        assert usb_relay.usb_devices() == [str(tty)]

    def test_skips_a_port_with_no_usb_device_control(self, tmp_path, monkeypatch):
        (tmp_path / "ttyACM0" / "device").mkdir(parents=True)
        monkeypatch.setattr(usb_relay, "_SYS_TTY_GLOB", str(tmp_path / "ttyACM*"))
        assert usb_relay.usb_devices() == []

    def test_disconnects_then_reconnects_and_waits_for_the_port(self, tmp_path, monkeypatch):
        monkeypatch.setattr(usb_relay, "_PORT_GLOB", str(tmp_path / "ttyACM*"))
        (tmp_path / "authorized").write_text("1")
        clock, seen = FakeClock(), []

        def nap(seconds):
            clock.now += seconds
            seen.append((tmp_path / "authorized").read_text())
            if clock.now > 1:
                (tmp_path / "ttyACM0").write_text("")

        usb_relay.reset_usb([str(tmp_path)], clock, nap)
        assert seen[:2] == ["1", "0"]
        assert (tmp_path / "authorized").read_text() == "1"
        assert clock.now < usb_relay._RESET_RETURN_SECONDS

    def test_stops_waiting_for_a_port_that_never_returns(self, tmp_path, monkeypatch):
        monkeypatch.setattr(usb_relay, "_PORT_GLOB", str(tmp_path / "ttyACM*"))
        (tmp_path / "authorized").write_text("1")
        clock = FakeClock()
        usb_relay.reset_usb([str(tmp_path)], clock, lambda seconds: setattr(clock, "now", clock.now + seconds))
        assert usb_relay._RESET_RETURN_SECONDS <= clock.now < usb_relay._RESET_RETURN_SECONDS + 1

    def test_no_permission_is_not_an_error(self, tmp_path):
        naps = []
        usb_relay.reset_usb([str(tmp_path / "gone")], FakeClock(), naps.append)
        assert naps == [usb_relay._RESET_PAUSE_SECONDS]

    def test_nothing_plugged_in_does_nothing(self):
        naps = []
        usb_relay.reset_usb([], FakeClock(), naps.append)
        assert naps == []

    def test_a_silent_board_gets_a_reset_and_a_second_search(self):
        clock = FakeClock()

        def silent_port():
            port = FakePort()
            port.read_lines = lambda timeout: setattr(clock, "now", clock.now + 1) or []
            return port

        ports = [silent_port(), FakePort([["READY RX"]])]
        with patch.object(usb_relay, "usb_devices", return_value=["/sys/1-1"]), \
                patch.object(usb_relay, "reset_usb") as reset:
            found = find_port(ROLE_RX, open_port=lambda path: ports.pop(0), paths=["/dev/ttyACM0"], clock=clock, sleep=lambda _s: None)
        assert found.greeting == ("READY", "RX")
        reset.assert_called_once()
        assert reset.call_args[0][0] == ["/sys/1-1"]

    def test_the_wrong_board_is_reported_without_a_reset(self):
        with patch.object(usb_relay, "reset_usb") as reset, pytest.raises(RelayError, match="needs the receiver"):
            find_port(ROLE_RX, open_port=lambda path: FakePort([["READY TX 9000 2"]]), paths=["/dev/ttyACM0"])
        reset.assert_not_called()


class TestPortReleaseAfterTransfers(BaseTest):
    """Every way out of a transfer closes the port and then resets USB."""

    def _released(self, run, port):
        order = []
        real_close = port.close
        port.close = lambda: (order.append("close"), real_close())
        with patch.object(usb_relay, "usb_devices", return_value=["/sys/1-1"]), \
                patch.object(usb_relay, "reset_usb", side_effect=lambda devices: order.append(("reset", devices))), \
                patch.object(relay_views, "_with_spinner", side_effect=lambda _text, work: work()), \
                patch.object(relay_views, "_open_port", return_value=port):
            result = run()
        assert order == ["close", ("reset", ["/sys/1-1"])]
        return result

    def _send_view(self, code=0):
        view = relay_views.RelaySendView(data=b"abc\n")
        view.run_screen = MagicMock(return_value=code)
        return view

    def _receive_view(self, code=0):
        view = MagicMock()
        view.run_screen = MagicMock(return_value=code)
        return view

    def test_after_a_send(self):
        assert self._released(self._send_view().run, FakePort()).View_cls == MainMenuView

    def test_after_a_cancelled_send(self):
        from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
        assert self._released(self._send_view(RET_CODE__BACK_BUTTON).run, FakePort()).View_cls == BackStackView

    def test_after_a_failed_send(self):
        view = self._send_view()
        view.run_screen = MagicMock(side_effect=RelayError("The USB relay was unplugged"))
        assert self._released(view.run, FakePort()).View_cls == ErrorView

    def test_after_a_receive(self):
        port = FakePort()
        frame = usb_relay.frame_message(b"hi")

        def run():
            with patch.object(usb_relay, "RelayReceiver") as receiver:
                receiver.return_value.result.return_value = frame
                return relay_views.receive_from_relay(self._receive_view())

        assert self._released(run, port) == frame

    def test_after_a_cancelled_receive(self):
        from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
        run = lambda: relay_views.receive_from_relay(self._receive_view(RET_CODE__BACK_BUTTON))
        assert self._released(run, FakePort()) is None

    def test_after_a_failed_receive(self):
        def run():
            with pytest.raises(RelayError):
                relay_views.receive_from_relay(self._receive_view(0))
            return "raised"

        with patch.object(RelayReceiver, "result", side_effect=RelayError("bad")):
            assert self._released(run, FakePort()) == "raised"

    def test_no_spinner_with_nothing_to_reset(self):
        port = FakePort()
        with patch.object(usb_relay, "usb_devices", return_value=[]), \
                patch.object(relay_views, "_with_spinner") as spinner:
            relay_views._release_port(port)
        assert port.closed
        spinner.assert_not_called()
