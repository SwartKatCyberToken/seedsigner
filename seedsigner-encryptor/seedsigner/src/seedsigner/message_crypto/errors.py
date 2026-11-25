"""Failures for message cryptography that are safe to show on screen.

Does not derive keys, encrypt, or log secrets. Callers in the message menu
catch MessageCryptoError and display str(exc). The message must name the
failed check and must not include key bytes, seed bytes, or plaintext.
"""


class MessageCryptoError(Exception):
    """A message-crypto input or check failed."""
