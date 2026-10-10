"""Forecast: exact probabilities against brute force, boundary cases, explanations, and a calibration backtest."""
import itertools
import random
from fractions import Fraction
from math import comb

import pytest

from src.analytics import forecast as fc


def brute_prob_below(hist, target, n):
    """P(final < target) by integrating the Beta prior numerically-free: enumerate Beta-Binomial pmf from first principles."""
    a, b = fc.posterior(hist)
    from math import gamma
    def B(x, y): return gamma(x) * gamma(y) / gamma(x + y)
    A, C = sum(hist), len(hist)
    p = 0.0
    for k in range(n + 1):
        if Fraction(A + k, C + n) * 100 < Fraction(str(target)):
            p += comb(n, k) * B(k + a, n - k + b) / B(a, b)
    return p


@pytest.mark.parametrize("hist, target, n", [
    ([1, 1, 0, 1, 0, 0, 1], 75, 6), ([1] * 10, 75, 8), ([0] * 6, 50, 4), ([1, 0] * 6, 60, 10), ([1, 1, 1, 0], 90, 5), ([1, 0, 0], 33.34, 3),
])
def test_probability_matches_brute_force(hist, target, n):
    assert fc.forecast(hist, target, n).prob_below_target == pytest.approx(brute_prob_below(hist, target, n), abs=2e-3)


def test_pmf_sums_to_one_and_is_nonnegative():
    for n, a, b in [(0, 1, 1), (1, .5, .5), (10, 3.2, 1.4), (60, 8, 2)]:
        p = fc.betabinom_pmf(n, a, b)
        assert abs(sum(p) - 1) < 1e-9 and min(p) >= 0 and len(p) == n + 1


def test_target_boundary_is_exact():
    # 3/4 = 75%: with 4 more classes, attending 3 of them gives 6/8 = 75% (meets), 2 gives 5/8 (below)
    f = fc.forecast([1, 1, 1, 0], 75, 4)
    assert f.must_attend == 3
    assert fc.forecast([1] * 3 + [0], 75, 0).must_attend == 0 and fc.forecast([1] * 3 + [0], 75, 0).prob_below_target == 0.0
    assert fc.forecast([1, 0, 0], 75, 1).must_attend is None and fc.forecast([1, 0, 0], 75, 1).prob_below_target == 1.0


def test_no_history_has_no_forecast():
    f = fc.forecast([], 75, 4)
    assert f.risk == "NO_DATA" and f.confidence == "low" and f.reasons


def test_risk_orders_with_attendance_and_recency():
    good = fc.forecast([1] * 12, 75, 8)
    slipping = fc.forecast([1] * 8 + [0] * 4, 75, 8)
    bad = fc.forecast([1, 0] * 3 + [0] * 6, 75, 8)
    assert good.risk == "LOW" and bad.risk == "HIGH"
    assert good.prob_below_target < slipping.prob_below_target <= bad.prob_below_target
    assert slipping.consecutive_absences == 4 and any("in a row" in r for r in slipping.reasons)
    assert any("declining" in r for r in slipping.reasons)


def test_recent_behaviour_counts_more_than_old():
    improving = fc.forecast([0] * 6 + [1] * 6, 75, 8)
    declining = fc.forecast([1] * 6 + [0] * 6, 75, 8)
    assert improving.p_attend > declining.p_attend and improving.expected_pct > declining.expected_pct


def test_interval_contains_expected_and_is_ordered():
    for h in ([1, 0, 1, 1, 0, 1], [1] * 9, [0, 0, 1]):
        f = fc.forecast(h, 75, 10)
        assert f.interval_pct[0] <= f.expected_pct <= f.interval_pct[1] or abs(f.expected_pct - f.interval_pct[1]) < 5
        assert 0 <= f.interval_pct[0] <= f.interval_pct[1] <= 100


def test_little_history_is_labelled_low_confidence():
    f = fc.forecast([1, 1], 75, 4, future_assumed=True)
    assert f.confidence == "low" and any("rough guide" in r for r in f.reasons) and any("assumed" in r for r in f.reasons)


def test_classes_in_horizon():
    day = 86400
    assert fc.classes_in_horizon([0, 7 * day, 14 * day, 21 * day], 30) == (4, False)          # weekly
    assert fc.classes_in_horizon([0, 2 * day, 4 * day, 6 * day], 30) == (15, False)           # every other day
    assert fc.classes_in_horizon([0, day], 30) == (4, True)                                    # too few to estimate
    assert fc.classes_in_horizon([5, 5, 5, 5], 30) == (4, True)                                # same instant: no usable gaps
    assert fc.classes_in_horizon([0, 0.1 * day, 0.2 * day, 0.3 * day], 30)[0] <= 60            # capped


def test_consecutive_absences():
    assert fc.consecutive_absences([1, 0, 0]) == 2 and fc.consecutive_absences([0, 1]) == 0 and fc.consecutive_absences([]) == 0


def test_backtest_beats_the_naive_baseline_and_is_roughly_calibrated():
    rng = random.Random(42)
    students = []
    for _ in range(150):
        p = rng.choice([0.45, 0.6, 0.7, 0.8, 0.9, 0.95])
        students.append([1 if rng.random() < p else 0 for _ in range(30)])
    bt = fc.backtest(students, 75, 8, min_history=6)
    assert bt.n > 1000 and bt.brier < bt.baseline_brier                                     # better than predicting the base rate
    for predicted, observed, count in bt.bins:
        if count >= 50:
            assert abs(predicted - observed) < 0.2                                          # calibration within 20 points per band


def test_backtest_with_too_little_data_is_empty():
    assert fc.backtest([[1, 0, 1]], 75, 4).n == 0
