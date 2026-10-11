"""Reusable confirmation dialog for actions that are hard to take back."""
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from src.ui.feedback import show_error
from src.utils.errors import AppError


def confirm_dialog(title: str, body: str, confirm_label: str, action: Callable[[], object], *, key: str, success: str = "Done",
                   cancel_label: str = "Cancel") -> None:
    """Open a modal that explains the consequence and runs ``action`` only on confirmation.

    ``action`` may raise ``AppError``; its safe message is shown and the dialog stays open.
    """
    @st.dialog(title)
    def _dialog() -> None:
        st.write(body)
        c1, c2 = st.columns(2)
        if c1.button(cancel_label, width="stretch", key=f"{key}_cancel"):
            st.rerun()
        if c2.button(confirm_label, width="stretch", type="primary", key=f"{key}_confirm"):
            try:
                action()
            except AppError as exc:
                show_error(exc)
                return
            st.toast(success)
            st.rerun()

    _dialog()
