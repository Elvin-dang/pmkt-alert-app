"""Lead / Member identity: the Lead's Ed25519 signing key, the invite code members enter (the Lead's
public key + checksum), and local protection of secrets (Windows DPAPI per user account)."""
import base64
import hashlib
import re
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def new_lead_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _raw(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def invite_code(pub: Ed25519PublicKey) -> str:
    raw = _raw(pub)
    text = base64.b32encode(raw + hashlib.sha256(raw).digest()[:2]).decode().rstrip("=")
    return "PMKT-" + "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def public_key_from_invite(code: str) -> Ed25519PublicKey:
    text = re.sub(r"[^A-Z2-7]", "", code.upper().replace("PMKT", "", 1))
    try:
        data = base64.b32decode(text + "=" * (-len(text) % 8))
    except ValueError:
        raise ValueError("Mã mời không hợp lệ") from None
    raw, check = data[:32], data[32:]
    if len(data) != 34 or hashlib.sha256(raw).digest()[:2] != check:
        raise ValueError("Mã mời không hợp lệ – kiểm tra lại từng ký tự")
    return Ed25519PublicKey.from_public_bytes(raw)


def private_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def private_from_bytes(data: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(data)


def protect(data: bytes) -> bytes:
    """Encrypt for the current Windows user (DPAPI). Elsewhere (dev machines) returned as-is."""
    if sys.platform != "win32":
        return data
    return _dpapi(data, encrypt=True)


def unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    return _dpapi(data, encrypt=False)


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
