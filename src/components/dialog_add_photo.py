import streamlit as st

from src.ui.feedback import show_error
from src.utils.errors import AppError
from src.utils.images import load_image


def _add(file_like) -> bool:
    try:
        st.session_state.attendance_images.append(load_image(file_like))
        return True
    except AppError as exc:
        show_error(exc)
        return False


@st.dialog("Capture or upload photos")
def add_photos_dialog():
    st.write("Add classroom photos to scan for attendance")
    st.session_state.setdefault("photo_tab", "camera")

    t1, t2 = st.columns(2)
    with t1:
        if st.button("Camera", type="primary" if st.session_state.photo_tab == "camera" else "tertiary", width="stretch"):
            st.session_state.photo_tab = "camera"
    with t2:
        if st.button("Upload photos", type="primary" if st.session_state.photo_tab == "upload" else "tertiary", width="stretch"):
            st.session_state.photo_tab = "upload"

    if st.session_state.photo_tab == "camera":
        cam_photo = st.camera_input("Take Snapshot", key="dialog_cam")
        if cam_photo and _add(cam_photo):
            st.toast("Photo captured")
            st.rerun()

    if st.session_state.photo_tab == "upload":
        files = st.file_uploader("Choose image files", type=["jpg", "png", "jpeg"], accept_multiple_files=True, key="dialog_upload")
        if files:
            added = sum(_add(f) for f in files)
            if added:
                st.toast(f"{added} photo(s) uploaded")
                st.rerun()

    st.divider()
    if st.button("Done", type="primary", width="stretch"):
        st.rerun()
