"""Student side of a QR/link invite: preview the subject, then join (or request to join)."""
import streamlit as st

from src.services import invite_service
from src.services.invite_service import MESSAGES, Redeem
from src.ui.feedback import show_error
from src.utils.errors import AppError


def _close():
    st.query_params.clear()
    st.rerun()


@st.dialog("Join a class")
def invite_enroll_dialog(token: str):
    try:
        info = invite_service.preview(token)
        state = info.get("state")
        if state != "VALID" and not info.get("enrolled") and not info.get("pending"):
            st.error(MESSAGES.get(Redeem(state), "This invite link is not valid.") if state in Redeem.__members__ else "This invite link is not valid.")
            if st.button("Close"):
                _close()
            return
        if info.get("enrolled"):
            st.info("You're already enrolled in this class.")
            if st.button("Got it"):
                _close()
            return
        if info.get("pending"):
            st.info("Your request is waiting for the teacher's approval.")
            if st.button("Got it"):
                _close()
            return
        name = str(info["name"]).replace("*", "\\*")
        st.markdown(f"Join **{name}**?" + (" Your teacher approves each student, so you will join once they accept." if info.get("require_approval") else ""))
        c1, c2 = st.columns(2)
        if c1.button("Not now", width="stretch"):
            _close()
        if c2.button("Request to join" if info.get("require_approval") else "Join class", type="primary", width="stretch"):
            outcome, _ = invite_service.redeem(token)
            if outcome is Redeem.ENROLLED:
                st.toast("Joined successfully")
            elif outcome is Redeem.PENDING_APPROVAL:
                st.toast("Request sent to your teacher")
            elif outcome in MESSAGES:
                st.toast(MESSAGES[outcome])
            _close()
    except AppError as exc:
        show_error(exc)
