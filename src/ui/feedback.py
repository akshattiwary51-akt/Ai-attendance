"""Consistent user-facing error display."""
from __future__ import annotations

import streamlit as st

from src.utils.errors import AppError
from src.utils.logging import get_logger

log = get_logger(__name__)


def show_error(exc: AppError) -> None:
    """Show the safe message; validation problems are warnings, the rest errors."""
    from src.utils.errors import ValidationError

    (st.warning if isinstance(exc, ValidationError) else st.error)(exc.user_message)
