import pytest

from src.analytics import attendance_math as m


def test_percentage():
    assert m.percentage(0, 0) == 0.0 and m.percentage(3, 4) == 75.0 and m.percentage(2, 3) == 66.7


def test_known_examples():
    assert m.classes_can_miss(15, 20, 75) == 0
    assert m.classes_can_miss(18, 20, 75) == 4
    assert m.classes_can_miss(10, 10, 75) == 3
    assert m.classes_to_recover(10, 20, 75) == 20
    assert m.classes_to_recover(15, 20, 75) == 0
    assert m.classes_to_recover(0, 4, 75) == 12
    assert m.classes_to_recover(1, 2, 75) == 2
    assert m.classes_can_miss(20, 20, 75) == 6


def test_boundary_is_exact_not_float_fuzzy():
    assert m.meets_target(3, 4, 75) and not m.meets_target(299, 400, 75)
    assert m.meets_target(33, 100, 33.0) is True
    assert m.classes_can_miss(7, 10, 70) == 0 and m.classes_can_miss(14, 20, 70) == 0 and m.classes_can_miss(15, 20, 70) == 1


def test_can_miss_and_recover_match_brute_force():
    for target in (50, 60, 66.7, 75, 80, 85, 90):
        for conducted in range(0, 31):
            for attended in range(0, conducted + 1):
                expected_miss = 0
                if m.meets_target(attended, conducted, target):
                    while m.meets_target(attended, conducted + expected_miss + 1, target):
                        expected_miss += 1
                assert m.classes_can_miss(attended, conducted, target) == expected_miss, (attended, conducted, target)
                need = m.classes_to_recover(attended, conducted, target)
                n = 0
                while conducted and not m.meets_target(attended + n, conducted + n, target) and n < 5000:
                    n += 1
                assert need == n, (attended, conducted, target)


def test_hundred_percent_target():
    assert m.classes_can_miss(10, 10, 100) == 0 and m.classes_to_recover(10, 10, 100) == 0
    assert m.classes_to_recover(9, 10, 100) is None


def test_no_classes_yet():
    assert m.classes_can_miss(0, 0, 75) == 0 and m.classes_to_recover(0, 0, 75) == 0
    assert m.assess_risk(0, 0, 75).level == m.NO_DATA


@pytest.mark.parametrize("attended,conducted,level", [(10, 20, m.HIGH), (15, 20, m.MEDIUM), (16, 20, m.MEDIUM), (20, 20, m.LOW), (19, 20, m.LOW)])
def test_risk_levels(attended, conducted, level):
    assert m.assess_risk(attended, conducted, 75).level == level


def test_risk_explains_why():
    high = m.assess_risk(10, 20, 75)
    assert "below the 75% target" in high.reasons[0] and "next 20 classes" in high.reasons[1]
    assert "cannot miss another" in m.assess_risk(15, 20, 75).reasons[0]
    assert "can be missed" in m.assess_risk(20, 20, 75).reasons[0]
    assert "no longer be reached" in m.assess_risk(9, 10, 100).reasons[1]


def test_worst_level():
    assert m.worst([m.LOW, m.HIGH, m.MEDIUM]) == m.HIGH and m.worst([m.NO_DATA, m.LOW]) == m.LOW and m.worst([]) == m.NO_DATA


@pytest.mark.parametrize("statuses,streak", [
    (["PRESENT", "LATE", "ABSENT", "PRESENT"], 2), (["ABSENT", "PRESENT"], 0), ([], 0),
    (["PRESENT", "EXCUSED", "PRESENT", "ABSENT"], 2), (["UNKNOWN", "PRESENT"], 1), (["EXCUSED"], 0),
])
def test_streak(statuses, streak):
    assert m.current_streak(statuses) == streak
