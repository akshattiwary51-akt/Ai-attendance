"""Small HTML widgets for dashboards. Every dynamic value is escaped; colours come from theme variables."""
from __future__ import annotations

import streamlit as st

from src.analytics import attendance_math as am
from src.utils.html import esc

_RISK_CLASS = {am.HIGH: "sc-bad", am.MEDIUM: "sc-warn", am.LOW: "sc-ok", am.NO_DATA: "sc-muted"}
_RISK_LABEL = {am.HIGH: "High risk", am.MEDIUM: "Watch", am.LOW: "On track", am.NO_DATA: "No data"}


def kpi_html(label: str, value: object, hint: str = "") -> str:
    hint_html = f'<div class="sc-kpi-hint">{esc(hint)}</div>' if hint else ""
    return (f'<div class="sc-kpi"><div class="sc-kpi-label">{esc(label)}</div>'
            f'<div class="sc-kpi-value">{esc(value)}</div>{hint_html}</div>')


def kpi_row(items: list[tuple]) -> None:
    """items: (label, value[, hint]) tuples rendered as equal cards."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        with col:
            st.markdown(kpi_html(*item), unsafe_allow_html=True)


def badge_html(text: str, kind: str = "sc-muted") -> str:
    return f'<span class="sc-badge {esc(kind)}">{esc(text)}</span>'


def risk_badge_html(level: str) -> str:
    return badge_html(_RISK_LABEL.get(level, "No data"), _RISK_CLASS.get(level, "sc-muted"))


def progress_html(percentage: float, target: float) -> str:
    pct = max(0.0, min(100.0, float(percentage)))
    tgt = max(0.0, min(100.0, float(target)))
    kind = "sc-ok" if percentage >= target else "sc-bad"
    return (f'<div class="sc-progress" role="progressbar" aria-valuenow="{pct:.0f}" aria-valuemin="0" aria-valuemax="100">'
            f'<div class="sc-progress-fill {kind}" style="width:{pct:.1f}%"></div>'
            f'<div class="sc-progress-target" style="left:{tgt:.1f}%" title="Target {tgt:.0f}%"></div></div>')


def standing_message(standing) -> str:
    """Plain-language guidance derived from exact integer arithmetic."""
    if standing.conducted == 0:
        return "No classes have been recorded yet."
    if standing.percentage >= standing.target:
        n = standing.can_miss
        if n == 0:
            return "You are on target, but you cannot afford to miss the next class."
        return f"You can miss {n} more class{'es' if n != 1 else ''} and stay on target."
    n = standing.to_recover
    if n is None:
        return "The target can no longer be reached for this subject."
    return f"Attend the next {n} class{'es' if n != 1 else ''} in a row to get back to {standing.target:g}%."


def empty_state(title: str, body: str = "") -> None:
    body_html = f"<p>{esc(body)}</p>" if body else ""
    st.markdown(f'<div class="sc-empty"><h4>{esc(title)}</h4>{body_html}</div>', unsafe_allow_html=True)
