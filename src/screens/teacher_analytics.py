"""Teacher 'Analytics' tab: trends, distribution, ranking, heatmaps, forecasts and anomaly flags (UI only)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analytics.anomalies import HIGH, WARN
from src.services import analytics_service, subject_service
from src.ui import charts
from src.ui.feedback import show_error
from src.ui.widgets import empty_state, kpi_row
from src.utils.errors import AppError

RISK_TEXT = {"HIGH": "High risk", "MEDIUM": "Watch", "LOW": "On track", "NO_DATA": "No data"}
SEVERITY_TEXT = {"HIGH": "🔴 High", "WARN": "🟠 Warning", "INFO": "🔵 Info"}


def anomaly_table(found) -> pd.DataFrame:
    return pd.DataFrame([{"Severity": SEVERITY_TEXT[a.severity], "Type": a.code.replace("_", " ").title(), "What was noticed": a.message,
                          "Subject": a.subject_id, "Session": a.session_id, "Student": a.student_id} for a in found])


def show_anomalies(found, empty="No unusual patterns detected.") -> None:
    if not found:
        st.success(empty)
        return
    st.caption("These are flags for you to review. Nothing has been changed, and a flag does not mean something went wrong.")
    st.dataframe(anomaly_table(found), hide_index=True, width="stretch")


def _chart(c, fallback="Not enough data yet.") -> None:
    st.altair_chart(c, width="stretch") if c is not None else st.info(fallback)


def teacher_tab_analytics() -> None:
    teacher_id = st.session_state.teacher_data["teacher_id"]
    st.header("Analytics")
    try:
        subjects = subject_service.list_teacher_subjects(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if not subjects:
        empty_state("No subjects yet", "Create a subject and take attendance to see analytics.")
        return
    options = {f"{s['name']} - {s['subject_code']}": s["subject_id"] for s in subjects}
    c1, c2 = st.columns([3, 2])
    label = c1.selectbox("Subject", list(options), key="analytics_subject")
    gran = {"Daily": "day", "Weekly": "week", "Monthly": "month"}[c2.radio("Trend by", ["Daily", "Weekly", "Monthly"], index=1, horizontal=True, key="analytics_gran")]
    try:
        ta = analytics_service.teacher_analytics(teacher_id, options[label], gran)
        comparison = analytics_service.subject_comparison(teacher_id)
        found = analytics_service.teacher_anomalies(teacher_id)
    except AppError as exc:
        show_error(exc)
        return
    if ta.participation["sessions"] == 0:
        empty_state("No completed sessions yet", "Analytics appear after you confirm your first attendance session.")
    else:
        kpi_row([("Class average", f"{ta.class_average:g}%" if ta.class_average is not None else "—", f"target {ta.subject['target_percent']:g}%"),
                 ("Highest", f"{ta.highest['percentage']:g}%" if ta.highest else "—", ta.highest["name"] if ta.highest else ""),
                 ("Lowest", f"{ta.lowest['percentage']:g}%" if ta.lowest else "—", ta.lowest["name"] if ta.lowest else ""),
                 ("Sessions", ta.participation["sessions"], f"{ta.participation['avg_students_counted']:g} students counted on average")])
        t1, t2 = st.tabs(["Attendance trend", "Present vs absent"])
        with t1:
            _chart(charts.trend_line(ta.trend, ta.subject["target_percent"]))
        with t2:
            _chart(charts.status_bars(ta.trend))
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Distribution")
            _chart(charts.distribution_bars(ta.distribution))
        with c2:
            st.subheader("Subject comparison")
            _chart(charts.comparison_bars(comparison))
        st.subheader("Class heatmap")
        st.caption("Each row is a student and each column a class: green attended, red absent, grey excused or no record.")
        _chart(charts.heatmap(ta.heatmap))
        st.subheader("When classes are best attended")
        _chart(charts.time_slot_heatmap(ta.time_slots))
        st.subheader("Ranking")
        st.dataframe(pd.DataFrame([{"Rank": r["rank"], "Student": r["name"], "Attendance %": r["percentage"], "Attended": r["attended"], "Classes": r["conducted"]}
                                   for r in ta.ranking]), hide_index=True, width="stretch")

    st.subheader("Forecast: who may fall below target")
    st.caption(f"Estimated from each student's history over roughly the next {ta.n_future} classes. A statistical estimate, not a certainty; "
               "students with little history are marked low confidence.")
    if not ta.forecasts:
        st.info("No students are enrolled in this subject.")
    else:
        st.dataframe(pd.DataFrame([{"Student": x["name"], "Risk": RISK_TEXT[x["forecast"].risk], "Chance below target": f"{x['forecast'].prob_below_target:.0%}",
                                    "Expected %": x["forecast"].expected_pct, "Must attend": ("-" if x["forecast"].must_attend is None else x["forecast"].must_attend),
                                    "Confidence": x["forecast"].confidence, "Why": " ".join(x["forecast"].reasons[:2])} for x in ta.forecasts]),
                     hide_index=True, width="stretch")
    st.subheader("Unusual patterns")
    show_anomalies(found)
