import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
import sqlite3
import time
from contextlib import closing
from email.message import EmailMessage
from pathlib import Path

PBKDF2_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 1024
PASSWORD_RESET_TTL_SECONDS = 30 * 60
PASSWORD_RESET_MAX_ATTEMPTS = 5
PASSWORD_SPECIAL_PATTERN = re.compile(r"[^A-Za-z0-9]")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY_SALT = bytes(16)


class UserAlreadyExistsError(ValueError):
    """Raised when an account already exists for an email address."""


class EmailConfigurationError(RuntimeError):
    """Raised when the settings required to send email are incomplete."""


class EmailDeliveryError(RuntimeError):
    """Raised when an email provider rejects or cannot deliver a message."""


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            token_hash TEXT NOT NULL,
            token_salt TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
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


def _smtp_settings() -> dict[str, str | int | bool]:
    host = os.environ.get("BIFLOW_SMTP_HOST", "").strip()
    sender = os.environ.get("BIFLOW_SMTP_FROM", "").strip()
    if not host or not sender:
        raise EmailConfigurationError(
            "Configure BIFLOW_SMTP_HOST and BIFLOW_SMTP_FROM to send password reset email."
        )

    try:
        port = int(os.environ.get("BIFLOW_SMTP_PORT", "587"))
    except ValueError as error:
        raise EmailConfigurationError("BIFLOW_SMTP_PORT must be a valid port number.") from error
    if not 1 <= port <= 65535:
        raise EmailConfigurationError("BIFLOW_SMTP_PORT must be between 1 and 65535.")

    username = os.environ.get("BIFLOW_SMTP_USER", "").strip()
    password = os.environ.get("BIFLOW_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailConfigurationError(
            "Set both BIFLOW_SMTP_USER and BIFLOW_SMTP_PASSWORD, or leave both unset."
        )

    use_ssl = os.environ.get("BIFLOW_SMTP_USE_SSL", "").strip().lower()
    return {
        "host": host,
        "sender": sender,
        "port": port,
        "use_ssl": use_ssl in {"1", "true", "yes"},
        "username": username,
        "password": password,
    }


def _send_password_reset_email(
    recipient: str,
    code: str,
    settings: dict[str, str | int | bool],
) -> None:
    message = EmailMessage()
    message["Subject"] = "Your BIFlow password reset code"
    message["From"] = str(settings["sender"])
    message["To"] = recipient
    message.set_content(
        f"Your BIFlow password reset code is {code}. "
        f"It expires in {PASSWORD_RESET_TTL_SECONDS // 60} minutes."
    )

    try:
        if settings["use_ssl"]:
            with smtplib.SMTP_SSL(
                str(settings["host"]),
                int(settings["port"]),
                timeout=10,
                context=ssl.create_default_context(),
            ) as server:
                if settings["username"]:
                    server.login(str(settings["username"]), str(settings["password"]))
                server.send_message(message)
        else:
            with smtplib.SMTP(
                str(settings["host"]), int(settings["port"]), timeout=10
            ) as server:
                server.starttls(context=ssl.create_default_context())
                if settings["username"]:
                    server.login(str(settings["username"]), str(settings["password"]))
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("The password reset email could not be sent.") from error


def request_password_reset(email: str) -> bool:
    normalized_email = validate_email(email)
    settings = _smtp_settings()
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_bytes(16)
    token_hash = hashlib.sha256(salt + code.encode("ascii")).hexdigest()
    expires_at = int(time.time()) + PASSWORD_RESET_TTL_SECONDS

    with closing(_connect()) as connection, connection:
        user = connection.execute(
            "SELECT 1 FROM users WHERE email = ?", (normalized_email,)
        ).fetchone()
        if user is None:
            return False
        connection.execute(
            """
            INSERT OR REPLACE INTO password_reset_tokens
                (email, token_hash, token_salt, expires_at, attempts)
            VALUES (?, ?, ?, ?, 0)
            """,
            (normalized_email, token_hash, salt.hex(), expires_at),
        )

    try:
        _send_password_reset_email(normalized_email, code, settings)
    except EmailDeliveryError:
        with closing(_connect()) as connection, connection:
            connection.execute(
                "DELETE FROM password_reset_tokens WHERE email = ? AND token_hash = ?",
                (normalized_email, token_hash),
            )
        raise

    return True


def reset_password(email: str, code: str, new_password: str) -> bool:
    try:
        normalized_email = validate_email(email)
    except ValueError:
        return False
    validate_password(new_password)
    normalized_code = code.strip()
    if not re.fullmatch(r"\d{6}", normalized_code):
        return False

    with closing(_connect()) as connection, connection:
        token = connection.execute(
            """
            SELECT token_hash, token_salt, expires_at, attempts
            FROM password_reset_tokens
            WHERE email = ?
            """,
            (normalized_email,),
        ).fetchone()
        if token is None:
            return False

        if (
            token["expires_at"] <= int(time.time())
            or token["attempts"] >= PASSWORD_RESET_MAX_ATTEMPTS
        ):
            connection.execute(
                "DELETE FROM password_reset_tokens WHERE email = ?",
                (normalized_email,),
            )
            return False

        candidate_hash = hashlib.sha256(
            bytes.fromhex(token["token_salt"]) + normalized_code.encode("ascii")
        ).hexdigest()
        if not hmac.compare_digest(candidate_hash, token["token_hash"]):
            connection.execute(
                "UPDATE password_reset_tokens SET attempts = attempts + 1 WHERE email = ?",
                (normalized_email,),
            )
            return False

        salt = secrets.token_bytes(16)
        password_hash = _hash_password(new_password, salt)
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, password_salt = ?
            WHERE email = ?
            """,
            (password_hash.hex(), salt.hex(), normalized_email),
        )
        if cursor.rowcount != 1:
            connection.execute(
                "DELETE FROM password_reset_tokens WHERE email = ?",
                (normalized_email,),
            )
            return False
        connection.execute(
            "DELETE FROM password_reset_tokens WHERE email = ?", (normalized_email,)
        )

    return True