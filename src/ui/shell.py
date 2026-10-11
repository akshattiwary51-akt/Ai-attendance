"""Application shell: brand, role-aware sidebar navigation, profile + logout, and the signed-out auth layout."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import streamlit as st

from src.ui.theme import apply_theme, hide_sidebar
from src.utils.html import esc
from src.utils.session import logout

LOGO_SVG = (
    '<svg width="38" height="38" viewBox="0 0 36 36" role="img" aria-label="SnapClass logo" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="scg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4F46E5"/><stop offset="1" stop-color="#7C3AED"/></linearGradient></defs>'
    '<rect width="36" height="36" rx="10" fill="url(#scg)"/>'
    '<path d="M10 14v-3a1 1 0 0 1 1-1h3M22 10h3a1 1 0 0 1 1 1v3M26 22v3a1 1 0 0 1-1 1h-3M14 26h-3a1 1 0 0 1-1-1v-3" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none"/>'
    '<path d="M14 18.5l3 3 5-6" stroke="#5EEAD4" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
)


def brand_html(subtitle: str = "AI attendance") -> str:
    return (f'<div class="sc-brand">{LOGO_SVG}<div><div class="sc-brand-name">SnapClass</div>'
            f'<div class="sc-brand-role">{esc(subtitle)}</div></div></div>')


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str


def _go(state_key: str, key: str) -> None:
    st.session_state[state_key] = key


def _initials(name: str) -> str:
    parts = [p for p in str(name).split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def sidebar(*, role_label: str, name: str, items: list[NavItem], state_key: str, cta: NavItem | None = None, default: str | None = None) -> str:
    """Render the shell for a signed-in user and return the active page key.

    ``cta`` is a prominent primary action (Take attendance for teachers); it is part of the same page state.
    """
    apply_theme()
    st.session_state.setdefault(state_key, default or (cta or items[0]).key)
    current = st.session_state[state_key]
    with st.sidebar:
        st.markdown(brand_html(role_label), unsafe_allow_html=True)
        if cta:
            st.button(cta.label, icon=cta.icon, key="nav_cta", width="stretch", type="primary", on_click=_go, args=(state_key, cta.key))
        st.markdown('<div class="sc-nav-label">Menu</div>', unsafe_allow_html=True)
        for item in items:
            st.button(item.label, icon=item.icon, key=f"nav_{item.key}", width="stretch",
                      type="primary" if current == item.key else "tertiary", on_click=_go, args=(state_key, item.key))
        st.markdown(f'<div class="sc-profile"><div class="sc-avatar" aria-hidden="true">{esc(_initials(name))}</div>'
                    f'<div><div class="sc-profile-name">{esc(name)}</div><div class="sc-profile-role">{esc(role_label)}</div></div></div>',
                    unsafe_allow_html=True)
        if st.button("Log out", icon=":material/logout:", key="loginbackbtn", width="stretch", type="secondary"):
            logout()
            st.rerun()
    return current


@contextmanager
def auth_layout(panel_title: str, points: list[str], *, back_label: str = "Back to home"):
    """Signed-out layout: brand + back button on top, a brand panel on the left and the form on the right."""
    apply_theme()
    hide_sidebar()
    top, back = st.columns([4, 1], vertical_alignment="center")
    with top:
        st.markdown(f'<div class="sc-auth-brand">{LOGO_SVG}<div class="sc-brand-name">SnapClass</div></div>', unsafe_allow_html=True)
    with back:
        if st.button(back_label, key="loginbackbtn", icon=":material/arrow_back:", type="tertiary", width="stretch"):
            st.session_state["login_type"] = None
            st.rerun()
    left, right = st.columns([5, 6], gap="large")
    with left:
        items = "".join(f"<li>{esc(p)}</li>" for p in points)
        st.markdown(f'<div class="sc-auth-panel"><h2>{esc(panel_title)}</h2><ul>{items}</ul></div>', unsafe_allow_html=True)
    with right:
        yield
