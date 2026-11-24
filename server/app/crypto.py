"""Local encryption helpers.

OAuth refresh tokens and access tokens are encrypted at rest with a key kept
in the local data directory (never committed). This is machine-bound
protection for a localhost app, not a replacement for OS-level disk crypto.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _load_or_create_key() -> bytes:
    path: Path = settings.SECRET_KEY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = path.read_bytes().strip()
        if data:
            return data
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


_fernet: Fernet | None = None


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt(plain: str) -> str:
    if plain is None:
        return ""
    return fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def random_token(nbytes: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(nbytes)).decode("ascii").rstrip("=")
