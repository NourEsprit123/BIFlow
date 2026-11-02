"""Authentication service and account operations."""

from .service import (
    EmailConfigurationError,
    EmailDeliveryError,
    UserAlreadyExistsError,
    authenticate_user,
    register_user,
    request_password_reset,
    reset_password,
    validate_email,
    validate_password,
    create_session,
    get_user_from_session,
    delete_session,
)

__all__ = [
    "EmailConfigurationError",
    "EmailDeliveryError",
    "UserAlreadyExistsError",
    "request_password_reset",
    "reset_password",
    "authenticate_user",
    "register_user",
    "validate_email",
    "validate_password",
    "create_session",
    "get_user_from_session",
    "delete_session",
]
