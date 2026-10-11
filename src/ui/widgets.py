"""Small HTML widgets for dashboards. Every dynamic value is escaped; colours come from theme variables."""
from __future__ import annotations

import re

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


_GLYPH = {"sc-ok": "✓", "sc-warn": "!", "sc-bad": "✕", "sc-info": "i", "sc-muted": "–"}
_STATUS_KIND = {
    "PRESENT": ("Present", "sc-ok"), "LATE": ("Late", "sc-warn"), "ABSENT": ("Absent", "sc-bad"), "EXCUSED": ("Excused", "sc-info"),
    "UNKNOWN": ("Unknown", "sc-muted"), "REJECTED": ("Rejected", "sc-bad"),
    "OPEN": ("Open", "sc-warn"), "COMPLETED": ("Completed", "sc-ok"), "CANCELLED": ("Cancelled", "sc-muted"),
    "ACTIVE": ("Active", "sc-ok"), "INACTIVE": ("Inactive", "sc-muted"), "PENDING": ("Pending approval", "sc-warn"),
}


def badge_html(text: str, kind: str = "sc-muted") -> str:
    """A pill with a glyph and a word, so status never depends on colour alone."""
    glyph = _GLYPH.get(kind, "")
    glyph_html = f'<span class="sc-glyph" aria-hidden="true">{glyph}</span>' if glyph else ""
    return f'<span class="sc-badge {esc(kind)}">{glyph_html}{esc(text)}</span>'


def status_badge_html(status: str) -> str:
    label, kind = _STATUS_KIND.get(str(status).upper(), (str(status).title(), "sc-muted"))
    return badge_html(label, kind)


def plain_status(status: str) -> str:
    """Readable label for a status code or an emoji-prefixed service label ('✅ Present' -> 'Present')."""
    text = _STATUS_KIND.get(str(status).upper(), (None,))[0]
    return text or re.sub(r"^[^A-Za-z]+", "", str(status)) or str(status)


_STATUS_TEXT = {"PRESENT": "✓ Present", "LATE": "! Late", "ABSENT": "✕ Absent", "EXCUSED": "i Excused", "UNKNOWN": "– Unknown", "REJECTED": "✕ Rejected"}


def status_text(status: str) -> str:
    """Glyph + word for tables, which cannot render badges: status is readable without colour."""
    return _STATUS_TEXT.get(str(status).upper(), plain_status(status))


def confidence_config() -> dict:
    """Column config that draws a real confidence score as a bar and leaves a missing score blank."""
    return {"Confidence": st.column_config.ProgressColumn("Confidence", min_value=0.0, max_value=1.0, format="%.2f")}


def page_header(title: str, description: str = "", crumbs: tuple[str, ...] = ()) -> None:
    crumb_html = f'<nav class="sc-crumbs" aria-label="Breadcrumb">{"".join(f"<span>{esc(c)}</span>" for c in crumbs)}</nav>' if crumbs else ""
    desc_html = f'<p class="sc-page-desc">{esc(description)}</p>' if description else ""
    st.markdown(f'<header class="sc-page-head">{crumb_html}<h1 class="sc-page-title">{esc(title)}</h1>{desc_html}</header>', unsafe_allow_html=True)


def section(title: str, description: str = "") -> None:
    desc_html = f'<p class="sc-section-desc">{esc(description)}</p>' if description else ""
    st.markdown(f'<h2 class="sc-section-title">{esc(title)}</h2>{desc_html}', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="sc-note">{esc(text)}</div>', unsafe_allow_html=True)


def stepper(steps: list[str], current: int) -> None:
    """Progress through a guided flow. ``current`` is 1-based; steps before it are done."""
    items = []
    for i, label in enumerate(steps, start=1):
        state, word = ("sc-done", "Done") if i < current else ("sc-current", "In progress") if i == current else ("", "Next")
        dot = "✓" if i < current else str(i)
        aria = ' aria-current="step"' if i == current else ""
        items.append(f'<li class="sc-step {state}"{aria}><span class="sc-step-dot" aria-hidden="true">{dot}</span>'
                     f'<span class="sc-step-label">{esc(label)}<span class="sc-step-state">{word}</span></span></li>')
    st.markdown(f'<ol class="sc-steps" aria-label="Progress">{"".join(items)}</ol>', unsafe_allow_html=True)


def summary_chips(items: list[tuple[str, object, str]]) -> str:
    """[(label, value, css kind)] -> a row of badges."""
    return '<div class="sc-summary">' + "".join(badge_html(f"{v} {l}", k) for l, v, k in items) + "</div>"


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


def loading_note(text: str = "Loading…"):
    """Context manager for data-driven sections: a spinner with consistent wording."""
    return st.spinner(text)
