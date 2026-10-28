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

Everyone signs in with their work email and a 6-digit code (Supabase Auth). The Lead runs the data, reviews it and uploads the report. Members only view, and only their own PIC.

**One-time setup (Lead)**
1. Create a Supabase project (the Free plan is enough).
2. Authentication → Email Templates → *Magic Link*: put `{{ .Token }}` in the body, so the email contains the 6-digit code.
3. In the app's sign-in dialog, open *First-time Lead*, enter the Lead's email, then copy the SQL and run it in the project's SQL Editor. It creates:
   - `pmkt_members`: who is Lead, and which PIC each member sees.
   - The private `reports` bucket.
   - The row-level security rules.
   - A guard that only lets listed emails sign up.
4. Paste the Project URL and anon key (Project Settings → API) into the app, then sign in as the Lead.
5. Optional: set the repository variables `PMKT_SUPABASE_URL` and `PMKT_SUPABASE_ANON`. Release builds then include them, so people only type their email. The anon key is meant to be public; the rules below protect the data.

**Accounts.** Under Settings → Team, the Lead creates accounts (email, name, PIC, role). People sign in with that email. Changing a PIC, locking an account or deleting it takes effect immediately.

**Who can do what (enforced by Postgres row-level security, not by the app):**
- Leads read and write the member list and upload or delete reports.
- A member can read only their own row and the Leads' public signing keys.
- A member can download only `<report>/<md5(their PIC)>.pmkt`.
- A device can publish its own public keys, but can't change its role or PIC, and only a Lead can set a signing key.
- The rules are tested against a real Postgres in `tests/test_team_sql.py`.

**Encryption on top.** Each upload contains one file per PIC plus a full file for Leads.
- Each file is encrypted for the devices of the people allowed to read it (X25519 + AES-GCM) and signed by the Lead (Ed25519).
- Supabase only ever stores encrypted files.
- Device keys live in `secrets.bin`, protected with Windows DPAPI.
- A report uploaded before someone's first sign-in on a device doesn't include that device.
- To move the Lead role to a new machine, use *Export Lead key* (the file is password-protected). If the key file is lost, *Create a new key* works, but older reports will no longer open.

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
