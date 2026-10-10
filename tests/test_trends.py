from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.analytics import trends as tr

UTC, IST = ZoneInfo("UTC"), ZoneInfo("Asia/Kolkata")


def s(day, hour=10, present=8, late=0, absent=2, excused=0, sid=1):
    return {"session_id": sid, "started_at": datetime(2026, 3, day, hour, tzinfo=timezone.utc), "present": present, "late": late, "absent": absent,
            "excused": excused, "conducted": present + late + absent}


def test_buckets_use_the_display_timezone():
    late_night = datetime(2026, 3, 8, 20, 0, tzinfo=timezone.utc)          # Sunday 20:00 UTC = Monday 01:30 IST
    assert tr.bucket_key(late_night, "day", UTC).day == 8 and tr.bucket_key(late_night, "day", IST).day == 9
    assert tr.bucket_key(late_night, "week", UTC).day == 2 and tr.bucket_key(late_night, "week", IST).day == 9
    assert tr.bucket_key(late_night, "month", IST).day == 1
    with pytest.raises(ValueError):
        tr.bucket_key(late_night, "year", UTC)


def test_trend_is_weighted_by_classes_not_an_average_of_percentages():
    rows = tr.trend([s(2, present=1, absent=0), s(3, present=9, absent=9)], "week", UTC)
    assert len(rows) == 1 and rows[0]["attended"] == 10 and rows[0]["conducted"] == 19 and rows[0]["percentage"] == 52.6
    daily = tr.trend([s(2), s(3), s(3, hour=15)], "day", UTC)
    assert [r["conducted"] for r in daily] == [10, 20] and daily == sorted(daily, key=lambda r: r["period"])


def test_trend_with_nothing_conducted_has_no_percentage():
    assert tr.trend([s(2, present=0, absent=0, excused=3)], "day", UTC)[0]["percentage"] is None
    assert tr.trend([], "day", UTC) == []


def test_distribution_bins_and_edges():
    d = tr.distribution([0, 49.9, 50, 74.9, 75, 100, 100, 89.9])
    counts = {b["label"]: b["count"] for b in d}
    assert counts["0-50%"] == 2 and counts["50-60%"] == 1 and counts["70-75%"] == 1 and counts["75-80%"] == 1 and counts["90-100%"] == 2
    assert sum(counts.values()) == 8


def test_ranking_has_competition_ranks_and_stable_ties():
    r = tr.ranking([{"name": "b", "percentage": 90}, {"name": "A", "percentage": 90}, {"name": "c", "percentage": 80}, {"name": "d", "percentage": 95}])
    assert [(x["name"], x["rank"]) for x in r] == [("d", 1), ("A", 2), ("b", 2), ("c", 4)]
    assert len(tr.ranking([{"name": "x", "percentage": 1}] * 5, top=3)) == 3


def test_status_totals_and_heatmap_cells():
    assert tr.status_totals([s(2, present=3, late=1, absent=2, excused=1), s(3, present=1, absent=0)]) == {"present": 4, "late": 1, "absent": 2, "excused": 1}
    sessions = [s(2, sid=1), s(3, sid=2)]
    recs = [{"session_id": 1, "student_id": 7, "status": "PRESENT"}, {"session_id": 2, "student_id": 7, "status": "ABSENT"},
            {"session_id": 1, "student_id": 8, "status": "EXCUSED"}, {"session_id": 99, "student_id": 7, "status": "PRESENT"}]
    cells = tr.heatmap(sessions, recs, {7: "Ann", 8: "Bob"})
    val = {(c["student"], c["order"]): c["value"] for c in cells}
    assert len(cells) == 4 and val == {("Ann", 0): 1, ("Ann", 1): 0, ("Bob", 0): None, ("Bob", 1): None}


def test_weekday_hour_counts():
    out = tr.weekday_hour_counts([s(2, 10, present=8, absent=2), s(9, 10, present=6, absent=4), s(3, 15)], UTC)
    mon = next(o for o in out if o["weekday"] == "Mon")
    assert mon["sessions"] == 2 and mon["percentage"] == 70.0 and mon["hour"] == 10 and len(out) == 2
