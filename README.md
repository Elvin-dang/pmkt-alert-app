# PMKT Alert

Windows desktop app for an Amazon performance-marketing team. It reads the team's daily Excel exports, runs the alert logic (PL pacing vs target, PL trend L7D vs P7D, campaign actions, action-log follow-up) and shows per-PIC alerts. With [Claude Code](https://claude.com/claude-code) installed and logged in, it also writes insights, to-dos and Slack-ready messages in your own writing style, reviews the logic for gaps after every run, and turns your "not reasonable" feedback into backtested logic changes that you approve.

## Install

1. Download `PMKT-Alert.exe` from the latest [Release](../../releases/latest) (the version is shown inside the app).
2. Optional, for AI features: install Claude Code and log in once (`claude` in a terminal).
3. Run the exe, pick the folder with the input files, press **Chạy**.

The app checks GitHub Releases for new versions (Settings → Phiên bản & cập nhật) and updates itself after verifying the SHA-256 checksum.

## Inputs

Data can be `.xlsx` or `.csv` (mixed is fine); the logic file must be `.xlsx`. Files are recognised by their sheets/columns rather than file names. As CSV, the tracking workbook becomes three files (`raw_sso_us`, `Product Info`, `KPI`, plus optional `INELIGIBLE ASIN`).

| Role | Must contain |
|---|---|
| Tracking | sheets `raw_sso_us`, `Product Info`, `KPI` (optional `INELIGIBLE ASIN`, `Summary`) |
| Ads by campaign | sheet `ads_camp` |
| Activity log | first sheet with columns `Level`, `username` |
| Alert logic | sheets `Config`, `Matrix_PL` (thresholds read by label) |
| Data dictionary | first sheet with column `Tên File` |

## Data & privacy

- Everything runs locally. Only the computed alert summaries (never raw rows) are sent to Claude, through **your own** Claude Code login.
- Every number Claude writes is checked against the rule output; sentences with numbers that don't match are dropped.
- Logic changes are never applied automatically. Approved changes are saved as a new `Alert_Logic_Ver N.xlsx`.
- User data (logic versions, lessons, feedback, writing style, run history) lives in `%APPDATA%\PMKT Alert` and survives updates.
- This repository contains no business data; tests use synthetic files.

## Team: Lead and Members

The team server (one Supabase project) is built into the app through `src/pmkt_alert/team.json`, which holds the project URL and the public anon key. Nobody on the team touches infrastructure:
- **Lead:** signs in, then creates accounts under Settings → Team (email, name, PIC, role). The app generates a first password for the Lead to hand over; no email is ever sent. From the same screen the Lead can reset a password, lock or unlock an account, or delete it, and every change takes effect immediately.
- **Members:** sign in and see only their own PIC, read-only. Anyone can change their own password.

**Who can do what** is enforced inside Supabase, not by the app:
- Row-level security on `pmkt_members` and on the private `reports` bucket:
  - A member reads only their own row and the Leads' public signing keys.
  - A member downloads only `<report>/<md5(their PIC)>.pmkt`.
  - Only Leads upload or delete reports.
- Public sign-up is disabled. Logins are created by the `pmkt-admin` function (`supabase/functions/pmkt-admin`), which holds the service key on the server side and accepts calls only from an active Lead.
- Tests: the rules run against a real Postgres (`tests/test_team_sql.py`), and the function has Deno tests (`tests/test_edge_function.py`).

**Encryption on top.** Each upload contains one file per PIC plus a full file for Leads.
- Each file is encrypted for the devices of the people allowed to read it (X25519 + AES-GCM) and signed by the Lead (Ed25519). Supabase only stores encrypted files.
- Device keys live in `secrets.bin`, protected with Windows DPAPI.
- A report uploaded before someone's first sign-in on a device doesn't include that device.
- To move the Lead to a new machine, use *Export Lead key* (the file is password-protected).

**App owner, once (re-runnable):**
1. Create a Supabase access token and save it to `~/.supabase-pmkt-token`.
2. Run `python scripts/provision_supabase.py --lead-email lead@company.com`. It creates the project, schema, security rules and function, disables sign-ups, and creates the first Lead login (the password is saved to `~/PMKT-Lead-login.txt`). It also writes `team.json`; commit that file.

## Develop

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/python -m pmkt_alert.app
```

## Release

```bash
git tag v1.0.0 && git push origin v1.0.0
```

GitHub Actions builds the Windows exe, attaches it with its `.sha256` and generates release notes from the commits.
