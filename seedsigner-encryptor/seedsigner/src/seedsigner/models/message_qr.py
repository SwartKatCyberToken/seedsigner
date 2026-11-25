"""Animated QR encoder for ssmsg1 message envelopes.

Does not derive keys or parse envelopes. MessageQrView passes compact JSON and
the user's density and speed settings. Frames use the same header QrAssembly
accepts. Density sets the fragment size and speed sets how long each frame is
held. Medium is the default for both.
"""

from dataclasses import dataclass

from seedsigner.message_crypto.qr_codec import QR_FRAGMENT_CHARS, split_frames
from seedsigner.models.encode_qr import BaseSimpleAnimatedQREncoder
from seedsigner.models.settings_definition import SettingsConstants


@dataclass
class MessageAnimatedQrEncoder(BaseSimpleAnimatedQREncoder):
    payload: str = ""
    qr_speed: str = SettingsConstants.QR_SPEED__MEDIUM

    @property
    def qr_max_fragment_size(self):
        density_mapping = {
            SettingsConstants.DENSITY__LOW: QR_FRAGMENT_CHARS // 2,
            SettingsConstants.DENSITY__MEDIUM: QR_FRAGMENT_CHARS,
            SettingsConstants.DENSITY__HIGH: QR_FRAGMENT_CHARS * 2,
        }
        return density_mapping.get(self.qr_density, QR_FRAGMENT_CHARS)

    @property
    def frame_delay_seconds(self):
        medium = 10 / 30.0
        speed_mapping = {
            SettingsConstants.QR_SPEED__SLOW: 15 / 30.0,
            SettingsConstants.QR_SPEED__MEDIUM: medium,
            SettingsConstants.QR_SPEED__FAST: 5 / 30.0,
        }
        return speed_mapping.get(self.qr_speed, medium)

    def _create_parts(self):
        self.parts = split_frames(self.payload, self.qr_max_fragment_size)
