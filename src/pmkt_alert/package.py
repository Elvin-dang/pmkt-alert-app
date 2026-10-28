""".pmkt – the shared report: one compressed file in parts, each part encrypted only for its readers, the
whole file signed by the Lead. Only PMKT Alert opens it.

layout: b"PMKTALRT" | format=2 (1 byte) | header length (4 bytes) | header JSON | part ciphertexts | Ed25519 sig (64)
- part: zip (deflate) → AES-256-GCM with a random part key
- the part key is wrapped for each reader: ephemeral X25519 → HKDF-SHA256 → AES-GCM (readers are identified
  only by a hash of their public key – no names or PICs in clear)
- "lead" part: always also readable by the signing Lead's own key; "pic:X" parts: only the devices of X's members
- signature over everything before it, checked BEFORE decrypting: members accept only their Lead's files"""
import base64
import hashlib
import io
import json
import os
import struct
import zipfile

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .identity import LeadKeys, raw_public

MAGIC, FORMAT = b"PMKTALRT", 2
EXT = ".pmkt"
_b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
_unb64 = base64.b64decode


class PackageError(Exception):
    pass


def reader_id(pub: X25519PublicKey) -> str:
    return hashlib.sha256(raw_public(pub)).hexdigest()[:16]


def _kek(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"pmkt-part-key").derive(shared)


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def build(parts: dict[str, tuple[dict[str, bytes], list[X25519PublicKey]]], meta: dict, lead: LeadKeys) -> bytes:
    header = {"format": FORMAT, "meta": meta, "parts": [], "wraps": []}
    blobs = []
    for idx, (pid, (files, readers)) in enumerate(parts.items()):
        key, nonce = AESGCM.generate_key(256), os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, _zip(files), f"part{idx}".encode())
        header["parts"].append({"i": idx, "nonce": _b64(nonce), "size": len(ct)})
        blobs.append(ct)
        for pub in readers + ([lead.enc_public] if pid == "lead" else []):
            eph = X25519PrivateKey.generate()
            wn = os.urandom(12)
            wrapped = AESGCM(_kek(eph.exchange(pub))).encrypt(wn, key, None)
            header["wraps"].append({"r": reader_id(pub), "i": idx, "e": _b64(raw_public(eph.public_key())),
                                    "n": _b64(wn), "k": _b64(wrapped)})
    head = json.dumps(header, ensure_ascii=False).encode("utf-8")
    body = MAGIC + bytes([FORMAT]) + struct.pack(">I", len(head)) + head + b"".join(blobs)
    return body + lead.sign.sign(body)


def read_meta(blob: bytes, lead_sign_public: Ed25519PublicKey) -> dict:
    return _verified_header(blob, lead_sign_public)[0]["meta"]


def _verified_header(blob: bytes, lead_sign_public: Ed25519PublicKey) -> tuple[dict, int, bytes]:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 5 + 64:
        raise PackageError("Đây không phải file PMKT Alert (.pmkt)")
    if blob[len(MAGIC)] != FORMAT:
        raise PackageError("File .pmkt của phiên bản app khác – hãy cập nhật app")
    body, sig = blob[:-64], blob[-64:]
    try:
        lead_sign_public.verify(sig, body)
    except InvalidSignature:
        raise PackageError("Sai chữ ký – file không do Lead của bạn phát hành, hoặc đã bị sửa") from None
    (hlen,) = struct.unpack(">I", body[len(MAGIC) + 1:len(MAGIC) + 5])
    start = len(MAGIC) + 5
    return json.loads(body[start:start + hlen]), start + hlen, body


def read(blob: bytes, my_key: X25519PrivateKey, lead_sign_public: Ed25519PublicKey) -> tuple[dict, dict[str, bytes]]:
    header, offset, body = _verified_header(blob, lead_sign_public)
    me = reader_id(my_key.public_key())
    pos, starts = offset, {}
    for p in header["parts"]:
        starts[p["i"]] = (pos, p)
        pos += p["size"]
    files: dict[str, bytes] = {}
    mine = [w for w in header["wraps"] if w["r"] == me]
    if not mine:
        raise PackageError("File này không có phần dành cho bạn – báo cáo được tải lên trước khi bạn đăng nhập trên máy này, hoặc bạn chưa được gán PIC")
    for w in mine:
        try:
            eph = X25519PublicKey.from_public_bytes(_unb64(w["e"]))
            key = AESGCM(_kek(my_key.exchange(eph))).decrypt(_unb64(w["n"]), _unb64(w["k"]), None)
            start, part = starts[w["i"]]
            data = AESGCM(key).decrypt(_unb64(part["nonce"]), body[start:start + part["size"]], f"part{w['i']}".encode())
        except (InvalidTag, KeyError, ValueError):
            raise PackageError("File .pmkt bị hỏng") from None
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            files.update({n: z.read(n) for n in z.namelist()})
    return header["meta"], files
