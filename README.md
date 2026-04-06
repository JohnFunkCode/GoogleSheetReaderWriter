# Google Sheet Reader Writer

Sample CLI app (Python + Fire) that:
1. Loads a CSV into a Pandas DataFrame and create a Google Sheet populated with that data, **protecting all columns except the last two**
   (`Judge Assigned`, `Comments`), then share it with a list of users.
2. Reads a Google Sheet into a DataFrame and export it to CSV.

## CSV schema

Expected columns (in this order):

- Division
- Rank
- Age
- Last Name
- Ring #
- Competitor Count
- Judge Assigned
- Comments

## Google Cloud setup

### Enable APIs

Google Cloud Console → APIs & Services → Library → enable:

- Google Sheets API
- Google Drive API

## Auth options

This project supports three auth modes via `config/config.yaml`:

- `auth_mode: "adc"` (recommended for personal `@gmail.com`)
- `auth_mode: "oauth"` (desktop OAuth client)
- `auth_mode: "service_account"` (recommended for Google Workspace + Shared Drive)

### ADC setup (personal Gmail)

Run once (and again if scopes change):

```bash
gcloud auth application-default login --scopes="https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive"
```

### OAuth setup (personal Gmail)

Authentication setup guide:
- [Guide to authentication setup](docs/guide-to-authentication.md)

1. Google Cloud Console → APIs & Services → OAuth consent screen
   - User type: **External**
   - Add yourself as a test user (or publish, if needed)
2. APIs & Services → Credentials → Create Credentials → **OAuth client ID**
   - Application type: **Desktop app**
3. Download the OAuth client JSON as `../secrets/credentials.json` relative to `config/config.yaml`
   (or set `oauth_client_secret_json` in `config/config.yaml`; relative paths are resolved from the config file directory).
4. Optional: set `oauth_token_path` in `config/config.yaml`.
   If omitted, the default is:
   - macOS: `~/Library/Application Support/gsheet-rw/token.json`
   - Windows: `%APPDATA%\gsheet-rw\token.json`
   - Linux: `~/.config/gsheet-rw/token.json`
5. First run will open a browser for consent; the OAuth token is stored in the system keyring.
6. If the token is not present in keyring, the app still checks `oauth_token_path` on disk and migrates that token into keyring after a successful load.
7. If a cached token becomes stale or tied to an old OAuth client secret, the app falls back to browser re-auth automatically.

### Service account setup (Workspace / automation)

1. IAM & Admin → Service Accounts → Create (e.g., `karate-tournament-sheets-bot`)
2. Create a JSON key (Keys → Add Key → JSON) and set `service_account_json` in `config/config.yaml`.
3. (Recommended) Create a Drive folder and share it with the service account email as **Editor**; set `drive_folder_id`.

> Note: Service accounts often cannot create files in personal Gmail Drive, and may have zero Drive quota. Use OAuth for personal Gmail.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Testing

### Integration test (optional)

An integration test is available and runs only when environment variables are set:

```bash
RUN_INTEGRATION_TESTS=1 \
SANDBOX_SPREADSHEET_ID="..." \
SANDBOX_WORKSHEET_TITLE="..." \
pytest -k integration
```

Optional env override:
- `GSHEET_RW_CONFIG_PATH` (defaults to `config/config.yaml`)

## Usage

## Interaction diagram

```mermaid
flowchart LR
  CLI[gsheet_rw/cli.py] --> APP[gsheet_rw/app.py]

  APP --> CFG[gsheet_rw/config.py]
  APP --> REG[gsheet_rw/registry.py]
  APP --> SC[gsheet_rw/sheets_client.py]

  CFG --> APP
  REG --> APP
  SC --> APP

  subgraph Sheets APIs
    SC --> SheetsAPI[Google Sheets API]
    SC --> DriveAPI[Google Drive API]
  end

  API[gsheet_rw/__init__.py] --> APP
```

### Create a sheet from CSV

You can either pass `--sheet_title` on the CLI or set `spreadsheet_title` in `config/config.yaml`.
If both are provided, the CLI argument wins.

```bash
gsheet-rw create_from_csv \
  --csv_path "./data/test_data.csv" \
  --sheet_title "Karate Tournament - Ring Assignments" \
  --drive_folder_name "root" \
  --config_path "./config/config.yaml"
```

You can also call the library directly with an in-memory config:

```python
from pathlib import Path

from gsheet_rw import create_from_csv
from gsheet_rw.config import AppConfig

cfg = AppConfig(
    auth_mode="oauth",
    oauth_client_secret_json=Path("../secrets/credentials.json"),
    oauth_token_path=Path("../secrets/token.json"),
    owner_email="you@example.com",
    share_emails=["judge1@example.com", "judge2@example.com"],
    drive_folder_name="root",
    spreadsheet_title="Tournament Judges Sheet",
    worksheet_title="Initial",
)

create_from_csv(
    csv_path="./data/test_data.csv",
    config=cfg,
)
```

CLI output will be a message like:

```text
Created spreadsheet 'Karate Tournament - Ring Assignments' (ID: 123abc...)
```

or:

```text
Updated spreadsheet 'Karate Tournament - Ring Assignments' (ID: 123abc...)
```

Notes:
- `drive_folder_name` is required for create. Use `"root"` for My Drive root.
- Each update writes data into a **new tab** named with a timestamp (`YYYY-MM-DD HH:MM:SS`).
- The tool tracks `(folder_name, sheet_title) -> spreadsheet_id` in `data/sheet_registry.yaml`
  to avoid creating duplicates.

### Export a sheet to CSV

Spreadsheet ID is the part after `/d/` in the URL:
`https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`

```bash
gsheet-rw export_to_csv \
  --spreadsheet_id "<SPREADSHEET_ID>" \
  --csv_path "./out/export.csv" \
  --config_path "./config/config.yaml"
```

If `worksheet_title` is omitted, the export uses the most recent timestamp-named tab.

CLI output will be a message like:

```text
Exported spreadsheet '2026-04-05 10:15:00' from spreadsheet ID 123abc... to CSV file './out/export.csv'
```

### Clear cached OAuth token

Remove the cached OAuth token from keyring:

```bash
gsheet-rw clear_oauth_token \
  --config_path "./config/config.yaml"
```

If you want a full reset that also removes the filesystem fallback token, use:

```bash
gsheet-rw clear_oauth_token \
  --config_path "./config/config.yaml" \
  --clear_filesystem_fallback true
```

Notes:
- The keyring entry is keyed by the resolved `oauth_token_path`.
- Clearing only keyring is usually enough for inspection and debugging.
- If `oauth_token_path` still exists on disk, the app will load it and migrate it back into keyring on the next run.

### Show authentication status

Show the resolved authentication configuration and token storage state:

```bash
gsheet-rw auth_status \
  --config_path "./config/config.yaml"
```

This is useful for confirming:

- which auth mode is active
- where `credentials.json` resolves to
- where the token fallback path resolves to
- whether a token currently exists in keyring
- whether a fallback token file exists on disk

## Security Notes

- OAuth tokens are stored in keyring first. If keyring is unavailable, the app can still fall back to `oauth_token_path` on disk for compatibility and debugging. In this project that tradeoff is intentional, but the fallback file may be less protected than the OS keyring depending on the local machine and filesystem permissions.
- The app logs useful operational details at `INFO` level, including spreadsheet IDs, worksheet names, folder names, and sharing target email addresses. That is acceptable for the intended trusted-user utility/tutorial use case, but those logs should be treated as sensitive metadata if used in a shared environment.

## Column protection behavior

- The tool protects columns **A..(N-2)** (all except the last 2 columns).
- Only `owner_email` (from config) is allowed to edit protected columns.
- Shared users can still edit the last 2 columns.
