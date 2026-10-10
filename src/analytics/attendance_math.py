"""Pure attendance arithmetic (no I/O). Exact fractions avoid float edge cases at the target boundary."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor
from typing import Iterable

LOW, MEDIUM, HIGH, NO_DATA = "LOW", "MEDIUM", "HIGH", "NO_DATA"
ATTENDED = frozenset({"PRESENT", "LATE"})
COUNTED = frozenset({"PRESENT", "LATE", "ABSENT"})
DEFAULT_RISK_BUFFER = 5.0   # points above the target within which a subject is "medium" risk


def _t(target: float) -> Fraction:
    return Fraction(str(target)) / 100


def percentage(attended: int, conducted: int) -> float:
    return round(100.0 * attended / conducted, 1) if conducted else 0.0


def meets_target(attended: int, conducted: int, target: float) -> bool:
    return conducted > 0 and Fraction(attended, conducted) >= _t(target)


def classes_can_miss(attended: int, conducted: int, target: float) -> int:
    """Most upcoming classes that can be skipped while staying at/above *target* (0 if already below)."""
    if conducted <= 0 or not meets_target(attended, conducted, target):
        return 0
    return max(0, floor(Fraction(attended) / _t(target)) - conducted)


def classes_to_recover(attended: int, conducted: int, target: float) -> int | None:
    """Consecutive classes that must ALL be attended to reach *target*; 0 if already there; None if impossible."""
    if conducted <= 0 or meets_target(attended, conducted, target):
        return 0
    t = _t(target)
    if t >= 1:                      # a 100% target can never be recovered after a miss
        return None
    return max(0, ceil((t * conducted - attended) / (1 - t)))


@dataclass(frozen=True)
class Risk:
    level: str
    reasons: tuple[str, ...]


def assess_risk(attended: int, conducted: int, target: float, buffer: float = DEFAULT_RISK_BUFFER) -> Risk:
    """Transparent rule-based risk (a learned model arrives in Phase 9; this stays as its explainable baseline)."""
    if conducted <= 0:
        return Risk(NO_DATA, ("No classes have been recorded yet.",))
    pct = percentage(attended, conducted)
    if not meets_target(attended, conducted, target):
        need = classes_to_recover(attended, conducted, target)
        how = f"Attend the next {need} class{'es' if need != 1 else ''} in a row to recover." if need else "The target can no longer be reached."
        return Risk(HIGH, (f"Attendance {pct}% is below the {target:g}% target.", how))
    miss = classes_can_miss(attended, conducted, target)
    if miss <= 1 or pct < target + buffer:
        reason = "You cannot miss another class without dropping below target." if miss == 0 else f"Only {miss} more absence{'s' if miss != 1 else ''} allowed before dropping below target."
        return Risk(MEDIUM, (reason,))
    return Risk(LOW, (f"{miss} class{'es' if miss != 1 else ''} can be missed while staying above target.",))


def worst(levels: Iterable[str]) -> str:
    order = {NO_DATA: 0, LOW: 1, MEDIUM: 2, HIGH: 3}
    return max(levels, key=order.__getitem__, default=NO_DATA)


def current_streak(statuses_newest_first: Iterable[str]) -> int:
    """Consecutive attended classes counting back from the most recent. EXCUSED is skipped; an absence ends it."""
    streak = 0
    for status in statuses_newest_first:
        if status == "EXCUSED" or status not in COUNTED:
            continue
        if status in ATTENDED:
            streak += 1
        else:
            break
    return streak
