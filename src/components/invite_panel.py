"""Teacher UI for enrolment invites (QR links) and pending enrolment requests. All rules are enforced by the database."""
from __future__ import annotations

import io

import segno
import streamlit as st

from src.services import invite_service
from src.ui.dialogs import confirm_dialog
from src.ui.feedback import show_error
from src.ui.widgets import badge_html, empty_state, note
from src.utils.errors import AppError
from src.utils.timefmt import format_local

_STATE = {"VALID": ("Active", "sc-ok"), "EXPIRED": ("Expired", "sc-muted"), "REVOKED": ("Revoked", "sc-bad"),
          "USED_UP": ("Fully used", "sc-muted"), "NOT_OPEN": ("Not open yet", "sc-warn")}
_OPENS = {"Right away": 0, "In 1 hour": 60, "In 1 day": 1440}


def _qr_png(url: str) -> bytes:
    out = io.BytesIO()
    segno.make(url).save(out, kind="png", scale=8, border=2)
    return out.getvalue()


def invite_panel(subject: dict) -> None:
    sid = subject["subject_id"]
    st.markdown("**Invite link and QR code**")
    st.caption("Each invite expires, can be limited to a number of students, and can be cancelled. Students must log in to use it.")
    c1, c2, c3 = st.columns(3)
    ttl_label = c1.selectbox("Valid for", list(invite_service.TTL_CHOICES), index=1, key=f"inv_ttl_{sid}")
    uses = c2.selectbox("Students who can join", invite_service.USE_CHOICES, index=2, key=f"inv_uses_{sid}")
    opens_label = c3.selectbox("Enrolment opens", list(_OPENS), key=f"inv_open_{sid}")
    approval = st.checkbox("I approve each student before they join", key=f"inv_appr_{sid}")
    ttl, opens = invite_service.TTL_CHOICES[ttl_label], _OPENS[opens_label]
    if st.button("Create invite", icon=":material/qr_code_2:", type="primary", key=f"inv_new_{sid}", disabled=opens >= ttl):
        try:
            st.session_state[f"inv_made_{sid}"] = invite_service.create(sid, ttl, int(uses), approval, opens)
        except AppError as exc:
            show_error(exc)
    made = st.session_state.get(f"inv_made_{sid}")
    if made:
        with st.container(border=True):
            st.success("Invite created. Copy the link or show the QR code now: for security it cannot be shown again.")
            st.code(made["url"], language="text")
            st.image(_qr_png(made["url"]), width=200, caption="Scan to join")
            if st.button("I have copied it", key=f"inv_done_{sid}"):
                st.session_state.pop(f"inv_made_{sid}", None)
                st.rerun()
    try:
        invites = invite_service.list_invites(sid)
    except AppError as exc:
        show_error(exc)
        return
    if not invites:
        empty_state("No invites yet", "Create one above to share a link or QR code.")
        return
    for i in invites:
        label, kind = _STATE[i["state"]]
        a, b = st.columns([5, 1], vertical_alignment="center")
        a.markdown(f"{badge_html(label, kind)} &nbsp; {i['uses']} of {i['max_uses']} used, expires {format_local(i['expires_at'])}"
                   f"{', needs your approval' if i['require_approval'] else ''}")
        if i["state"] in ("VALID", "NOT_OPEN") and b.button("Revoke", key=f"inv_rev_{i['invite_id']}"):
            confirm_dialog("Revoke this invite?", "The link and QR code stop working immediately. Students who already joined stay enrolled.", "Revoke invite",
                           lambda iid=i["invite_id"]: invite_service.revoke(iid), key=f"inv_rev_{i['invite_id']}_dlg", success="Invite revoked")


def requests_panel() -> None:
    """Pending enrolment requests across the teacher's subjects."""
    try:
        pending = invite_service.pending_requests()
    except AppError as exc:
        show_error(exc)
        return
    if not pending:
        return
    st.subheader(f"Enrolment requests ({len(pending)})")
    note("These students used an invite that needs your approval. They are not enrolled until you approve.")
    for r in pending:
        a, b, c = st.columns([4, 1, 1], vertical_alignment="center")
        a.markdown(f"**{r['student']}**" + (f" ({r['roll_number']})" if r.get("roll_number") else "") + f" wants to join {r['subject']}")
        for col, approve, label in ((b, True, "Approve"), (c, False, "Decline")):
            if col.button(label, key=f"req_{'a' if approve else 'd'}_{r['request_id']}", type="primary" if approve else "secondary", width="stretch"):
                try:
                    invite_service.decide(r["request_id"], approve)
                except AppError as exc:
                    show_error(exc)
                    return
                st.toast("Student approved" if approve else "Request declined")
                st.rerun()
