"""Pure aggregation helpers for charts (no I/O, no Streamlit)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.analytics import attendance_math as am

GRANULARITIES = ("day", "week", "month")


def bucket_key(dt: datetime, granularity: str, tz: ZoneInfo) -> date:
    d = dt.astimezone(tz).date()
    if granularity == "day":
        return d
    if granularity == "week":
        return d - timedelta(days=d.weekday())          # Monday of that week
    if granularity == "month":
        return d.replace(day=1)
    raise ValueError(f"unknown granularity {granularity}")


def trend(sessions: Iterable[Mapping], granularity: str, tz: ZoneInfo) -> list[dict]:
    """Attendance % per time bucket from per-session summaries ({started_at: datetime, present, late, absent, excused, conducted}).
    Percentages are weighted by classes conducted (sum attended / sum conducted), not an average of session percentages."""
    acc: dict[date, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])   # attended, conducted, present, late, absent, excused
    for s in sessions:
        k = bucket_key(s["started_at"], granularity, tz)
        a = acc[k]
        a[0] += s["present"] + s["late"]; a[1] += s["conducted"]; a[2] += s["present"]; a[3] += s["late"]; a[4] += s["absent"]; a[5] += s["excused"]
    return [{"period": k, "percentage": am.percentage(v[0], v[1]) if v[1] else None, "attended": v[0], "conducted": v[1],
             "present": v[2], "late": v[3], "absent": v[4], "excused": v[5]} for k, v in sorted(acc.items())]


def distribution(percentages: Sequence[float], bins: Sequence[int] = (0, 50, 60, 70, 75, 80, 90, 100)) -> list[dict]:
    """Histogram of student percentages; the last bin includes 100. Bins are [lo, hi)."""
    edges = list(bins)
    out = [{"label": f"{lo}-{hi}%", "lo": lo, "hi": hi, "count": 0} for lo, hi in zip(edges, edges[1:])]
    for p in percentages:
        for i, b in enumerate(out):
            if b["lo"] <= p < b["hi"] or (i == len(out) - 1 and p == b["hi"]):
                b["count"] += 1
                break
    return out


def ranking(rows: Sequence[Mapping], key: str = "percentage", top: int | None = None) -> list[dict]:
    """Sort descending by percentage (ties broken by name) and add a competition rank (1,2,2,4)."""
    ordered = sorted(rows, key=lambda r: (-r[key], r["name"].lower()))
    out, prev, rank = [], None, 0
    for i, r in enumerate(ordered, 1):
        if r[key] != prev:
            rank, prev = i, r[key]
        out.append({**r, "rank": rank})
    return out[:top] if top else out


def status_totals(sessions: Iterable[Mapping]) -> dict[str, int]:
    t = {"present": 0, "late": 0, "absent": 0, "excused": 0}
    for s in sessions:
        for k in t:
            t[k] += s[k]
    return t


def heatmap(sessions: Sequence[Mapping], records: Iterable[Mapping], names: Mapping[int, str]) -> list[dict]:
    """Student x session grid: one cell per (student, session) with value 1 attended / 0 absent / None excused-or-no-record.
    `sessions` are completed sessions (oldest first); `records` carry session_id, student_id, status."""
    order = {s["session_id"]: i for i, s in enumerate(sessions)}
    label = {s["session_id"]: s["started_at"].strftime("%d %b") if hasattr(s["started_at"], "strftime") else str(s["started_at"]) for s in sessions}
    cell: dict[tuple[int, int], int | None] = {}
    for r in records:
        if r["session_id"] not in order:
            continue
        cell[(r["student_id"], r["session_id"])] = 1 if r["status"] in am.ATTENDED else 0 if r["status"] == "ABSENT" else None
    out = []
    for sid, name in names.items():
        for s in sessions:
            out.append({"student": name, "student_id": sid, "session_id": s["session_id"], "session": f"#{order[s['session_id']] + 1} {label[s['session_id']]}",
                        "order": order[s["session_id"]], "value": cell.get((sid, s["session_id"]))})
    return out


def weekday_hour_counts(sessions: Iterable[Mapping], tz: ZoneInfo) -> list[dict]:
    """When classes happen: counts per (weekday, hour) - the 'attendance heatmap' by time slot, with average attendance %."""
    acc: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0])
    for s in sessions:
        d = s["started_at"].astimezone(tz)
        a = acc[(d.weekday(), d.hour)]
        a[0] += 1; a[1] += s["present"] + s["late"]; a[2] += s["conducted"]
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [{"weekday": names[w], "weekday_idx": w, "hour": h, "sessions": v[0], "percentage": am.percentage(v[1], v[2]) if v[2] else None}
            for (w, h), v in sorted(acc.items())]
