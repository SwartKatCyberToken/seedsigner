"""Split and reassemble ssmsg1 animated-QR frames.

Does not parse envelopes or draw QR images. decode_qr.MessageCryptoQrDecoder
and models.message_qr.MessageAnimatedQrEncoder are the callers. Frame text is
`ssmsg1 {index}of{count} {chunk}` with a 1-based index. Chunk size is capped
so one frame still fits a QR shown on the 240px screen.
"""

import re

# Characters of JSON per frame, excluding the ssmsg1 header.
QR_FRAGMENT_CHARS = 90
_FRAME_RE = re.compile(r"^ssmsg1 (\d+)of(\d+) (.*)$", re.DOTALL)


def split_frames(payload: str, fragment_chars: int = QR_FRAGMENT_CHARS) -> list:
    """Return one or more ssmsg1 frames that concatenate back to payload."""
    if fragment_chars < 1:
        raise ValueError(f"fragment_chars must be positive, got {fragment_chars}")
    if payload == "":
        chunks = [""]
    else:
        chunks = [
            payload[index:index + fragment_chars]
            for index in range(0, len(payload), fragment_chars)
        ]
    count = len(chunks)
    return [
        f"ssmsg1 {index}of{count} {chunk}"
        for index, chunk in enumerate(chunks, start=1)
    ]


class QrAssembly:
    """Collect ssmsg1 frames until every index is present once."""

    def __init__(self):
        self.total = None
        self._parts = []
        self.payload = None

    @property
    def collected(self) -> int:
        return sum(part is not None for part in self._parts)

    def add(self, segment: str) -> str:
        """Return complete, part, existing, or invalid."""
        match = _FRAME_RE.match(segment)
        if match is None:
            return "invalid"
        index = int(match.group(1))
        total = int(match.group(2))
        chunk = match.group(3)
        if total < 1 or index < 1 or index > total:
            return "invalid"
        if self.total is None:
            self.total = total
            self._parts = [None] * total
        elif total != self.total:
            return "invalid"
        if self._parts[index - 1] is not None:
            return "existing"
        self._parts[index - 1] = chunk
        if any(part is None for part in self._parts):
            return "part"
        self.payload = "".join(self._parts)
        return "complete"
