"""Turns tool results into plain-language answers (rules mode). Every number comes from the tool result."""
from __future__ import annotations


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _error(r: dict) -> str | None:
    if "error" not in r:
        return None
    opts = r.get("options") or []
    return r["message"] + (" Options: " + ", ".join(opts) + "." if opts else "")


def render(tool: str, r: dict) -> str:
    err = _error(r)
    if err:
        return err
    return _RENDER[tool](r)


def _attendance(r: dict) -> str:
    lines = []
    if "overall_percentage" in r:
        if not r["conducted"]:
            return "No classes have been recorded for you yet."
        lines.append(f"Overall you have attended {r['attended']} of {r['conducted']} classes ({r['overall_percentage']:g}%).")
    for s in r["subjects"]:
        if not s["conducted"]:
            lines.append(f"- {s['subject']}: no classes recorded yet.")
            continue
        flag = "on target" if s["percentage"] >= s["target"] else f"below the {s['target']:g}% target"
        lines.append(f"- {s['subject']}: {s['percentage']:g}% ({s['attended']}/{s['conducted']}), {flag}.")
    return "\n".join(lines) or "You are not enrolled in any subject yet."


def _can_miss(r: dict) -> str:
    if not r["has_data"]:
        return f"No classes have been recorded for {r['subject']} yet, so I cannot say."
    n, cls = r["classes"], "class" if r["classes"] == 1 else "classes"
    if r["allowed"]:
        return (f"Yes. In {r['subject']} you can miss up to {r['max_can_miss']} more {('class' if r['max_can_miss'] == 1 else 'classes')} and stay at or above "
                f"{r['target']:g}%. Missing {n} {cls} would take you from {r['percentage_now']:g}% to {r['percentage_after']:g}%.")
    return (f"No. Missing {n} {cls} would take you from {r['percentage_now']:g}% to {r['percentage_after']:g}%, below the {r['target']:g}% target. "
            f"You can afford to miss {r['max_can_miss']} more.")


def _needed(r: dict) -> str:
    lines = []
    for s in r["subjects"]:
        if not s["has_data"]:
            lines.append(f"- {s['subject']}: no classes recorded yet.")
        elif s["already_meets"]:
            lines.append(f"- {s['subject']}: you already meet {s['target']:g}%.")
        elif s["consecutive_classes_needed"] is None:
            lines.append(f"- {s['subject']}: {s['target']:g}% can no longer be reached.")
        else:
            lines.append(f"- {s['subject']}: attend the next {_plural(s['consecutive_classes_needed'], 'class', 'classes')} in a row to reach {s['target']:g}%.")
    return "\n".join(lines) or "You are not enrolled in any subject yet."


def _risk(r: dict) -> str:
    if not r["subjects"]:
        return f"None of your {_plural(r['checked'], 'subject')} is at risk right now." if r["checked"] else "You are not enrolled in any subject yet."
    return "\n".join(f"- {s['subject']} ({'high' if s['risk'] == 'HIGH' else 'watch'}): {s['percentage']:g}%. " + " ".join(s["reasons"]) for s in r["subjects"])


def _forecast(r: dict) -> str:
    if not r["subjects"]:
        return "There is not enough attendance data to forecast yet."
    return "\n".join(f"- {s['subject']}: about {s['expected_percentage']:g}% by the end of the month (likely {s['likely_range'][0]:g}-{s['likely_range'][1]:g}%), "
                     f"{s['chance_below_target']:.0%} chance of ending below target ({s['confidence']} confidence)." for s in r["subjects"]) + \
        "\nThis is a statistical estimate, not a promise."


def _below(r: dict) -> str:
    if not r["count"]:
        return f"No student is below {r['threshold']:g}%."
    lines = [f"{_plural(r['count'], 'student')} below {r['threshold']:g}%:"] + [f"- {s['student']} ({s['subject']}): {s['percentage']:g}%" for s in r["students"]]
    return "\n".join(lines + (["(showing the lowest 25)"] if r["truncated"] else []))


def _subject_att(r: dict) -> str:
    when = {"all": "overall", "this_week": "this week", "this_month": "this month"}[r["period"]]
    if not r["sessions"]:
        return f"No completed sessions for {r['subject']} {when}."
    pct = f"{r['percentage']:g}%" if r["percentage"] is not None else "n/a"
    return (f"{r['subject']} {when}: {_plural(r['sessions'], 'session')}, attendance {pct} "
            f"({r['present']} present, {r['late']} late, {r['absent']} absent, {r['excused']} excused).")


def _missed(r: dict) -> str:
    lines = []
    for s in r["subjects"]:
        if s["completed_classes"] < r["classes"]:
            lines.append(f"- {s['subject']}: only {_plural(s['completed_classes'], 'class', 'classes')} held so far.")
        elif s["students"]:
            lines.append(f"- {s['subject']}: " + ", ".join(s["students"]))
        else:
            lines.append(f"- {s['subject']}: nobody missed the last {r['classes']} classes.")
    return f"Students who missed each of the last {r['classes']} classes:\n" + "\n".join(lines) if lines else "You have no subjects yet."


def _today(r: dict) -> str:
    if not r["sessions"]:
        return f"No attendance has been taken today ({r['date']})."
    return f"Today ({r['date']}):\n" + "\n".join(
        f"- {s['subject']}: {s['present']} present, {s['absent']} absent, {s['excused']} excused" + (" (in progress)" if s["status"] == "OPEN" else "") for s in r["sessions"])


def _at_risk(r: dict) -> str:
    if not r["count"]:
        return "Nobody is currently at risk."
    return f"{_plural(r['count'], 'student')} at risk:\n" + "\n".join(f"- {s['student']} ({s['subject']}): {s['percentage']:g}%. {s['reason']}" for s in r["students"])


_RENDER = {"get_my_attendance": _attendance, "can_i_miss": _can_miss, "classes_needed": _needed, "my_risk_subjects": _risk, "my_forecast": _forecast,
           "students_below": _below, "subject_attendance": _subject_att, "students_missed_last": _missed, "todays_summary": _today, "at_risk_students": _at_risk}
