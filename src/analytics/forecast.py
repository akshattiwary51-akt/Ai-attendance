"""Interpretable attendance forecast (pure Python, no ML library).

Model (Bayesian, deliberately simple):
  * each counted class is attended (1) or missed (0); EXCUSED classes are skipped by the caller;
  * the student's attendance propensity p ~ Beta(a, b): a weak prior (mean PRIOR_MEAN, strength PRIOR_STRENGTH) updated with
    the history, where older classes are down-weighted exponentially (HALF_LIFE classes) so recent behaviour counts more;
  * the number attended in the next n classes is Beta-Binomial(n, a, b), which carries the uncertainty about p;
  * P(below target) = P(final percentage < target), computed exactly from that distribution; expected percentage and an 80% interval
    come from the same distribution. n comes from the subject's own class frequency.
It is a transparent heuristic, not a validated predictor: `backtest` measures its calibration on your own history (Brier score).
Fewer than 5 counted classes => confidence "low" and the number should be read as a rough guide."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import ceil, exp, lgamma, log
from statistics import median
from typing import Sequence

from src.analytics import attendance_math as am

PRIOR_MEAN, PRIOR_STRENGTH = 0.8, 2.0
HALF_LIFE = 8.0                 # classes after which an observation counts half as much
DEFAULT_HORIZON_DAYS = 30
FALLBACK_CLASSES = 4            # assumed classes in the horizon when the subject has too few sessions to estimate its frequency
MAX_FUTURE = 60
LOW_RISK_BELOW, HIGH_RISK_FROM = 0.20, 0.50   # probability bands


@dataclass(frozen=True)
class Forecast:
    attended: int
    conducted: int
    target: float
    current_pct: float
    n_future: int
    future_assumed: bool          # n_future is a default, not estimated from the subject's schedule
    p_attend: float               # posterior mean propensity to attend a future class
    expected_pct: float
    interval_pct: tuple[float, float]   # 80% interval for the final percentage
    prob_below_target: float
    must_attend: int | None       # fewest of the next n classes to attend to finish at/above target (None = unreachable)
    risk: str                     # LOW | MEDIUM | HIGH | NO_DATA
    confidence: str               # low | medium | high (amount of history)
    consecutive_absences: int
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _logbeta(a: float, b: float) -> float:
    return lgamma(a) + lgamma(b) - lgamma(a + b)


def betabinom_pmf(n: int, a: float, b: float) -> list[float]:
    """P(X = k) for k = 0..n, X ~ BetaBinomial(n, a, b)."""
    out = []
    for k in range(n + 1):
        lc = lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
        out.append(exp(lc + _logbeta(k + a, n - k + b) - _logbeta(a, b)))
    s = sum(out)
    return [x / s for x in out]


def posterior(history: Sequence[int], half_life: float = HALF_LIFE) -> tuple[float, float]:
    """Beta(a, b) after recency-weighted updating with the 0/1 history (oldest first)."""
    n = len(history)
    s = f = 0.0
    for i, x in enumerate(history):
        w = 0.5 ** ((n - 1 - i) / half_life)
        s += w * x
        f += w * (1 - x)
    return PRIOR_STRENGTH * PRIOR_MEAN + s, PRIOR_STRENGTH * (1 - PRIOR_MEAN) + f


def classes_in_horizon(session_times: Sequence[float], horizon_days: int = DEFAULT_HORIZON_DAYS) -> tuple[int, bool]:
    """(expected number of classes in the horizon, assumed?) from session timestamps (epoch seconds) of the subject."""
    ts = sorted(session_times)
    if len(ts) < 3:
        return FALLBACK_CLASSES, True
    gaps = [(b - a) / 86400 for a, b in zip(ts, ts[1:]) if b > a]
    if not gaps:
        return FALLBACK_CLASSES, True
    gap = max(median(gaps), 0.5)          # sessions closer than 12 h are one lecture day
    return int(max(1, min(MAX_FUTURE, round(horizon_days / gap)))), False


def consecutive_absences(history: Sequence[int]) -> int:
    n = 0
    for x in reversed(history):
        if x:
            break
        n += 1
    return n


def _confidence(n: int) -> str:
    return "low" if n < 5 else "medium" if n < 12 else "high"


def forecast(history: Sequence[int], target: float, n_future: int, future_assumed: bool = False) -> Forecast:
    """history: 0/1 per counted class, oldest first."""
    hist = [1 if x else 0 for x in history]
    A, C = sum(hist), len(hist)
    cur = am.percentage(A, C)
    if C == 0:
        return Forecast(0, 0, target, 0.0, n_future, future_assumed, PRIOR_MEAN, 0.0, (0.0, 0.0), 0.0, None, am.NO_DATA, "low", 0,
                        ("No classes have been recorded yet.",))
    a, b = posterior(hist)
    pmf = betabinom_pmf(n_future, a, b)
    total = C + n_future
    # smallest X with (A + X) / total >= target%, exactly
    need = Fraction(str(target)) * total / 100 - A
    x_min = max(0, ceil(need))
    must = x_min if x_min <= n_future else None
    p_below = float(sum(pmf[:x_min])) if x_min <= n_future else 1.0
    p = a / (a + b)
    expected = 100.0 * (A + n_future * p) / total
    cdf, lo, hi = 0.0, 0, n_future
    lo_set = False
    for k, pk in enumerate(pmf):
        cdf += pk
        if not lo_set and cdf >= 0.10:
            lo, lo_set = k, True
        if cdf >= 0.90:
            hi = k
            break
    interval = (round(100.0 * (A + lo) / total, 1), round(100.0 * (A + hi) / total, 1))
    risk = am.HIGH if p_below >= HIGH_RISK_FROM else am.MEDIUM if p_below >= LOW_RISK_BELOW else am.LOW
    run = consecutive_absences(hist)
    recent = hist[-5:]
    recent_rate = 100.0 * sum(recent) / len(recent)
    reasons: list[str] = []
    if cur < target:
        reasons.append(f"Attendance is {cur:g}%, below the {target:g}% target.")
    if run >= 2:
        reasons.append(f"{run} classes missed in a row.")
    if C >= 6 and recent_rate <= cur - 15:
        reasons.append(f"Recent attendance ({recent_rate:.0f}% over the last {len(recent)}) is well below the overall {cur:g}%: a declining trend.")
    elif C >= 6 and recent_rate >= cur + 15:
        reasons.append(f"Recent attendance ({recent_rate:.0f}% over the last {len(recent)}) is above the overall {cur:g}%: improving.")
    if must is None:
        reasons.append(f"Even attending all of the next {n_future} classes would not reach {target:g}%.")
    elif must > 0 and n_future:
        reasons.append(f"To finish the period at {target:g}% you need to attend at least {must} of the next {n_future} classes.")
    elif n_future:
        reasons.append(f"You would stay at or above {target:g}% even if you missed the next {n_future} classes.")
    if future_assumed:
        reasons.append(f"The subject has too few classes to estimate its schedule; {n_future} classes in the period were assumed.")
    if C < 5:
        reasons.append(f"Only {C} class{'es' if C != 1 else ''} recorded: treat this as a rough guide.")
    return Forecast(A, C, target, cur, n_future, future_assumed, round(p, 3), round(expected, 1), interval, round(p_below, 3), must,
                    risk, _confidence(C), run, tuple(reasons))


# ───────────────────────── backtest ─────────────────────────
@dataclass(frozen=True)
class Backtest:
    n: int
    brier: float                 # mean squared error of prob_below_target vs what happened (lower is better)
    baseline_brier: float        # always predicting the overall prevalence of "below target"
    prevalence: float
    bins: list[tuple[float, float, int]]   # (mean predicted, observed frequency, count) per probability decile band


def backtest(histories: Sequence[Sequence[int]], target: float, n_future: int, min_history: int = 5) -> Backtest:
    """Rolling-origin evaluation: forecast from the first c classes, then check the end-of-period percentage over the next n_future
    classes. Only cuts with n_future classes still to come are used. Use on your own data to see whether the numbers deserve trust."""
    preds, actual = [], []
    for h in histories:
        for c in range(min_history, len(h) - n_future + 1):
            f = forecast(h[:c], target, n_future)
            final = (sum(h[: c + n_future])) / (c + n_future) * 100
            preds.append(f.prob_below_target)
            actual.append(1.0 if final < target else 0.0)
    if not preds:
        return Backtest(0, 0.0, 0.0, 0.0, [])
    n = len(preds)
    prev = sum(actual) / n
    brier = sum((p - y) ** 2 for p, y in zip(preds, actual)) / n
    base = sum((prev - y) ** 2 for y in actual) / n
    bins = []
    for lo in [i / 5 for i in range(5)]:
        sel = [(p, y) for p, y in zip(preds, actual) if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
        if sel:
            bins.append((round(sum(p for p, _ in sel) / len(sel), 3), round(sum(y for _, y in sel) / len(sel), 3), len(sel)))
    return Backtest(n, round(brier, 4), round(base, 4), round(prev, 3), bins)
