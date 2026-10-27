# PMKT Alert

Windows desktop app for an Amazon performance-marketing team. It reads the team's daily Excel exports, runs the alert logic (PL pacing vs target, PL trend L7D vs P7D, campaign actions, action-log follow-up) and shows per-PIC alerts. With [Claude Code](https://claude.com/claude-code) installed and logged in, it also writes insights, to-dos and Slack-ready messages in your own writing style, reviews the logic for gaps after every run, and turns your "not reasonable" feedback into backtested logic changes that you approve.

## Install

1. Download `PMKT-Alert-vX.Y.Z.exe` from [Releases](../../releases).
2. Optional, for AI features: install Claude Code and log in once (`claude` in a terminal).
3. Run the exe, pick the folder with the input files, press **Chạy**.

The app checks GitHub Releases for new versions (Settings → Phiên bản & cập nhật) and updates itself after verifying the SHA-256 checksum.

## Inputs

Three data files and two setting files, recognised by their sheets/columns rather than file names:

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
