import streamlit as st

from src.components.footer import footer_home
from src.ui.theme import apply_theme, hide_sidebar
from src.ui.shell import LOGO_SVG

_PERSON = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
           '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>')
_BOARD = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
          '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>')


def _role_card(icon: str, title: str, body: str) -> None:
    st.markdown(f'<div class="sc-icon-tile">{icon}</div><div class="sc-role-title">{title}</div><p class="sc-role-body">{body}</p>', unsafe_allow_html=True)


def home_screen():
    apply_theme()
    hide_sidebar()
    st.markdown(f'<div class="sc-auth-brand" style="margin-top:1rem">{LOGO_SVG}<div class="sc-brand-name">SnapClass</div></div>', unsafe_allow_html=True)
    st.markdown('<h1 class="sc-page-title">Welcome to SnapClass</h1>'
                '<p class="sc-page-desc" style="margin-bottom:1.5rem">Attendance from classroom photos and voice, reviewed by the teacher before anything is saved. Choose how you will use it.</p>',
                unsafe_allow_html=True)
    col1, col2 = st.columns(2, gap="large")
    with col1, st.container(border=True, key="role_student"):
        _role_card(_PERSON, "I'm a student", "See your attendance in every subject, know which classes need attention, and manage your face and voice samples.")
        if st.button("Continue as student", type="primary", icon=":material/arrow_forward:", icon_position="right", key="student_portal", width="stretch"):
            st.session_state["login_type"] = "student"
            st.rerun()
    with col2, st.container(border=True, key="role_teacher"):
        _role_card(_BOARD, "I'm a teacher", "Take attendance from photos or voice, review the results, correct records with an audit trail, and track every class.")
        if st.button("Continue as teacher", type="primary", icon=":material/arrow_forward:", icon_position="right", key="teacher_portal", width="stretch"):
            st.session_state["login_type"] = "teacher"
            st.rerun()
    st.space()
    if st.button("Administrator login", type="tertiary", icon=":material/admin_panel_settings:", key="admin_portal"):
        st.session_state["login_type"] = "admin"
        st.rerun()
    footer_home()
