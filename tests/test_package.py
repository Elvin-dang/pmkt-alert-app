import pytest

from pmkt_alert.identity import invite_code, new_lead_key, public_key_from_invite
from pmkt_alert.package import PackageError, build, read

PASS = "mật khẩu nhóm rất dài 2026"


@pytest.fixture(scope="module")
def lead():
    return new_lead_key()


def test_roundtrip(lead):
    blob = build({"result.json": b'{"a": 1}', "logic.xlsx": b"x" * 5000}, {"as_of": "2026-10-25", "by": "Lead"},
                 PASS, lead)
    manifest, files = read(blob, PASS, lead.public_key())
    assert manifest["as_of"] == "2026-10-25" and manifest["format"] == 1
    assert files["result.json"] == b'{"a": 1}' and len(files["logic.xlsx"]) == 5000
    assert len(blob) < 1000  # compressed before encryption
    assert b"result.json" not in blob and b'"a": 1' not in blob  # nothing readable inside


def test_wrong_passphrase(lead):
    blob = build({"x": b"1"}, {}, PASS, lead)
    with pytest.raises(PackageError, match="mật khẩu"):
        read(blob, "sai rồi", lead.public_key())


def test_not_signed_by_this_lead(lead):
    blob = build({"x": b"1"}, {}, PASS, new_lead_key())  # someone else who knows the passphrase
    with pytest.raises(PackageError, match="chữ ký"):
        read(blob, PASS, lead.public_key())


def test_tampered(lead):
    blob = bytearray(build({"x": b"1" * 100}, {}, PASS, lead))
    blob[40] ^= 1
    with pytest.raises(PackageError, match="chữ ký"):
        read(bytes(blob), PASS, lead.public_key())


def test_not_a_package():
    with pytest.raises(PackageError, match="không phải file PMKT"):
        read(b"PK\x03\x04 a zip", PASS, new_lead_key().public_key())


def test_invite_code_roundtrip(lead):
    code = invite_code(lead.public_key())
    assert code.startswith("PMKT-") and public_key_from_invite(code.lower().replace("-", " ")) == lead.public_key()
    with pytest.raises(ValueError):
        public_key_from_invite("PMKT-XXXX")
