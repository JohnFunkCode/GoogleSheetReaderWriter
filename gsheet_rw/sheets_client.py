from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import google.auth
import keyring
import pandas as pd
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from keyring.errors import KeyringError, PasswordDeleteError

from .config import AppConfig

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
KEYRING_SERVICE_NAME = "gsheet-rw"


@dataclass
class GoogleClients:
    sheets: Any
    drive: Any


class GoogleClientsProtocol(Protocol):
    sheets: Any
    drive: Any


def _oauth_token_key(token_path: Path) -> str:
    return str(token_path)


def _escape_drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _oauth_principal(creds: Optional[UserCredentials]) -> str:
    account = getattr(creds, "account", "") if creds else ""
    return account or "(unknown_oauth_user)"


def _load_oauth_client_id(client_secret_path: Path) -> Optional[str]:
    try:
        payload = json.loads(client_secret_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    for section_name in ("installed", "web"):
        section = payload.get(section_name)
        if isinstance(section, dict):
            client_id = str(section.get("client_id") or "").strip()
            if client_id:
                return client_id
    return None


def clear_cached_oauth_token(
    cfg: AppConfig,
    *,
    clear_filesystem_fallback: bool = False,
) -> Dict[str, bool]:
    if (cfg.auth_mode or "service_account").strip().lower() != "oauth":
        raise ValueError("clear_cached_oauth_token requires auth_mode='oauth'")
    if not cfg.oauth_token_path:
        raise ValueError("oauth_token_path is required for oauth mode")

    logger = logging.getLogger(__name__)
    token_path = Path(cfg.oauth_token_path).expanduser().resolve()
    deleted_keyring = False
    deleted_filesystem = False

    try:
        keyring.delete_password(KEYRING_SERVICE_NAME, _oauth_token_key(token_path))
        deleted_keyring = True
        logger.info("oauth_token_deleted=keyring path=%s", token_path)
    except PasswordDeleteError:
        logger.info("oauth_token_deleted=keyring path=%s skipped=not_found", token_path)
    except KeyringError as exc:
        logger.warning("oauth_token_keyring_delete_failed=true path=%s error=%s", token_path, exc)

    if clear_filesystem_fallback and token_path.exists():
        token_path.unlink()
        deleted_filesystem = True
        logger.info("oauth_token_deleted=filesystem path=%s", token_path)

    return {
        "keyring_deleted": deleted_keyring,
        "filesystem_deleted": deleted_filesystem,
    }


def get_auth_status(cfg: AppConfig) -> Dict[str, Any]:
    mode = (cfg.auth_mode or "service_account").strip().lower()
    status: Dict[str, Any] = {
        "auth_mode": mode,
    }

    if mode == "oauth":
        client_secret_path = Path(cfg.oauth_client_secret_json).expanduser().resolve() if cfg.oauth_client_secret_json else None
        token_path = Path(cfg.oauth_token_path).expanduser().resolve() if cfg.oauth_token_path else None
        keyring_has_token = False
        keyring_error = None

        if token_path is not None:
            try:
                keyring_has_token = keyring.get_password(
                    KEYRING_SERVICE_NAME,
                    _oauth_token_key(token_path),
                ) is not None
            except KeyringError as exc:
                keyring_error = str(exc)

        status.update(
            {
                "oauth_client_secret_path": str(client_secret_path) if client_secret_path else None,
                "oauth_client_secret_exists": client_secret_path.exists() if client_secret_path else False,
                "oauth_token_path": str(token_path) if token_path else None,
                "oauth_token_file_exists": token_path.exists() if token_path else False,
                "keyring_service": KEYRING_SERVICE_NAME,
                "keyring_has_token": keyring_has_token,
            }
        )
        if keyring_error:
            status["keyring_error"] = keyring_error
        return status

    if mode == "service_account":
        service_account_path = Path(cfg.service_account_json).expanduser().resolve() if cfg.service_account_json else None
        status.update(
            {
                "service_account_json_path": str(service_account_path) if service_account_path else None,
                "service_account_json_exists": service_account_path.exists() if service_account_path else False,
            }
        )
        return status

    status["adc_uses_application_default_credentials"] = True
    return status


def _store_oauth_credentials(
    creds: UserCredentials,
    token_path: Path,
    *,
    write_filesystem: bool = False,
) -> None:
    logger = logging.getLogger(__name__)
    token_json = creds.to_json()

    try:
        keyring.set_password(KEYRING_SERVICE_NAME, _oauth_token_key(token_path), token_json)
        logger.info("oauth_token_persisted=keyring path=%s", token_path)
    except KeyringError as exc:
        logger.warning("oauth_token_keyring_write_failed=true path=%s error=%s", token_path, exc)
        write_filesystem = True

    if write_filesystem:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token_json, encoding="utf-8")
        logger.info("oauth_token_persisted=filesystem path=%s", token_path)


def _load_oauth_credentials(token_path: Path) -> Optional[UserCredentials]:
    logger = logging.getLogger(__name__)

    try:
        token_json = keyring.get_password(KEYRING_SERVICE_NAME, _oauth_token_key(token_path))
    except KeyringError as exc:
        logger.warning("oauth_token_keyring_read_failed=true path=%s error=%s", token_path, exc)
        token_json = None

    if token_json:
        try:
            token_info = json.loads(token_json)
            logger.info("oauth_token_source=keyring path=%s", token_path)
            return UserCredentials.from_authorized_user_info(token_info, SCOPES)
        except (TypeError, ValueError) as exc:
            logger.warning("oauth_token_keyring_invalid=true path=%s error=%s", token_path, exc)

    if token_path.exists():
        try:
            logger.info("oauth_token_source=filesystem path=%s", token_path)
            creds = UserCredentials.from_authorized_user_file(str(token_path), SCOPES)
            _store_oauth_credentials(creds, token_path, write_filesystem=False)
            return creds
        except ValueError as exc:
            logger.warning(
                "oauth_token_filesystem_invalid=true path=%s error=%s action=browser_reauth",
                token_path,
                exc,
            )

    return None


def build_clients(service_account_json_path: str) -> GoogleClients:
    """Service-account only (legacy entrypoint)."""
    creds = ServiceAccountCredentials.from_service_account_file(service_account_json_path, scopes=SCOPES)
    logging.getLogger(__name__).info(
        "auth_mode=service_account principal=%s", creds.service_account_email
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return GoogleClients(sheets=sheets, drive=drive)


def build_clients_from_config(cfg: AppConfig) -> GoogleClients:
    """Build Sheets/Drive clients using service account, OAuth, or ADC."""
    mode = (cfg.auth_mode or "service_account").strip().lower()

    if mode == "service_account":
        if not cfg.service_account_json:
            raise ValueError("service_account_json is required for service_account mode")
        return build_clients(str(cfg.service_account_json))

    if mode == "adc":
        creds, project_id = google.auth.default(scopes=SCOPES)
        logging.getLogger(__name__).info(
            "auth_mode=adc project=%s", project_id or "(unknown)"
        )
        sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        return GoogleClients(sheets=sheets, drive=drive)

    if mode != "oauth":
        raise ValueError("auth_mode must be 'service_account', 'oauth', or 'adc'")

    if not cfg.oauth_client_secret_json or not cfg.oauth_token_path:
        raise ValueError("oauth_client_secret_json and oauth_token_path are required for oauth mode")

    if not cfg.oauth_client_secret_json.exists():
        raise FileNotFoundError(
            f"OAuth client secret JSON not found at {cfg.oauth_client_secret_json}. "
            "Set oauth_client_secret_json in config/config.yaml. "
            "Relative paths in config are resolved from the config file directory."
        )

    token_path = Path(cfg.oauth_token_path).expanduser().resolve()
    creds = _load_oauth_credentials(token_path)
    expected_client_id = _load_oauth_client_id(cfg.oauth_client_secret_json)

    if creds and expected_client_id:
        cached_client_id = str(getattr(creds, "client_id", "") or "").strip()
        if cached_client_id and cached_client_id != expected_client_id:
            logging.getLogger(__name__).warning(
                "oauth_token_client_mismatch=true path=%s action=browser_reauth "
                "message=\"cached token was created for a different OAuth client\"",
                token_path,
            )
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _store_oauth_credentials(creds, token_path)
        except RefreshError as exc:
            logging.getLogger(__name__).warning(
                "oauth_token_refresh_failed=true path=%s error=%s action=browser_reauth "
                "message=\"cached token could not be refreshed; sign in again\"",
                token_path,
                exc,
            )
            creds = None

    if not creds or not creds.valid:
        logger = logging.getLogger(__name__)
        if creds:
            logger.info(
                "oauth_reauth_required=true path=%s message=\"browser window will open for Google sign-in\"",
                token_path,
            )
        else:
            logger.info(
                "oauth_signin_required=true path=%s message=\"browser window will open for Google sign-in\"",
                token_path,
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.oauth_client_secret_json), SCOPES)
        creds = flow.run_local_server(port=0)
        _store_oauth_credentials(creds, token_path)

    logging.getLogger(__name__).info(
        "auth_mode=oauth principal=%s token_path=%s",
        _oauth_principal(creds),
        token_path,
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return GoogleClients(sheets=sheets, drive=drive)


def create_spreadsheet(
    clients: GoogleClients,
    title: str,
    worksheet_title: str = "Sheet1",
    drive_folder_id: Optional[str] = None,
) -> Tuple[str, int]:
    """Create a spreadsheet and return (spreadsheet_id, sheet_id)."""
    if drive_folder_id:
        try:
            created = clients.drive.files().create(
                body={
                    "name": title,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "parents": [drive_folder_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
        except HttpError as e:
            logging.getLogger(__name__).error(
                "event=drive_create_error status=%s reason=%s content=%s",
                e.resp.status,
                getattr(e.resp, "reason", None),
                e.content.decode("utf-8", errors="replace"),
            )
            raise

        spreadsheet_id = created["id"]

        meta = clients.sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        ).execute()
        first = meta["sheets"][0]["properties"]
        sheet_id = int(first["sheetId"])
        default_title = first.get("title", "")

        if worksheet_title and default_title != worksheet_title:
            clients.sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": sheet_id, "title": worksheet_title},
                                "fields": "title",
                            }
                        }
                    ]
                },
            ).execute()

        return spreadsheet_id, sheet_id

    spreadsheet_body: Dict[str, Any] = {
        "properties": {"title": title},
        "sheets": [{"properties": {"title": worksheet_title}}],
    }

    try:
        spreadsheet = clients.sheets.spreadsheets().create(
            body=spreadsheet_body,
            fields="spreadsheetId,sheets(properties(sheetId))",
        ).execute()
    except HttpError as e:
        logging.getLogger(__name__).error(
            "event=sheets_create_error status=%s reason=%s content=%s",
            e.resp.status,
            getattr(e.resp, "reason", None),
            e.content.decode("utf-8", errors="replace"),
        )
        raise

    spreadsheet_id = spreadsheet["spreadsheetId"]
    sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
    return spreadsheet_id, sheet_id


def add_sheet_tab(
    clients: GoogleClients,
    spreadsheet_id: str,
    title: str,
) -> int:
    resp = clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    replies = resp.get("replies", [])
    if not replies:
        raise RuntimeError("Failed to add new sheet tab.")
    return int(replies[0]["addSheet"]["properties"]["sheetId"])


def rename_sheet_tab(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
    new_title: str,
) -> None:
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "title": new_title},
                        "fields": "title",
                    }
                }
            ]
        },
    ).execute()


def move_sheet_tab_to_index(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
    index: int,
) -> None:
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "index": index},
                        "fields": "index",
                    }
                }
            ]
        },
    ).execute()


def spreadsheet_exists(clients: GoogleClients, spreadsheet_id: str) -> bool:
    try:
        clients.drive.files().get(
            fileId=spreadsheet_id,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        return True
    except HttpError as e:
        if getattr(e.resp, "status", None) == 404:
            return False
        raise


def resolve_drive_folder_id_by_name(clients: GoogleClients, folder_name: str) -> str:
    escaped_folder_name = _escape_drive_query_literal(folder_name)
    try:
        resp = clients.drive.files().list(
            q=(
                "mimeType='application/vnd.google-apps.folder' "
                f"and name='{escaped_folder_name}' and trashed=false"
            ),
            fields="files(id,name)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
    except HttpError as e:
        if getattr(e.resp, "status", None) == 403:
            raise PermissionError(
                f"Access denied while searching for Drive folder '{folder_name}'."
            ) from e
        raise
    folders = resp.get("files", [])
    if not folders:
        raise ValueError(f"Drive folder not found: '{folder_name}'")
    if len(folders) > 1:
        ids = ", ".join(f["id"] for f in folders)
        raise ValueError(f"Multiple Drive folders named '{folder_name}' found. IDs: {ids}")
    return str(folders[0]["id"])


def write_dataframe(
    clients: GoogleClients,
    spreadsheet_id: str,
    worksheet_title: str,
    df: pd.DataFrame,
) -> None:
    values: List[List[Any]] = [list(df.columns)] + df.astype(object).where(pd.notnull(df), "").values.tolist()
    body = {"values": values}
    range_name = f"{worksheet_title}!A1"
    clients.sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body=body,
    ).execute()

    sheet_id = _get_sheet_id(clients, spreadsheet_id, worksheet_title)

    requests = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id}}}},
    ]
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def auto_resize_columns(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
    total_columns: int,
) -> None:
    if total_columns <= 0:
        return
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": total_columns,
                        }
                    }
                }
            ]
        },
    ).execute()


def get_column_pixel_sizes(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
) -> List[int]:
    meta = clients.sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=True,
        fields="sheets(properties(sheetId),data.columnMetadata(pixelSize))",
    ).execute()
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if int(props.get("sheetId", -1)) != sheet_id:
            continue
        data = sheet.get("data", [])
        if not data:
            return []
        col_meta = data[0].get("columnMetadata", [])
        return [int(cm.get("pixelSize", 100)) for cm in col_meta]
    return []


def set_column_pixel_size(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
    column_index: int,
    pixel_size: int,
) -> None:
    if column_index < 0:
        return
    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": column_index,
                            "endIndex": column_index + 1,
                        },
                        "properties": {"pixelSize": pixel_size},
                        "fields": "pixelSize",
                    }
                }
            ]
        },
    ).execute()


def protect_columns_except_last_n(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
    total_columns: int,
    unprotected_last_n: int,
    allowed_editor_emails: Sequence[str],
) -> None:
    protected_end = max(0, total_columns - unprotected_last_n)
    if protected_end <= 0:
        return

    req = {
        "addProtectedRange": {
            "protectedRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endColumnIndex": protected_end,
                },
                "description": "Protected: all columns except the last editable columns.",
                "warningOnly": False,
                "editors": {"users": list(allowed_editor_emails)},
            }
        }
    }

    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [req]},
    ).execute()


def shade_columns_except_last_n(
    clients: GoogleClients,
    spreadsheet_id: str,
    sheet_id: int,
    total_columns: int,
    unprotected_last_n: int,
    total_rows: int,
    time_row_indexes: Optional[Iterable[int]] = None,
    *,
    protected_rgb: Optional[Tuple[float, float, float]] = None,
    unprotected_rgb: Optional[Tuple[float, float, float]] = None,
) -> None:
    protected_end = max(0, total_columns - unprotected_last_n)
    if total_columns <= 0 or total_rows <= 0:
        return

    protected_light = _hex_to_rgb("#d9d9d9")
    protected_dark = _hex_to_rgb("#b7b7b7")
    unprotected_light = _hex_to_rgb("#cfe2f3")
    unprotected_dark = _hex_to_rgb("#9fc5e8")
    protected_color = protected_rgb or protected_light
    unprotected_color = unprotected_rgb or unprotected_light

    time_rows = set(time_row_indexes or [])
    requests = []
    for row in range(total_rows):
        if row in time_rows:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row,
                            "endRowIndex": row + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": total_columns,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                                "textFormat": {"fontSize": 18},
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.fontSize)",
                    }
                }
            )
            continue

        is_even = row % 2 == 0
        protected_row = protected_color if is_even else protected_dark
        unprotected_row = unprotected_color if is_even else unprotected_dark

        if protected_end > 0:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row,
                            "endRowIndex": row + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": protected_end,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": protected_row[0],
                                    "green": protected_row[1],
                                    "blue": protected_row[2],
                                }
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )

        if protected_end < total_columns:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row,
                            "endRowIndex": row + 1,
                            "startColumnIndex": protected_end,
                            "endColumnIndex": total_columns,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": unprotected_row[0],
                                    "green": unprotected_row[1],
                                    "blue": unprotected_row[2],
                                }
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )

    border = {
        "style": "SOLID_THICK",
        "width": 2,
        "color": {"red": 0.6, "green": 0.6, "blue": 0.6},
    }
    requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": total_rows,
                    "startColumnIndex": 0,
                    "endColumnIndex": total_columns,
                },
                "innerHorizontal": border,
                "innerVertical": {"style": "NONE"},
                "top": {"style": "NONE"},
                "bottom": border,
                "left": {"style": "NONE"},
                "right": {"style": "NONE"},
            }
        }
    )

    clients.sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def _hex_to_rgb(value: str) -> Tuple[float, float, float]:
    cleaned = value.lstrip("#")
    if len(cleaned) != 6:
        raise ValueError(f"Invalid hex color: {value}")
    r = int(cleaned[0:2], 16) / 255.0
    g = int(cleaned[2:4], 16) / 255.0
    b = int(cleaned[4:6], 16) / 255.0
    return (r, g, b)


def share_spreadsheet(
    clients: GoogleClients,
    spreadsheet_id: str,
    emails: Sequence[str],
    role: str = "writer",
) -> None:
    logger = logging.getLogger(__name__)
    for email in emails:
        perm_body = {"type": "user", "role": role, "emailAddress": email}
        clients.drive.permissions().create(
            fileId=spreadsheet_id,
            body=perm_body,
            sendNotificationEmail=True,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        logger.info(
            "event=share_permission spreadsheet_id=%s role=%s email=%s",
            spreadsheet_id,
            role,
            email,
        )


def read_sheet_to_dataframe(
    clients: GoogleClients,
    spreadsheet_id: str,
    worksheet_title: str,
) -> pd.DataFrame:
    try:
        resp = clients.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{worksheet_title}",
        ).execute()
    except HttpError as e:
        if getattr(e.resp, "status", None) == 404:
            raise FileNotFoundError(
                f"Spreadsheet '{spreadsheet_id}' or worksheet '{worksheet_title}' was not found, "
                "or the OAuth account used by this app does not have access to it."
            ) from e
        raise
    values = resp.get("values", [])
    if not values:
        return pd.DataFrame()

    headers = values[0]
    rows = values[1:]
    max_len = max(len(headers), *(len(r) for r in rows)) if rows else len(headers)
    headers = headers + [""] * (max_len - len(headers))
    normalized_rows = [r + [""] * (max_len - len(r)) for r in rows]
    return pd.DataFrame(normalized_rows, columns=headers)


def _get_sheet_id(clients: GoogleClients, spreadsheet_id: str, worksheet_title: str) -> int:
    try:
        meta = clients.sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        ).execute()
    except HttpError as e:
        if getattr(e.resp, "status", None) == 404:
            raise FileNotFoundError(
                f"Spreadsheet '{spreadsheet_id}' was not found, or the OAuth account used by this app "
                "does not have access to it."
            ) from e
        raise
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == worksheet_title:
            return int(props["sheetId"])
    raise ValueError(f"Worksheet '{worksheet_title}' not found in spreadsheet {spreadsheet_id}")
