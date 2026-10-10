"""Chat panel for the attendance assistant (UI only; all logic and authorization live in services/assistant_service)."""
from __future__ import annotations

import streamlit as st

from src.assistant.router import HELP
from src.services import assistant_service
from src.utils.errors import AppError

KEY = "assistant_history"


def assistant_chat(role: str) -> None:
    st.caption("Ask about attendance in your own words. Answers come from your attendance records only; the assistant cannot change anything.")
    history = st.session_state.setdefault(KEY, [])
    st.session_state.setdefault("assistant_limiter", assistant_service.limiter_for_session())
    if not history:
        st.markdown("Try:\n" + "\n".join(f"- {e}" for e in HELP[role]))
    for who, text in history:
        with st.chat_message(who):
            st.markdown(text)                                    # plain markdown: no unsafe HTML
    question = st.chat_input("Ask about attendance", key=f"assistant_input_{role}", max_chars=assistant_service.MAX_QUESTION)
    if question:
        history.append(("user", question))
        try:
            answer = assistant_service.ask(question, st.session_state.assistant_limiter)
            history.append(("assistant", answer.text))
        except AppError as exc:
            history.append(("assistant", exc.user_message))
        del history[:-30]                                        # bounded history
        st.rerun()
