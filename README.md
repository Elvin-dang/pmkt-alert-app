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

The Lead runs the data and uploads a reviewed report; Members only view, and only their own PIC.

1. **Lead** – first launch → *I'm the Lead* → pick where reports live: Supabase Storage or a shared folder. The app shows a **setup code** (`PMKT1:…`) – send it to each member. It holds the Lead's public signing key and where reports live; it holds no secrets.
2. **Member** – first launch → *I'm a Member* → paste the setup code. The app shows a **member code** (`PMKM-…`) – send it back to the Lead.
3. **Lead** – Settings → Team → add each member code and choose the PIC it may see.
4. After a run, **Upload to team**. The file is named `PMKT-Alert_<date>_<time>.pmkt` and never overwrites an earlier one. Members press **Refresh** and pick a report.

A `.pmkt` file is compressed and encrypted: every PIC's part has its own key, wrapped for each member of that PIC (X25519 + AES-GCM). The whole file is signed by the Lead (Ed25519) and checked before anything is opened. Keys live in `secrets.bin`, which is protected with Windows DPAPI. Use *Export Lead key* (password-protected) to move the Lead role to another machine.

**Supabase setup (once):** create a project, add the Lead as a user under Authentication, copy the Project URL and the anon key into the Lead setup, then sign in under Settings → Team. Run the SQL shown under *Supabase SQL* in the SQL editor. It creates the private `reports` bucket: everyone can read it, and only the Lead's email can upload or delete. Members never need a Supabase account.

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
