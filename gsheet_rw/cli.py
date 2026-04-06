from __future__ import annotations

import json
import logging
from typing import Optional

import fire

from .app import create_from_csv, export_to_csv
from .config import AppConfig
from .sheets_client import clear_cached_oauth_token, get_auth_status


class SheetCLI:
    def create_from_csv(
        self,
        csv_path: str,
        sheet_title: Optional[str] = None,
        config_path: str = "config/config.yaml",
        worksheet_title: Optional[str] = None,
        drive_folder_name: Optional[str] = None,
        share_role: str = "writer",
        unprotected_last_n: int = 2,
    ) -> str:
        return create_from_csv(
            csv_path=csv_path,
            sheet_title=sheet_title,
            config_path=config_path,
            worksheet_title=worksheet_title,
            drive_folder_name=drive_folder_name,
            share_role=share_role,
            unprotected_last_n=unprotected_last_n,
        )

    def export_to_csv(
        self,
        spreadsheet_id: str,
        csv_path: Optional[str] = None,
        config_path: str = "config/config.yaml",
        worksheet_title: Optional[str] = None,
        out_csv_path: Optional[str] = None,
    ) -> str:
        return export_to_csv(
            spreadsheet_id=spreadsheet_id,
            csv_path=csv_path,
            config_path=config_path,
            worksheet_title=worksheet_title,
            out_csv_path=out_csv_path,
        )

    def clear_oauth_token(
        self,
        config_path: str = "config/config.yaml",
        clear_filesystem_fallback: bool = False,
    ) -> str:
        cfg = AppConfig.load(config_path)
        result = clear_cached_oauth_token(
            cfg,
            clear_filesystem_fallback=clear_filesystem_fallback,
        )
        return (
            "Cleared OAuth token cache: "
            f"keyring_deleted={result['keyring_deleted']} "
            f"filesystem_deleted={result['filesystem_deleted']}"
        )

    def auth_status(self, config_path: str = "config/config.yaml") -> str:
        cfg = AppConfig.load(config_path)
        status = get_auth_status(cfg)
        return json.dumps(status, indent=2, sort_keys=True)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    fire.Fire(SheetCLI)


if __name__ == "__main__":
    main()
