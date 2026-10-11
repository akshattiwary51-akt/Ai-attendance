"""Compact notification list shown at the top of each role's overview."""
from __future__ import annotations

import streamlit as st

from src.services.notification_service import HIGH, WARN, Notification
from src.ui.widgets import badge_html
from src.utils.html import esc

_BADGE = {HIGH: ("Needs attention", "sc-bad"), WARN: ("Heads up", "sc-warn")}


def notifications_panel(items: list[Notification], state_key: str) -> None:
    """state_key: the session key holding the active page, so an action button can navigate."""
    if not items:
        return
    with st.expander(f"Notifications ({len(items)})", expanded=any(n.level == HIGH for n in items)):
        for i, n in enumerate(items):
            label, kind = _BADGE.get(n.level, ("Info", "sc-info"))
            a, b = st.columns([5, 1], vertical_alignment="center")
            a.markdown(f"{badge_html(label, kind)} &nbsp; **{esc(n.title)}**<br><span class='sc-sub'>{esc(n.body)}</span>", unsafe_allow_html=True)
            if n.page:
                b.button("Open", key=f"notif_{state_key}_{i}", type="tertiary", on_click=lambda p=n.page: st.session_state.__setitem__(state_key, p))
