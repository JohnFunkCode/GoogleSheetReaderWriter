from pathlib import Path

from gsheet_rw.config import AppConfig
from gsheet_rw import sheets_client


class _FakeCreds:
    def __init__(self, source: str) -> None:
        self.source = source

    def to_json(self) -> str:
        return f'{{"source":"{self.source}"}}'


def test_load_oauth_credentials_prefers_keyring(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"source":"filesystem"}', encoding="utf-8")

    monkeypatch.setattr(
        sheets_client.keyring,
        "get_password",
        lambda service, username: '{"source":"keyring"}',
    )
    monkeypatch.setattr(
        sheets_client.UserCredentials,
        "from_authorized_user_info",
        lambda token_info, scopes: _FakeCreds(token_info["source"]),
    )
    monkeypatch.setattr(
        sheets_client.UserCredentials,
        "from_authorized_user_file",
        lambda path, scopes: _FakeCreds("filesystem"),
    )

    creds = sheets_client._load_oauth_credentials(token_path)

    assert creds is not None
    assert creds.source == "keyring"


def test_load_oauth_credentials_falls_back_to_filesystem(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"source":"filesystem"}', encoding="utf-8")
    stored = {}

    monkeypatch.setattr(
        sheets_client.keyring,
        "get_password",
        lambda service, username: None,
    )
    monkeypatch.setattr(
        sheets_client.keyring,
        "set_password",
        lambda service, username, password: stored.update(
            {"service": service, "username": username, "password": password}
        ),
    )
    monkeypatch.setattr(
        sheets_client.UserCredentials,
        "from_authorized_user_file",
        lambda path, scopes: _FakeCreds("filesystem"),
    )

    creds = sheets_client._load_oauth_credentials(token_path)

    assert creds is not None
    assert creds.source == "filesystem"
    assert stored == {
        "service": sheets_client.KEYRING_SERVICE_NAME,
        "username": str(token_path),
        "password": '{"source":"filesystem"}',
    }


def test_clear_cached_oauth_token_clears_keyring_and_optional_filesystem(
    monkeypatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"source":"filesystem"}', encoding="utf-8")
    deleted = {}

    monkeypatch.setattr(
        sheets_client.keyring,
        "delete_password",
        lambda service, username: deleted.update(
            {"service": service, "username": username}
        ),
    )

    cfg = AppConfig(
        auth_mode="oauth",
        oauth_token_path=token_path,
    )
    result = sheets_client.clear_cached_oauth_token(
        cfg,
        clear_filesystem_fallback=True,
    )

    assert result == {
        "keyring_deleted": True,
        "filesystem_deleted": True,
    }
    assert deleted == {
        "service": sheets_client.KEYRING_SERVICE_NAME,
        "username": str(token_path),
    }
    assert not token_path.exists()


def test_load_oauth_credentials_ignores_invalid_filesystem_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("not-json", encoding="utf-8")

    monkeypatch.setattr(
        sheets_client.keyring,
        "get_password",
        lambda service, username: None,
    )
    monkeypatch.setattr(
        sheets_client.UserCredentials,
        "from_authorized_user_file",
        lambda path, scopes: (_ for _ in ()).throw(ValueError("bad token file")),
    )

    creds = sheets_client._load_oauth_credentials(token_path)

    assert creds is None


def test_load_oauth_client_id_reads_installed_client(tmp_path: Path) -> None:
    client_secret_path = tmp_path / "credentials.json"
    client_secret_path.write_text(
        '{"installed":{"client_id":"client-123","client_secret":"secret"}}',
        encoding="utf-8",
    )

    client_id = sheets_client._load_oauth_client_id(client_secret_path)

    assert client_id == "client-123"


def test_get_auth_status_reports_oauth_paths_and_keyring(monkeypatch, tmp_path: Path) -> None:
    client_secret_path = tmp_path / "credentials.json"
    client_secret_path.write_text('{"installed":{"client_id":"client-123"}}', encoding="utf-8")
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        sheets_client.keyring,
        "get_password",
        lambda service, username: '{"token":"present"}',
    )

    cfg = AppConfig(
        auth_mode="oauth",
        oauth_client_secret_json=client_secret_path,
        oauth_token_path=token_path,
    )

    status = sheets_client.get_auth_status(cfg)

    assert status == {
        "auth_mode": "oauth",
        "keyring_has_token": True,
        "keyring_service": sheets_client.KEYRING_SERVICE_NAME,
        "oauth_client_secret_exists": True,
        "oauth_client_secret_path": str(client_secret_path),
        "oauth_token_file_exists": True,
        "oauth_token_path": str(token_path),
    }
