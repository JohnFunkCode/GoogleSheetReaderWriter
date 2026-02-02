from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import yaml

RegistryData = Dict[str, Dict[str, str]]


def load_registry(path: Path) -> RegistryData:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    normalized: RegistryData = {}
    for folder_name, names in data.items():
        if not isinstance(names, dict):
            continue
        normalized[str(folder_name)] = {str(k): str(v) for k, v in names.items()}
    return normalized


def save_registry(path: Path, registry: RegistryData) -> None:
    path.write_text(yaml.safe_dump(registry, sort_keys=True), encoding="utf-8")


def get_registered_id(registry: RegistryData, folder_name: str, sheet_name: str) -> Optional[str]:
    return registry.get(folder_name, {}).get(sheet_name)


def set_registered_id(registry: RegistryData, folder_name: str, sheet_name: str, spreadsheet_id: str) -> None:
    registry.setdefault(folder_name, {})[sheet_name] = spreadsheet_id
