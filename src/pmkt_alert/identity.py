"""Device keys.

Lead: Ed25519 signing key (members accept only files signed by it) + X25519 key (reads the full Lead file).
Member: X25519 key. Public halves are published to the team's member list at sign-in (supabase.py).
Secrets on disk are protected for the Windows user account (DPAPI)."""
import sys
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

_RAW = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
_PRIV = (serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def raw_public(pub) -> bytes:
    return pub.public_bytes(*_RAW)


@dataclass
class LeadKeys:
    sign: Ed25519PrivateKey
    enc: X25519PrivateKey

    @classmethod
    def new(cls) -> "LeadKeys":
        return cls(Ed25519PrivateKey.generate(), X25519PrivateKey.generate())

    @property
    def sign_public(self) -> Ed25519PublicKey:
        return self.sign.public_key()

    @property
    def enc_private(self) -> X25519PrivateKey:
        return self.enc

    @property
    def enc_public(self) -> X25519PublicKey:
        return self.enc.public_key()

    def to_bytes(self) -> bytes:
        return self.sign.private_bytes(*_PRIV) + self.enc.private_bytes(*_PRIV)

    @classmethod
    def from_bytes(cls, b: bytes) -> "LeadKeys":
        return cls(Ed25519PrivateKey.from_private_bytes(b[:32]), X25519PrivateKey.from_private_bytes(b[32:64]))


@dataclass
class MemberKey:
    private: X25519PrivateKey

    @classmethod
    def new(cls) -> "MemberKey":
        return cls(X25519PrivateKey.generate())

    @property
    def public(self) -> X25519PublicKey:
        return self.private.public_key()

    def to_bytes(self) -> bytes:
        return self.private.private_bytes(*_PRIV)

    @classmethod
    def from_bytes(cls, b: bytes) -> "MemberKey":
        return cls(X25519PrivateKey.from_private_bytes(b))


def protect(data: bytes) -> bytes:
    """Encrypt for the current Windows user (DPAPI). Elsewhere (dev machines) returned as-is."""
    return _dpapi(data, encrypt=True) if sys.platform == "win32" else data


def unprotect(data: bytes) -> bytes:
    return _dpapi(data, encrypt=False) if sys.platform == "win32" else data


def _dpapi(data: bytes, encrypt: bool) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x01, ctypes.byref(dst)):  # UI_FORBIDDEN
        raise OSError("Windows không giải mã được dữ liệu bảo mật của app (khác tài khoản Windows?)")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)
