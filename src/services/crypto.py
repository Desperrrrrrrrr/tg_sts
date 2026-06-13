import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.config import get_settings


def _fernet() -> Fernet | None:
    key = get_settings().token_encryption_key.strip()
    if not key:
        return None
    # Fernet needs 32 url-safe base64 bytes; derive from arbitrary secret
    derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    return Fernet(derived)


def encrypt_token(plain: str) -> str:
    f = _fernet()
    if f is None:
        return plain
    return f.encrypt(plain.encode()).decode()


def decrypt_token(cipher: str) -> str:
    f = _fernet()
    if f is None:
        return cipher
    try:
        return f.decrypt(cipher.encode()).decode()
    except InvalidToken:
        return cipher
