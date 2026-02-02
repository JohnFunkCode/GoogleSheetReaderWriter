#To continue this session, run codex resume 019c17a2-5330-7af3-9665-a394a4e2d45e

# Google Sheet Reader Writer -- Full Technical Handoff

## Project Overview

This project is a Python CLI tool designed to support karate tournament
organizers by:

1.  Creating a Google Sheet from a CSV file.
2.  Protecting all columns except the last two (`Judge Assigned`,
    `Comments`).
3.  Sharing the sheet with configured users.
4.  Exporting a Google Sheet back to CSV.

The system is built using: - Python - pandas - Google Sheets API -
Google Drive API - Python Fire (CLI) - Google authentication libraries

------------------------------------------------------------------------

# Final Architecture Decision

The system supports three authentication modes:

-   `service_account`
-   `oauth`
-   `adc` (Application Default Credentials)

### Final Working Mode: `auth_mode: "adc"`

ADC was selected because:

-   Personal Gmail accounts cannot use Shared Drives.
-   Service accounts have no usable Drive storage in personal Gmail
    contexts.
-   OAuth required `client_secret.json`, which added unnecessary
    friction.
-   ADC uses the local user's Google identity and Drive quota.

This removed the need for: - `client_secret.json` - Service account
Drive ownership complexity

------------------------------------------------------------------------

# Authentication Setup (ADC)

### One-time setup:

    gcloud auth application-default login   --scopes="https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive"

### Runtime behavior (sheets_client.py):

    creds, project_id = google.auth.default(scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

No client secret file required.

------------------------------------------------------------------------

# CLI Interface

Module:

    gsheet_rw.cli

Run:

    python -m gsheet_rw.cli

## Command 1: create_from_csv

Arguments: - `csv_path` - `sheet_title` - `config_path` - Optional: -
`worksheet_title` - `share_role` (default: writer) -
`unprotected_last_n` (default: 2)

### Behavior

1.  Load config.
2.  Read CSV into pandas DataFrame.
3.  Validate required columns.
4.  Create spreadsheet.
5.  Write DataFrame to sheet.
6.  Protect all columns except last two.
7.  Share with configured emails.
8.  Return spreadsheet ID.

------------------------------------------------------------------------

## Command 2: export_to_csv

Arguments: - `spreadsheet_id` - `out_csv_path` - `config_path` -
Optional: `worksheet_title`

### Behavior

1.  Load config.
2.  Read sheet into DataFrame.
3.  Normalize column structure.
4.  Save to CSV.

------------------------------------------------------------------------

# Required CSV Schema

Expected columns:

-   Division

-   Rank

-   Age

-   Last Name

-   Ring \#

-   Competitor Count

-   Judge Assigned

-   Comments

Validation fails if any column is missing.

------------------------------------------------------------------------

# Sheet Protection Logic

All columns except the last two are protected using the Sheets API.

Default behavior: - Protect columns 0 → total_columns - 2 - Only
`owner_email` may edit protected columns

------------------------------------------------------------------------

# Sharing Logic

Uses Drive API permissions:

-   Role default: writer
-   Sends notification email
-   Supports shared drives via `supportsAllDrives=True`

------------------------------------------------------------------------

# Spreadsheet Creation Logic

If `drive_folder_id` provided: - Create via Drive API `files.create` -
MIME type: `application/vnd.google-apps.spreadsheet` - Parent folder
assigned - Rename default sheet if necessary

If not: - Create via Sheets API directly

------------------------------------------------------------------------

# Final config.yaml (Working Version)

``` yaml
auth_mode: "adc"

owner_email: "owner@example.com"
share_emails:
  - "helper@example.com"

drive_folder_id: null
worksheet_title: "Sheet1"
```

------------------------------------------------------------------------

# Issues Encountered and Resolved

## 1. 403 SERVICE_DISABLED

Cause: APIs not enabled\
Fix: Enabled Sheets and Drive APIs.

## 2. 403 Permission Denied (Service Account)

Cause: Service account lacked Drive context\
Fix: Switched creation to Drive API and eventually abandoned service
account for personal Gmail.

## 3. 404 Folder Not Found

Cause: Folder name used instead of ID\
Fix: Use actual Drive folder ID.

## 4. 403 storageQuotaExceeded

Cause: Service account has no Drive quota in personal Gmail\
Fix: Switch to ADC mode.

## 5. FileNotFoundError for client_secret.json

Cause: Config defaulted to OAuth\
Fix: Added support for `auth_mode: "adc"` and updated config validation.

## 6. PyCharm Auto-Apply Corruption

Cause: Bad patch injection\
Fix: Replaced modules with clean full versions manually.

------------------------------------------------------------------------

# Current System State

System is stable and working with:

-   Personal Gmail
-   ADC authentication
-   Proper sheet creation
-   Column protection logic
-   Sharing logic
-   CSV export
-   No client_secret.json required
-   No service account required

------------------------------------------------------------------------

# Open Enhancements (Optional Future Work)

1.  Add dry-run mode
2.  Add idempotent update mode (update existing sheet instead of always
    creating)
3.  Add integration tests
4.  Replace print statements with structured logging
5.  Print loaded config path at startup
6.  Validate required OAuth scopes at runtime
7.  Package as installable CLI tool

------------------------------------------------------------------------

# Deployment Model

Local CLI tool executed from developer workstation.

No server deployment required.

------------------------------------------------------------------------

# Final Recommendation

For personal Gmail usage: continue using `auth_mode: "adc"`.

For organizational continuity or team-owned storage: migrate to Google
Workspace and Shared Drive with service account support retained.

------------------------------------------------------------------------

# Latest Session Notes (2026-02-01)

- Attempted to run `create_from_csv` inside the Codex sandbox, but it
  failed because outbound DNS/network access is blocked (could not
  reach `oauth2.googleapis.com` for ADC token refresh).
- Ran the command locally instead and it succeeded.
- Created spreadsheet ID:
  `1sU34hwTHuV39hq7odK6yfpqd1YH1OdctOLAjcGHECiE`.
- Conclusion: any auth-dependent operations must be run outside the
  sandbox in a network-enabled environment.

------------------------------------------------------------------------

# Latest Session Notes (2026-02-01) — OAuth packaging for non-technical user

## Goal
Make OAuth the easiest path for a non-technical user to update a single sheet owned by the developer, without gcloud/ADC.

## Decisions
- Chosen auth flow for this user: **OAuth (Desktop App)** with one-time browser consent.
- Service account rejected due to personal Gmail limitations.
- ADC rejected because the user cannot install/manage gcloud.

## Code changes
1) **OAuth default paths (zero-config friendly)**
   - If `auth_mode: "oauth"` and paths are omitted, defaults resolve automatically.
   - OAuth client secret default: look for `credentials.json` or `client_secret.json` next to `config.yaml`.
   - OAuth token default: OS-specific user config dir (`gsheet-rw/token.json`).
   - Implemented in `gsheet_rw/config.py`.

2) **OAuth missing credentials error**
   - Clear error if OAuth client JSON is not found, with guidance.
   - Implemented in `gsheet_rw/sheets_client.py`.

3) **First-run CLI message**
   - When OAuth consent is needed, prints:
     - First run: browser window will open for consent (one-time).
     - Re-authorization: browser window will open to re-authorize.
   - Implemented in `gsheet_rw/sheets_client.py`.

4) **Example config + README updated**
   - `config.example.yaml` switched to OAuth and shows defaults.
   - README updated to document default OAuth token locations.

## Files touched
- `gsheet_rw/config.py`
- `gsheet_rw/sheets_client.py`
- `config.example.yaml`
- `README.md`

## Current packaging guidance (for the non-technical user)
- Ship `config.yaml` + `credentials.json` together.
- Set `auth_mode: "oauth"` in config.
- Run the CLI once to complete browser consent; tokens stored locally in the default location.

## Next potential steps
- Add branded/clearer first-run message text if desired.
- Build a Tkinter helper for consent (user deferred for later).
- Prepare a simple installer/bundle (optional).
