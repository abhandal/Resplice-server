"""Symmetric encryption for stored Plex tokens.

The Fernet key is derived from SESSION_SECRET via PBKDF2-SHA256, so rotating the
secret invalidates persisted tokens (users will need to re-login). This is fine —
sessions persist independently and tokens are only used for background sync.
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_SECRET = os.environ.get("SESSION_SECRET", "")
if not _SECRET:
    raise RuntimeError(
        "SESSION_SECRET is not set. It encrypts stored Plex tokens, so running "
        "without one would leave them readable to anyone with the data directory. "
        "Generate one with `openssl rand -hex 32` and add it to your .env."
    )
_SALT = b"plex-support-token-v1"


def _key() -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=200_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(_SECRET.encode()))


_fernet = Fernet(_key())


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ""
