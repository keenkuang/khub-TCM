import os
import warnings
from typing import Optional
from cryptography.fernet import Fernet


def load_key() -> bytes:
    """Load the Fernet key from environment, file, or generate on demand.

    Priority:
      1. KHUB_PII_KEY env var (base64 urlsafe 44 chars)
      2. KHUB_PII_KEY_FILE env var (default ~/.khub/pii.key)
      3. If neither exists and KHUB_PII_ENCRYPT=1, generate + write to default path.
    Returns b"" if no key available.
    """
    key = os.environ.get("KHUB_PII_KEY")
    if key:
        _validate_key(key.encode("ascii"))
        return key.encode("ascii")

    key_file = os.environ.get("KHUB_PII_KEY_FILE", os.path.expanduser("~/.khub/pii.key"))
    if os.path.exists(key_file):
        with open(key_file, "rb") as f:
            data = f.read().strip()
        _validate_key(data)
        return data

    if os.environ.get("KHUB_PII_ENCRYPT") == "1":
        gen_key = Fernet.generate_key()
        parent = os.path.dirname(key_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(key_file, "wb") as f:
            f.write(gen_key)
        os.chmod(key_file, 0o600)
        warnings.warn(
            f"KHUB_PII_KEY not set; generated new key at {key_file}",
            RuntimeWarning,
            stacklevel=2,
        )
        return gen_key

    return b""


def _validate_key(key: bytes):
    """校验 Fernet key 格式（44 字节 base64url），非法时给出明确错误而非崩溃。"""
    try:
        Fernet(key)
    except Exception as e:
        raise ValueError(
            f"KHUB_PII_KEY 不是合法的 Fernet 密钥（应为 44 字符 base64url 串）：{e}"
        ) from e


class PIICipher:
    """Wrapper around Fernet for PII field encryption / decryption."""

    def __init__(self, key: bytes):
        self.f = Fernet(key)

    def encrypt(self, plain: Optional[str]) -> str:
        if not plain:
            return plain or ""
        return self.f.encrypt(plain.encode()).decode()

    def decrypt(self, token: Optional[str]) -> str:
        if not token:
            return token or ""
        return self.f.decrypt(token.encode()).decode()


def get_cipher() -> Optional[PIICipher]:
    """Return a PIICipher when encryption is enabled, else None.

    Intentionally not cached — re-reads env each call so tests can toggle.
    """
    if os.environ.get("KHUB_PII_ENCRYPT") == "1":
        return PIICipher(load_key())
    return None


def enc(plain: Optional[str]) -> str:
    """Encrypt plaintext when PII encryption is active; otherwise passthrough."""
    c = get_cipher()
    if c is None:
        return plain or ""
    return c.encrypt(plain)


def dec(token: Optional[str]) -> str:
    """Decrypt token when PII encryption is active; otherwise passthrough."""
    c = get_cipher()
    if c is None:
        return token or ""
    return c.decrypt(token)
