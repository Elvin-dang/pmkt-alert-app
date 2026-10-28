"""The Supabase setup SQL, run against a real local Postgres with the few Supabase pieces it relies on stubbed
(auth.email(), auth.users, storage.objects/filename). Skipped when Postgres is not installed."""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from pmkt_alert.supabase import setup_sql

PG_BIN = next((Path(p) for p in [shutil.which("initdb") and Path(shutil.which("initdb")).parent,
                                  *sorted(Path("/opt/homebrew/opt").glob("postgresql@*/bin")),
                                  *sorted(Path("/usr/lib/postgresql").glob("*/bin"))]
               if p and (Path(p) / "initdb").exists()), None)
pytestmark = pytest.mark.skipif(PG_BIN is None, reason="Postgres not installed")

STUBS = """
create role anon nologin; create role authenticated nologin;
create schema auth; create schema storage;
create table auth.users (id uuid primary key default gen_random_uuid(), email text);
create function auth.email() returns text language sql stable as
  $$ select nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email' $$;
create table storage.buckets (id text primary key, name text, public boolean);
create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text, name text);
alter table storage.objects enable row level security;
create function storage.filename(name text) returns text language sql immutable as
  $$ select (string_to_array(name, '/'))[array_length(string_to_array(name, '/'), 1)] $$;
grant usage on schema public, auth, storage to anon, authenticated;
grant all on storage.objects to anon, authenticated;
grant all on all tables in schema public to anon, authenticated;
alter default privileges in schema public grant all on tables to anon, authenticated;
"""


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("pg")
    data = d / "data"
    sock = Path(tempfile.mkdtemp(prefix="pg", dir="/tmp" if Path("/tmp").is_dir() else None))  # unix socket paths max ~100 chars
    subprocess.run([PG_BIN / "initdb", "-D", data, "-U", "postgres", "-A", "trust"], check=True, capture_output=True)
    subprocess.run([PG_BIN / "pg_ctl", "-D", data, "-o", f"-k {sock} -p 55432 -c listen_addresses=''", "-l", d / "pg.log", "-w", "start"],
                   check=True, capture_output=True)
    psql = [PG_BIN / "psql", "-h", str(sock), "-p", "55432", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-qAt"]

    def sql(text: str, email: str | None = None, role: str = "authenticated") -> str:
        if email is not None or role != "postgres":
            claims = json.dumps({"email": email}) if email else ""
            text = f"set role {role}; select set_config('request.jwt.claims', '{claims}', false);\n{text}"
        r = subprocess.run(psql, input=text, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip())
        return r.stdout.strip()

    sql(STUBS, role="postgres")
    sql(setup_sql("Lead@Team.com"), role="postgres")
    yield sql
    subprocess.run([PG_BIN / "pg_ctl", "-D", data, "-m", "immediate", "stop"], capture_output=True)
    shutil.rmtree(sock, ignore_errors=True)


def lines(out: str) -> list[str]:
    return [x for x in out.splitlines() if x and not x.startswith("{") and x not in ("", "SET")][-50:]


def last(out: str) -> str:
    return out.splitlines()[-1] if out else ""


LEAD = "lead@team.com"


def test_lead_manages_members_and_members_cannot_escalate(db):
    db("insert into pmkt_members (email, role, pic, name) values ('a@team.com', 'member', 'PIC A', 'A'),"
       " ('b@team.com', 'member', 'PIC B', 'B');", LEAD)
    seen_by_lead = db("select string_agg(email, ',' order by email) from pmkt_members;", LEAD)
    assert last(seen_by_lead) == "a@team.com,b@team.com,lead@team.com"
    seen_by_a = db("select string_agg(email, ',' order by email) from pmkt_members;", "a@team.com")
    assert last(seen_by_a) == "a@team.com,lead@team.com"  # self + leads (for their signing key), never other PICs
    for attack in ("update pmkt_members set role = 'lead' where email = 'a@team.com';",
                   "update pmkt_members set pic = 'PIC B' where email = 'a@team.com';",
                   "delete from pmkt_members where email = 'b@team.com';"):
        db(attack, "a@team.com")  # RLS: silently affects 0 rows
    assert last(db("select role || pic from pmkt_members where email = 'a@team.com';", LEAD)) == "memberPIC A"
    assert last(db("select count(*) from pmkt_members;", LEAD)) == "3"
    with pytest.raises(RuntimeError):
        db("insert into pmkt_members (email, role, pic) values ('x@team.com', 'lead', null);", "a@team.com")
    with pytest.raises(RuntimeError):
        db("select * from pmkt_members;", None, role="anon")


def test_emails_stored_lowercase(db):
    with pytest.raises(RuntimeError):
        db("insert into pmkt_members (email, role, pic) values ('Mixed@Team.com', 'member', 'PIC C');", LEAD)


def test_signup_only_for_listed_active_emails(db):
    db("insert into auth.users (email) values ('a@team.com');", role="postgres")
    with pytest.raises(RuntimeError, match="PMKT"):
        db("insert into auth.users (email) values ('stranger@x.com');", role="postgres")
    db("insert into pmkt_members (email, role, pic, active) values ('gone@team.com', 'member', 'PIC A', false);", LEAD)
    with pytest.raises(RuntimeError, match="PMKT"):
        db("insert into auth.users (email) values ('gone@team.com');", role="postgres")


def test_register_keys(db):
    db("select pmkt_register_keys('K1', 'S-member');", "b@team.com")
    db("select pmkt_register_keys('K2', null);", "b@team.com")
    db("select pmkt_register_keys('K1', null);", "b@team.com")  # same device again: no duplicate
    for k in ("K3", "K4"):
        db(f"select pmkt_register_keys('{k}', null);", "b@team.com")
    row = last(db("select array_to_string(enc_keys, ',') || '|' || coalesce(sign_pub, '-') from pmkt_members"
                  " where email = 'b@team.com';", LEAD))
    assert row == "K1,K3,K4|-"  # last 3 devices (K1 re-registered = recent); a member can never publish a signing key
    db("select pmkt_register_keys('L1', 'SIGN1');", LEAD)
    db("select pmkt_register_keys('L1', 'SIGN2');", LEAD)  # no silent swap of the Lead's signing key
    assert last(db(f"select sign_pub from pmkt_members where email = '{LEAD}';", LEAD)) == "SIGN1"
    db("select pmkt_register_keys('L1', 'SIGN2', true);", LEAD)  # explicit reset
    assert last(db(f"select sign_pub from pmkt_members where email = '{LEAD}';", LEAD)) == "SIGN2"


def test_storage_each_member_reads_only_own_pic_file(db):
    a, b = (hashlib.md5(p.encode()).hexdigest() + ".pmkt" for p in ("PIC A", "PIC B"))
    db("insert into storage.objects (bucket_id, name) values "
       f"('reports', 'R1/lead.pmkt'), ('reports', 'R1/{a}'), ('reports', 'R1/{b}'), ('reports', 'R2/{b}');", LEAD)
    names = lambda who: last(db("select coalesce(string_agg(name, ',' order by name), '-') from storage.objects;", who))  # noqa: E731
    assert names(LEAD) == f"R1/{a},R1/{b},R1/lead.pmkt,R2/{b}"
    assert names("a@team.com") == f"R1/{a}"
    assert names("b@team.com") == f"R1/{b},R2/{b}"
    with pytest.raises(RuntimeError):
        db(f"insert into storage.objects (bucket_id, name) values ('reports', 'R3/{a}');", "a@team.com")
    db("delete from storage.objects;", "a@team.com")
    assert names(LEAD).count(",") == 3
    db("update pmkt_members set active = false where email = 'a@team.com';", LEAD)
    assert names("a@team.com") == "-"
