from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Optional

import pandas as pd

from .config import AppConfig
from .registry import get_registered_id, load_registry, save_registry, set_registered_id
from .sheets_client import (
    add_sheet_tab,
    auto_resize_columns,
    build_clients_from_config,
    create_spreadsheet,
    get_column_pixel_sizes,
    read_sheet_to_dataframe,
    move_sheet_tab_to_index,
    rename_sheet_tab,
    resolve_drive_folder_id_by_name,
    shade_columns_except_last_n,
    protect_columns_except_last_n,
    set_column_pixel_size,
    share_spreadsheet,
    spreadsheet_exists,
    write_dataframe,
)

EXPECTED_COLUMNS = [
    "Division",
    "Rank",
    "Age",
    "Last Name",
    "Ring #",
    "Competitor Count",
    "Judge Assigned",
    "Comments",
]


def create_from_csv(
    csv_path: str,
    sheet_title: Optional[str] = None,
    config_path: str = "config.yaml",
    worksheet_title: Optional[str] = None,
    drive_folder_name: Optional[str] = None,
    share_role: str = "writer",
    unprotected_last_n: int = 2,
) -> str:
    cfg = AppConfig.load(config_path)
    ws_title = worksheet_title or cfg.worksheet_title
    spreadsheet_title = sheet_title or cfg.spreadsheet_title
    folder_name = drive_folder_name or cfg.drive_folder_name

    if not folder_name:
        raise ValueError("Missing drive folder name. Provide drive_folder_name or set it in config.yaml.")

    if not spreadsheet_title:
        raise ValueError("Missing spreadsheet title. Provide sheet_title or set spreadsheet_title in config.yaml.")

    if not ws_title:
        raise ValueError("Missing worksheet title. Provide worksheet_title or set worksheet_title in config.yaml.")

    df = pd.read_csv(csv_path)
    _validate_columns(df)

    clients = build_clients_from_config(cfg)
    registry_path = Path(config_path).expanduser().resolve().parent / "sheet_registry.yaml"
    registry = load_registry(registry_path)

    registry_key = folder_name
    drive_folder_id = None
    if folder_name != "root":
        drive_folder_id = resolve_drive_folder_id_by_name(clients, folder_name)

    existing_id = get_registered_id(registry, registry_key, spreadsheet_title)
    if existing_id and not spreadsheet_exists(clients, existing_id):
        existing_id = None

    created_new = False
    if existing_id:
        spreadsheet_id = existing_id
        timestamp_title = _timestamp_tab_title()
        sheet_id = add_sheet_tab(clients, spreadsheet_id, timestamp_title)
        # Move newest tab to the far left; use index = -1 to append on the far right.
        move_sheet_tab_to_index(clients, spreadsheet_id, sheet_id, 0)
    else:
        timestamp_title = _timestamp_tab_title()
        spreadsheet_id, sheet_id = create_spreadsheet(
            clients=clients,
            title=spreadsheet_title,
            worksheet_title=ws_title,
            drive_folder_id=drive_folder_id,
        )
        rename_sheet_tab(clients, spreadsheet_id, sheet_id, timestamp_title)
        # Move newest tab to the far left; use index = -1 to append on the far right.
        move_sheet_tab_to_index(clients, spreadsheet_id, sheet_id, 0)
        set_registered_id(registry, registry_key, spreadsheet_title, spreadsheet_id)
        save_registry(registry_path, registry)
        created_new = True

    write_dataframe(clients, spreadsheet_id, timestamp_title, df)
    auto_resize_columns(
        clients=clients,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        total_columns=len(df.columns),
    )
    _widen_columns_by_header(
        clients=clients,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        headers=list(df.columns),
    )
    shade_columns_except_last_n(
        clients=clients,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        total_columns=len(df.columns),
        unprotected_last_n=unprotected_last_n,
        total_rows=len(df.index) + 1,
        time_row_indexes=_time_row_indexes(df),
    )
    protect_columns_except_last_n(
        clients=clients,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        total_columns=len(df.columns),
        unprotected_last_n=unprotected_last_n,
        allowed_editor_emails=[cfg.owner_email],
    )
    share_spreadsheet(clients, spreadsheet_id, cfg.share_emails, role=share_role)

    action = "Created" if created_new else "Updated"
    print(f"{action} spreadsheet: {spreadsheet_id}")
    return spreadsheet_id


def export_to_csv(
    spreadsheet_id: str,
    csv_path: Optional[str] = None,
    config_path: str = "config.yaml",
    worksheet_title: Optional[str] = None,
    out_csv_path: Optional[str] = None,
) -> str:
    if csv_path and out_csv_path:
        raise ValueError("Provide only one of csv_path or out_csv_path.")
    if not csv_path:
        csv_path = out_csv_path
    if not csv_path:
        raise ValueError("Missing csv_path. Provide csv_path (preferred) or out_csv_path.")

    cfg = AppConfig.load(config_path)

    clients = build_clients_from_config(cfg)
    ws_title = worksheet_title or _latest_timestamp_tab_title(clients, spreadsheet_id)
    df = read_sheet_to_dataframe(clients, spreadsheet_id, ws_title)

    if set(EXPECTED_COLUMNS).issubset(set(df.columns)):
        df = df[EXPECTED_COLUMNS]

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"Wrote: {csv_path}")
    return csv_path


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "CSV is missing expected columns: "
            + ", ".join(missing)
            + f"\nExpected columns: {EXPECTED_COLUMNS}"
            + f"\nFound columns: {list(df.columns)}"
        )


def _timestamp_tab_title() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _latest_timestamp_tab_title(clients, spreadsheet_id: str) -> str:
    titles = _list_sheet_titles(clients, spreadsheet_id)
    parsed = []
    for title in titles:
        try:
            parsed.append((datetime.strptime(title, "%Y-%m-%d %H:%M:%S"), title))
        except ValueError:
            continue
    if not parsed:
        raise ValueError("No timestamp-named sheets found. Provide worksheet_title explicitly.")
    parsed.sort()
    return parsed[-1][1]


def _list_sheet_titles(clients, spreadsheet_id: str) -> list[str]:
    meta = clients.sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(title))",
    ).execute()
    return [s.get("properties", {}).get("title", "") for s in meta.get("sheets", [])]


def _time_row_indexes(df: pd.DataFrame) -> list[int]:
    if df.empty or df.shape[1] == 0:
        return []
    first_col = df.iloc[:, 0].astype(str).fillna("")
    rows: list[int] = []
    for idx, value in enumerate(first_col.tolist()):
        if _looks_like_time(value):
            # +1 to account for header row in the sheet.
            rows.append(idx + 1)
    return rows


def _looks_like_time(value: str) -> bool:
    v = value.strip().lower()
    if not v:
        return False
    time_re = r"\d{1,2}:\d{2}"
    ampm_re = r"(a\.?m\.?|p\.?m\.?|am|pm)"
    noon_re = r"(noon)"
    patterns = [
        rf"^{time_re}\s*{ampm_re}$",
        rf"^{time_re}\s*{noon_re}$",
        rf"^{noon_re}$",
    ]
    return any(re.match(p, v) for p in patterns)


def _widen_columns_by_header(
    clients,
    spreadsheet_id: str,
    sheet_id: int,
    headers: list[str],
) -> None:
    targets = [
        ("Judge Assigned", 2),
        ("Comments", 4),
    ]
    sizes = get_column_pixel_sizes(clients, spreadsheet_id, sheet_id)
    for name, multiplier in targets:
        if name not in headers:
            continue
        idx = headers.index(name)
        base = sizes[idx] if idx < len(sizes) else 100
        set_column_pixel_size(clients, spreadsheet_id, sheet_id, idx, int(base * multiplier))
