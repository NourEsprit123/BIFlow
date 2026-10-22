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
)

__all__ = [
    "EmailConfigurationError",
    "EmailDeliveryError",
    "UserAlreadyExistsError",
    "authenticate_user",
    "register_user",
    "request_password_reset",
    "reset_password",
    "validate_email",
    "validate_password",
]
