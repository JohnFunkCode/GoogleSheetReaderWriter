#To continue this session, run codex resume 019c17a2-5330-7af3-9665-a394a4e2d45e

# Google Sheet Reader Writer -- Full Technical Handoff (Updated)

## Project Overview

Python CLI/tooling to help karate tournament organizers:

1. Create or update a shared Google Sheet from a CSV.
2. Protect all columns except the last two (`Judge Assigned`, `Comments`).
3. Share the sheet with configured users.
4. Export a Google Sheet back to CSV.

Tech: Python, pandas, Google Sheets API, Google Drive API, Python Fire, Google auth libs.

------------------------------------------------------------------------

# Current Architecture & Auth

## Auth modes supported
- `service_account`
- `oauth`
- `adc`

### Current intended mode for non-technical users
**OAuth (Desktop App)** with one-time browser consent. No gcloud required.

Rationale for making OAuth the default:
- ADC requires gcloud install and a CLI login, which is too much friction for non-technical users.
- Service accounts are unreliable for personal Gmail Drive (quota/ownership limitations).
- OAuth provides a one-time browser consent and then silent refresh, which is easiest to package.

Key behavior:
- If OAuth paths are omitted in config, defaults are inferred:
  - Client secret: `credentials.json` or `client_secret.json` next to `config/config.yaml`
  - Token: OS-specific user config dir (`gsheet-rw/token.json`) unless overridden
- If OAuth or service account paths are provided as relative paths, they are resolved from the config file directory.
- OAuth tokens are stored in system keyring first, using the resolved `oauth_token_path` as the lookup key.
- If keyring has no token, the app falls back to `oauth_token_path` on disk and migrates that token into keyring.
- If token refresh fails, the app falls back to interactive browser re-auth instead of aborting.
- A debug CLI command can clear the cached token from keyring, with an option to also remove the filesystem fallback token.
- First run shows a message and opens browser for consent.

------------------------------------------------------------------------

# CLI Interface

Module:

    gsheet_rw.cli

Run:

    python -m gsheet_rw.cli

Commands:

## create_from_csv
Args:
- `csv_path`
- `sheet_title`
- `config_path`
- `worksheet_title`
- `drive_folder_name` (required if not in config)
- `share_role` (default: writer)
- `unprotected_last_n` (default: 2)

Behavior (current):
1. Load config.
2. Read CSV into DataFrame.
3. Validate required columns.
4. Resolve Drive folder **by name** (or `"root"` for My Drive root).
5. Use `sheet_registry.yaml` to decide whether to reuse an existing sheet ID.
6. If existing: create a **new timestamp tab** in the existing file.
7. If new: create a new sheet, rename its first tab to a timestamp.
8. Write data, auto-resize columns, then apply styling and protection.
9. Move the new timestamp tab to **leftmost** position.
10. Share file with configured users.

Prints a message like `Created spreadsheet 'Tournament Judges Sheet' (ID: <id>)`
or `Updated spreadsheet 'Tournament Judges Sheet' (ID: <id>)`.

## export_to_csv
Args:
- `spreadsheet_id`
- `csv_path` (or `out_csv_path`)
- `config_path`
- `worksheet_title`

Behavior:
1. Load config.
2. Read from provided worksheet title or the **latest timestamp tab**.
3. Normalize expected column ordering.
4. Save to CSV.

Prints a message like:
`Exported spreadsheet '2026-04-05 10:15:00' from spreadsheet ID <id> to CSV file './out/export.csv'`.

## clear_oauth_token
Args:
- `config_path`
- `clear_filesystem_fallback` (default: false)

Behavior:
1. Load config.
2. Resolve the OAuth token key from `oauth_token_path`.
3. Remove the cached token from keyring.
4. Optionally delete the filesystem fallback token file.

## auth_status
Args:
- `config_path`

Behavior:
1. Load config.
2. Resolve the effective auth paths for the current auth mode.
3. For OAuth mode, report whether keyring has a token and whether the fallback token file exists.

------------------------------------------------------------------------

# Required CSV Schema

Expected columns:
- Division
- Rank
- Age
- Last Name
- Ring #
- Competitor Count
- Judge Assigned
- Comments

Validation fails if any column is missing.

------------------------------------------------------------------------

# Sheet Tabs & Versioning

- Every update writes data to a **new tab** named with a timestamp:
  `YYYY-MM-DD HH:MM:SS`.
- Newest tab is moved to the **leftmost** position.
- Worksheet title is required on create (first tab), but it is renamed immediately.

------------------------------------------------------------------------

# Registry (Avoiding Duplicate Sheets)

A registry file tracks the sheet ID by `(folder_name, sheet_title)`:

- File: `data/sheet_registry.yaml`
- Keyed by **folder name** + **sheet title**
- If ID no longer exists, a new sheet is created and registry updated.

------------------------------------------------------------------------

# Other significant decisions

- **Folder identification uses human-readable folder name** (not ID). It is required on create and can be provided via CLI or config; `"root"` targets My Drive root.
- **In-place updates** were chosen to preserve sharing; new data goes into a timestamp-named tab rather than creating a new file.
- **Newest tab ordering**: each new timestamp tab is moved to the leftmost position for visibility.
- **Secrets handling**: OAuth credentials and token moved into `./secrets/`, which is gitignored.
- **Config location**: config files live in `config/` (`config/config.yaml`, `config/config.example.yaml`).
- **Column header change**: `# Comp` renamed to `Competitor Count` across CSVs and code.
- **UI-agnostic refactor**: core logic moved into `gsheet_rw/app.py` with a public API surface for future Flask/Tkinter UIs.
- **Testability**: `create_from_csv`/`export_to_csv` accept optional injected clients (mockable) and an env-gated integration test was added.
- **Logging**: `print` statements replaced with `logging`; CLI configures a default formatter for local runs.

------------------------------------------------------------------------

# Styling & Protection

## Protection
- All columns except the last `n` are protected (default: 2).
- Only `owner_email` can edit protected columns.

## Styling
- Alternating row fills:
  - Protected columns: light grey (`#d9d9d9`) and dark grey (`#b7b7b7`)
  - Unprotected columns: light blue (`#cfe2f3`) and light blue (`#9fc5e8`)
- Thick horizontal borders between rows; **no vertical borders**.
- Time rows (if first column looks like `9:00 a.m.`, `4:15 pm`, `12:00 noon`, `noon`):
  - Row fill set to white
  - Font size set to 18

## Column width
- Auto-resize all columns to fit data.
- Then widen:
  - `Judge Assigned`: 2× current width
  - `Comments`: 4× current width

------------------------------------------------------------------------

# Files / Modules

- `gsheet_rw/app.py`: Core app logic (used by CLI, reusable for Flask/Tkinter)
- `gsheet_rw/cli.py`: Thin CLI wrapper
- `gsheet_rw/sheets_client.py`: Google Sheets/Drive API operations
- `gsheet_rw/config.py`: Config parsing + OAuth defaults
- `gsheet_rw/registry.py`: Registry file helpers
- `gsheet_rw/__init__.py`: Public API surface (`create_from_csv`, `export_to_csv`)
- `docs/guide-to-authentication.md`: Plain-language guide to authentication setup, token storage, and permissions
- `tests/test_integration_sandbox.py`: Optional integration test (env-gated)

------------------------------------------------------------------------

# Secrets & Paths

- Credentials moved to `./secrets/`
- `secrets/` added to `.gitignore`
- `config/config.yaml` updated to point at `../secrets/credentials.json` and `../secrets/token.json`
- OAuth token cache is keyring-first, with filesystem fallback for migration/debugging

------------------------------------------------------------------------

# Current config/config.example.yaml

- Uses OAuth by default
- Requires `drive_folder_name` (use `"root"` for My Drive root)
- Requires `worksheet_title` on create

------------------------------------------------------------------------

# Notes / Caveats

- Drive folder lookup is by **human-readable name** and errors if duplicates are found.
- Folder lookup will raise a PermissionError on 403 (expected in restricted scopes).
- Network/auth operations must run outside sandbox.
- Integration test runs only when `RUN_INTEGRATION_TESTS=1` and required env vars are set.
- `AGENTS.md` now contains run instructions; this file contains session state/handoff details.

------------------------------------------------------------------------

# Latest Session Notes (2026-02-01 to 2026-02-02)

- Project directory renamed to `GoogleSheetReaderWriter` and checked into GitHub.
- OAuth is now the default recommended path for non-technical users.
- Registry-based reuse prevents duplicate files with the same name.
- Each update creates a timestamped tab; newest tab is leftmost.
- Styling updated with alternating fills, borders, time-row overrides.
- Column headers updated: `# Comp` -> `Competitor Count`.
- `gsheet_rw` refactored so UI-agnostic logic lives in `app.py`.

------------------------------------------------------------------------

# Deployment Model

Local CLI tool executed from developer workstation or packaged UI.
No server deployment required.
