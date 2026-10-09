import io
from urllib.parse import quote

import segno
import streamlit as st

from src.config.settings import get_settings


@st.dialog("Share Class Link")
def share_subject_dialog(subject_name, subject_code):
    join_url = f"{get_settings().app_base_url}/?join-code={quote(str(subject_code), safe='')}"

    st.header("Scan to Join")
    out = io.BytesIO()
    segno.make(join_url).save(out, kind="png", scale=10, border=1)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Copy Link")
        st.code(join_url, language="text")
        st.code(subject_code, language="text")
        st.info("Copy this link to share on WhatsApp or Email")
    with col2:
        st.markdown("### Scan to Join")
        st.image(out.getvalue(), caption="QR code for class joining")
