import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

PBKDF2_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 1024
PASSWORD_SPECIAL_PATTERN = re.compile(r"[^A-Za-z0-9]")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY_SALT = bytes(16)


class UserAlreadyExistsError(ValueError):
    """Raised when an account already exists for an email address."""


def _database_path() -> Path:
    configured_path = os.environ.get("BIFLOW_AUTH_DB")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "data" / "biflow_auth.sqlite3"


def _connect() -> sqlite3.Connection:
    database_path = _database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return connection


def validate_email(email: str) -> str:
    normalized_email = email.strip().lower()
    if len(normalized_email) > 254 or not EMAIL_PATTERN.fullmatch(normalized_email):
        raise ValueError("Enter a valid email address.")
    return normalized_email


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )


def validate_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Your password must contain at least {PASSWORD_MIN_LENGTH} characters."
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Your password must contain {PASSWORD_MAX_LENGTH} characters or fewer."
        )
    if not any(character.isupper() for character in password):
        raise ValueError("Your password must contain at least one uppercase letter.")
    if not PASSWORD_SPECIAL_PATTERN.search(password):
        raise ValueError("Your password must contain at least one special character.")
    return password


def register_user(full_name: str, email: str, password: str) -> dict:
    name = full_name.strip()
    normalized_email = validate_email(email)
    if not name:
        raise ValueError("Enter your name.")
    if len(name) > 200:
        raise ValueError("Your name must be 200 characters or fewer.")
    validate_password(password)

    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)
    try:
        with closing(_connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO users (full_name, email, password_hash, password_salt)
                VALUES (?, ?, ?, ?)
                """,
                (name, normalized_email, password_hash.hex(), salt.hex()),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise UserAlreadyExistsError(
            "An account with this email already exists."
        ) from error

    return {"id": user_id, "full_name": name, "email": normalized_email}


def authenticate_user(email: str, password: str) -> dict | None:
    try:
        normalized_email = validate_email(email)
    except ValueError:
        return None
    if len(password) > PASSWORD_MAX_LENGTH:
        return None

    with closing(_connect()) as connection:
        row = connection.execute(
            """
            SELECT id, full_name, email, password_hash, password_salt
            FROM users
            WHERE email = ?
            """,
            (normalized_email,),
        ).fetchone()

    if row is None:
        _hash_password(password, _DUMMY_SALT)
        return None

    stored_hash = bytes.fromhex(row["password_hash"])
    salt = bytes.fromhex(row["password_salt"])
    if not hmac.compare_digest(_hash_password(password, salt), stored_hash):
        return None

    return {"id": row["id"], "full_name": row["full_name"], "email": row["email"]}