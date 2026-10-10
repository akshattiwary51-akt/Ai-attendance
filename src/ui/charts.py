"""Altair chart builders (Streamlit's built-in charting stack; no extra dependency). Pure functions: rows in, chart out."""
from __future__ import annotations

import altair as alt
import pandas as pd

OK, BAD, MUTED = "#15803d", "#b91c1c", "#9ca3af"


def trend_line(rows: list[dict], target: float | None = None):
    df = pd.DataFrame([{"Period": str(r["period"]), "Attendance %": r["percentage"]} for r in rows if r["percentage"] is not None])
    if df.empty:
        return None
    line = alt.Chart(df).mark_line(point=True).encode(x=alt.X("Period:N", sort=None), y=alt.Y("Attendance %:Q", scale=alt.Scale(domain=[0, 100])),
                                                     tooltip=["Period", "Attendance %"])
    if target is None:
        return line
    rule = alt.Chart(pd.DataFrame({"t": [target]})).mark_rule(strokeDash=[5, 4], color=BAD).encode(y="t:Q")
    return line + rule


def status_bars(rows: list[dict]):
    long = [{"Period": str(r["period"]), "Status": k.title(), "Classes": r[k]} for r in rows for k in ("present", "late", "absent", "excused")]
    if not long:
        return None
    return alt.Chart(pd.DataFrame(long)).mark_bar().encode(
        x=alt.X("Period:N", sort=None), y="Classes:Q",
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Present", "Late", "Absent", "Excused"], range=[OK, "#ca8a04", BAD, MUTED])),
        tooltip=["Period", "Status", "Classes"])


def distribution_bars(bins: list[dict]):
    df = pd.DataFrame([{"Attendance": b["label"], "Students": b["count"], "order": i} for i, b in enumerate(bins)])
    return alt.Chart(df).mark_bar().encode(x=alt.X("Attendance:N", sort=alt.SortField("order")), y="Students:Q", tooltip=["Attendance", "Students"])


def heatmap(cells: list[dict]):
    if not cells:
        return None
    df = pd.DataFrame([{"Student": c["student"], "Class": c["session"], "order": c["order"],
                        "State": {1: "Attended", 0: "Absent", None: "Excused / no record"}[c["value"]]} for c in cells])
    return alt.Chart(df).mark_rect().encode(
        x=alt.X("Class:N", sort=alt.SortField("order"), axis=alt.Axis(labelAngle=-45)), y=alt.Y("Student:N", sort="ascending"),
        color=alt.Color("State:N", scale=alt.Scale(domain=["Attended", "Absent", "Excused / no record"], range=[OK, BAD, MUTED])),
        tooltip=["Student", "Class", "State"])


def time_slot_heatmap(slots: list[dict]):
    if not slots:
        return None
    df = pd.DataFrame(slots).rename(columns={"weekday": "Day", "hour": "Hour", "percentage": "Attendance %", "sessions": "Sessions"})
    return alt.Chart(df).mark_rect().encode(x=alt.X("Hour:O"), y=alt.Y("Day:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
                                            color=alt.Color("Attendance %:Q", scale=alt.Scale(domain=[0, 100], scheme="redyellowgreen")),
                                            tooltip=["Day", "Hour", "Sessions", "Attendance %"])


def comparison_bars(rows: list[dict]):
    """rows: {subject, percentage, target}"""
    df = pd.DataFrame([r for r in rows if r.get("percentage") is not None]).rename(columns={"subject": "Subject", "percentage": "Attendance %", "target": "Target %"})
    if df.empty:
        return None
    bars = alt.Chart(df).mark_bar().encode(x=alt.X("Subject:N", sort=None), y=alt.Y("Attendance %:Q", scale=alt.Scale(domain=[0, 100])),
                                           tooltip=["Subject", "Attendance %", "Target %"])
    ticks = alt.Chart(df).mark_tick(color=BAD, thickness=3, size=40).encode(x=alt.X("Subject:N", sort=None), y="Target %:Q")
    return bars + ticks
