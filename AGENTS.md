# AGENTS

## Quick start
- CLI entrypoint: `python -m gsheet_rw.cli`
- Config path default: `config/config.yaml`

## Local setup
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Tests
- Integration test (env-gated):
```
RUN_INTEGRATION_TESTS=1 \
SANDBOX_SPREADSHEET_ID="..." \
SANDBOX_WORKSHEET_TITLE="..." \
pytest -k integration
```
- Optional override: `GSHEET_RW_CONFIG_PATH` (defaults to `config/config.yaml`)

## Conventions
- Core app logic lives in `gsheet_rw/app.py` (UI-agnostic).
- CLI wrapper stays thin in `gsheet_rw/cli.py`.
- Registry file: `data/sheet_registry.yaml`.
- Secrets live in `./secrets/` and are gitignored.
- Logging uses `logging` (configured in CLI for local runs).
