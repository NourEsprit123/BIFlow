import sqlite3

import pytest

import auth.service as auth_service
from auth import (
    EmailConfigurationError,
    UserAlreadyExistsError,
    authenticate_user,
    register_user,
    request_password_reset,
    reset_password,
    validate_email,
    validate_password,
)

VALID_PASSWORD = "A-long-password!"


def test_register_and_authenticate_user(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))

    registered = register_user("Ada Lovelace", "ADA@example.com", VALID_PASSWORD)

    assert registered["email"] == "ada@example.com"
    assert authenticate_user("ada@example.com", VALID_PASSWORD) == registered
    assert authenticate_user("ada@example.com", "incorrect-password") is None
    assert authenticate_user("unknown@example.com", VALID_PASSWORD) is None

    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        stored_hash, stored_salt = connection.execute(
            "SELECT password_hash, password_salt FROM users"
        ).fetchone()

    assert stored_hash != VALID_PASSWORD
    assert stored_salt


def test_registration_rejects_duplicate_email_case_insensitively(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    register_user("Ada Lovelace", "ada@example.com", VALID_PASSWORD)

    with pytest.raises(UserAlreadyExistsError):
        register_user("Another Ada", "ADA@example.com", "Another-password!")


def test_validate_email_normalizes_valid_addresses():
    assert validate_email("  ADA@example.com ") == "ada@example.com"


@pytest.mark.parametrize(
    ("name", "email", "password"),
    [
        ("", "ada@example.com", "a-long-password"),
        ("Ada", "invalid-email", "a-long-password"),
        ("Ada", "ada@example.com", "short"),
    ],
)
def test_registration_validates_account_fields(
    tmp_path, monkeypatch, name, email, password
):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))

    with pytest.raises(ValueError):
        register_user(name, email, password)


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Ab1!", "at least 8 characters"),
        ("no-uppercase-password!", "uppercase letter"),
        ("NoSpecialCharacter123", "special character"),
        ("A" * 1025 + "!", "1024 characters or fewer"),
    ],
)
def test_password_policy(password, message):
    with pytest.raises(ValueError, match=message):
        validate_password(password)


def test_request_and_complete_password_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("BIFLOW_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BIFLOW_SMTP_FROM", "no-reply@example.test")
    monkeypatch.setenv("BIFLOW_SMTP_PORT", "587")
    sent = {}
    monkeypatch.setattr(
        auth_service,
        "_send_password_reset_email",
        lambda recipient, code, settings: sent.update(
            recipient=recipient, code=code, settings=settings
        ),
    )
    user = register_user("Ada Lovelace", "ada@example.com", VALID_PASSWORD)

    request_password_reset("ADA@example.com")

    assert sent["recipient"] == "ada@example.com"
    assert sent["code"]
    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        stored_token_hash = connection.execute(
            "SELECT token_hash FROM password_reset_tokens"
        ).fetchone()[0]
    assert stored_token_hash != sent["code"]

    new_password = "A-new-password!"
    assert reset_password("ada@example.com", sent["code"], new_password)
    assert authenticate_user("ada@example.com", new_password) == user
    assert authenticate_user("ada@example.com", VALID_PASSWORD) is None
    assert not reset_password("ada@example.com", sent["code"], VALID_PASSWORD)


def test_reset_code_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("BIFLOW_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BIFLOW_SMTP_FROM", "no-reply@example.test")
    monkeypatch.setattr(auth_service.time, "time", lambda: 1_000)
    sent = {}
    monkeypatch.setattr(
        auth_service,
        "_send_password_reset_email",
        lambda recipient, code, settings: sent.update(code=code),
    )
    register_user("Ada Lovelace", "ada@example.com", VALID_PASSWORD)

    request_password_reset("ada@example.com")
    monkeypatch.setattr(
        auth_service.time,
        "time",
        lambda: 1_000 + auth_service.PASSWORD_RESET_TTL_SECONDS,
    )

    assert not reset_password("ada@example.com", sent["code"], "A-new-password!")


def test_password_reset_does_not_send_email_for_unknown_account(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("BIFLOW_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BIFLOW_SMTP_FROM", "no-reply@example.test")
    sent = []
    monkeypatch.setattr(
        auth_service,
        "_send_password_reset_email",
        lambda *args: sent.append(args),
    )

    assert not request_password_reset("unknown@example.com")
    assert sent == []


def test_password_reset_limits_invalid_code_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("BIFLOW_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BIFLOW_SMTP_FROM", "no-reply@example.test")
    sent = {}
    monkeypatch.setattr(
        auth_service,
        "_send_password_reset_email",
        lambda recipient, code, settings: sent.update(code=code),
    )
    register_user("Ada Lovelace", "ada@example.com", VALID_PASSWORD)
    request_password_reset("ada@example.com")
    wrong_code = "000000" if sent["code"] != "000000" else "000001"

    for _ in range(auth_service.PASSWORD_RESET_MAX_ATTEMPTS):
        assert not reset_password("ada@example.com", wrong_code, VALID_PASSWORD)

    assert not reset_password("ada@example.com", sent["code"], "A-new-password!")


def test_password_reset_requires_smtp_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.delenv("BIFLOW_SMTP_HOST", raising=False)
    monkeypatch.delenv("BIFLOW_SMTP_FROM", raising=False)

    with pytest.raises(EmailConfigurationError):
        request_password_reset("ada@example.com")
