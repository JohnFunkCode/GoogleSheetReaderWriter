from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class AppConfig:
    # Auth mode: "service_account" (default), "oauth", or "adc"
    auth_mode: str = "service_account"

    # Service account JSON key (required when auth_mode == "service_account")
    service_account_json: Optional[Path] = None

    # OAuth client secret JSON and token path (required when auth_mode == "oauth")
    oauth_client_secret_json: Optional[Path] = None
    oauth_token_path: Optional[Path] = None

    owner_email: str = ""
    share_emails: List[str] = None  # type: ignore[assignment]
    drive_folder_id: Optional[str] = None
    drive_folder_name: Optional[str] = None
    spreadsheet_title: Optional[str] = None
    worksheet_title: str = ""

    @staticmethod
    def load(path: str | Path) -> "AppConfig":
        p = Path(path).expanduser().resolve()
        data: Dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

        auth_mode = str(data.get("auth_mode", "service_account")).strip().lower()
        if auth_mode not in {"service_account", "oauth", "adc"}:
            raise ValueError("config/config.yaml: auth_mode must be 'service_account', 'oauth', or 'adc'")

        missing = [k for k in ("owner_email", "share_emails") if k not in data]
        if missing:
            raise ValueError(f"Missing required config keys: {', '.join(missing)}")

        owner_email = str(data["owner_email"]).strip()
        share_emails = [str(x).strip() for x in (data["share_emails"] or []) if str(x).strip()]

        service_account_json = None
        oauth_client_secret_json = None
        oauth_token_path = None

        if auth_mode == "service_account":
            sa = str(data.get("service_account_json", "")).strip()
            if not sa:
                raise ValueError("Missing required config key for service_account mode: service_account_json")
            service_account_json = Path(sa).expanduser().resolve()

        if auth_mode == "oauth":
            cs = str(data.get("oauth_client_secret_json", "")).strip()
            tp = str(data.get("oauth_token_path", "")).strip()
            oauth_client_secret_json = _default_oauth_client_secret_path(p) if not cs else Path(cs).expanduser().resolve()
            oauth_token_path = _default_oauth_token_path() if not tp else Path(tp).expanduser().resolve()

        drive_folder_id = str(data.get("drive_folder_id") or "").strip() or None
        drive_folder_name = str(data.get("drive_folder_name") or "").strip() or None
        spreadsheet_title = str(data.get("spreadsheet_title") or "").strip() or None
        worksheet_title = str(data.get("worksheet_title") or "").strip()

        return AppConfig(
            auth_mode=auth_mode,
            service_account_json=service_account_json,
            oauth_client_secret_json=oauth_client_secret_json,
            oauth_token_path=oauth_token_path,
            owner_email=owner_email,
            share_emails=share_emails,
            drive_folder_id=drive_folder_id,
            drive_folder_name=drive_folder_name,
            spreadsheet_title=spreadsheet_title,
            worksheet_title=worksheet_title,
        )


def _default_oauth_client_secret_path(config_path: Path) -> Path:
    base = config_path.parent
    for name in ("credentials.json", "client_secret.json"):
        candidate = (base / name).expanduser()
        if candidate.exists():
            return candidate.resolve()
    return (base / "credentials.json").resolve()


def _default_oauth_token_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return (base / "gsheet-rw" / "token.json").expanduser().resolve()
