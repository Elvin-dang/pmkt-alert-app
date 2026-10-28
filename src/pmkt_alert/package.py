""".pmkt – the shared run file: one compressed, encrypted, signed file only PMKT Alert opens.

layout: b"PMKTALRT" | format (1 byte) | salt (16) | nonce (12) | AES-256-GCM(zip) | Ed25519 signature (64)
- zip: manifest.json + payload files, deflate-compressed
- key: scrypt(team passphrase, salt); GCM also detects corruption
- signature over everything before it, by the Lead's key: members only accept files from their Lead,
  even someone who knows the passphrase cannot forge one. Checked BEFORE decrypting."""
import io
import json
import os
import zipfile

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC, FORMAT = b"PMKTALRT", 1
EXT = ".pmkt"
_HEAD = len(MAGIC) + 1 + 16 + 12


class PackageError(Exception):
    pass


def derive_key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def build(files: dict[str, bytes], manifest: dict, passphrase: str, signing_key: Ed25519PrivateKey) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("manifest.json", json.dumps({**manifest, "format": FORMAT}, ensure_ascii=False))
        for name, data in files.items():
            z.writestr(name, data)
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + bytes([FORMAT]) + salt + nonce
    body = header + AESGCM(derive_key(passphrase, salt)).encrypt(nonce, buf.getvalue(), header)
    return body + signing_key.sign(body)


def read(blob: bytes, passphrase: str, lead_key: Ed25519PublicKey) -> tuple[dict, dict[str, bytes]]:
    if not blob.startswith(MAGIC) or len(blob) < _HEAD + 16 + 64:
        raise PackageError("Đây không phải file PMKT Alert (.pmkt)")
    if blob[len(MAGIC)] != FORMAT:
        raise PackageError("File .pmkt của phiên bản app khác – hãy cập nhật app")
    body, sig = blob[:-64], blob[-64:]
    try:
        lead_key.verify(sig, body)
    except InvalidSignature:
        raise PackageError("Sai chữ ký – file không do Lead của bạn phát hành, hoặc đã bị sửa") from None
    salt, nonce = body[len(MAGIC) + 1:len(MAGIC) + 17], body[len(MAGIC) + 17:_HEAD]
    try:
        data = AESGCM(derive_key(passphrase, salt)).decrypt(nonce, body[_HEAD:], body[:_HEAD])
    except InvalidTag:
        raise PackageError("Sai mật khẩu nhóm") from None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = {n: z.read(n) for n in z.namelist()}
    return json.loads(files.pop("manifest.json")), files
