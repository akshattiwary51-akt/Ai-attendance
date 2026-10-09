"""Typed application errors.

Every error carries a *user_message* that is safe to display, while the
exception text itself is for logs only.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for all expected application errors."""

    default_user_message = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None, *, user_message: str | None = None):
        super().__init__(message or user_message or self.default_user_message)
        # Internal *message* is for logs only and is never shown to users.
        self.user_message = user_message or self.default_user_message


class ValidationError(AppError):
    """User input is invalid."""


class AuthenticationError(AppError):
    default_user_message = "Invalid email or password."


class DatabaseError(AppError):
    default_user_message = "A database error occurred. Please try again."


class DuplicateError(DatabaseError):
    """A unique constraint was violated (duplicate row)."""

    default_user_message = "That record already exists."


class AIError(AppError):
    default_user_message = "The AI model failed to process this input."


class ConfigurationError(AppError):
    default_user_message = "The application is not configured correctly."


class NotFoundError(AppError):
    default_user_message = "We couldn't find that record."


class ConflictError(AppError):
    """The action conflicts with the current state (e.g. session already open/closed)."""

    default_user_message = "That action conflicts with the current state. Please refresh and try again."


class AuthorizationError(AppError):
    default_user_message = "You don't have permission to do that."
