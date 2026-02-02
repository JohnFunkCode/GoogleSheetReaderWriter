from __future__ import annotations

from typing import Optional

import fire

from .app import create_from_csv, export_to_csv


class SheetCLI:
    def create_from_csv(
        self,
        csv_path: str,
        sheet_title: Optional[str] = None,
        config_path: str = "config.yaml",
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
        config_path: str = "config.yaml",
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


def main():
    fire.Fire(SheetCLI)


if __name__ == "__main__":
    main()
