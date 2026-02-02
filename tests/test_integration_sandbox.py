import os
from pathlib import Path

import pytest

from gsheet_rw import export_to_csv
from gsheet_rw.config import AppConfig


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    return value


@pytest.mark.integration
def test_export_from_sandbox_sheet(tmp_path: Path) -> None:
    if _env("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to enable integration tests.")

    config_path = _env("GSHEET_RW_CONFIG_PATH") or "config/config.yaml"
    if not Path(config_path).exists():
        pytest.skip(f"Missing config at {config_path}.")

    spreadsheet_id = _env("SANDBOX_SPREADSHEET_ID")
    if not spreadsheet_id:
        pytest.skip("Set SANDBOX_SPREADSHEET_ID to a sandbox sheet.")

    worksheet_title = _env("SANDBOX_WORKSHEET_TITLE")
    if not worksheet_title:
        pytest.skip("Set SANDBOX_WORKSHEET_TITLE to a known sheet tab.")

    cfg = AppConfig.load(config_path)
    out_path = tmp_path / "export.csv"
    export_to_csv(
        spreadsheet_id=spreadsheet_id,
        csv_path=str(out_path),
        config=cfg,
        worksheet_title=worksheet_title,
    )
    assert out_path.exists()
    assert out_path.stat().st_size > 0
