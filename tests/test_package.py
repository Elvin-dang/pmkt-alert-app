import pytest

from pmkt_alert.identity import LeadKeys, MemberKey
from pmkt_alert.package import PackageError, build, read


@pytest.fixture(scope="module")
def keys():
    return LeadKeys.new(), MemberKey.new(), MemberKey.new()


def test_each_member_opens_only_their_part(keys):
    lead, a, b = keys
    blob = build({"pic:A": ({"run.json": b"A data"}, [a.public]), "pic:B": ({"run.json": b"B data"}, [b.public]),
                  "lead": ({"run.json": b"everything"}, [])}, {"as_of": "2026-10-25"}, lead)
    meta, files = read(blob, a.private, lead.sign_public)
    assert files == {"run.json": b"A data"} and meta["as_of"] == "2026-10-25"
    assert read(blob, b.private, lead.sign_public)[1] == {"run.json": b"B data"}
    assert read(blob, lead.enc_private, lead.sign_public)[1]["run.json"] == b"everything"  # Lead reads its full part
    assert b"A data" not in blob and b"everything" not in blob


def test_removed_member_cannot_open(keys):
    lead, a, b = keys
    blob = build({"pic:B": ({"x": b"1"}, [b.public])}, {}, lead)
    with pytest.raises(PackageError, match="không có phần"):
        read(blob, a.private, lead.sign_public)


def test_signature_checked(keys):
    lead, a, _ = keys
    forged = build({"pic:A": ({"x": b"1"}, [a.public])}, {}, LeadKeys.new())
    with pytest.raises(PackageError, match="chữ ký"):
        read(forged, a.private, lead.sign_public)
    blob = bytearray(build({"pic:A": ({"x": b"1" * 50}, [a.public])}, {}, lead))
    blob[-80] ^= 1
    with pytest.raises(PackageError, match="chữ ký"):
        read(bytes(blob), a.private, lead.sign_public)


def test_not_a_package(keys):
    lead, a, _ = keys
    with pytest.raises(PackageError, match="không phải file PMKT"):
        read(b"PK\x03\x04 zip", a.private, lead.sign_public)


def test_keys_serialize(keys):
    lead, a, _ = keys
    assert LeadKeys.from_bytes(lead.to_bytes()).sign_public == lead.sign_public
    assert MemberKey.from_bytes(a.to_bytes()).public == a.public
