# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import math

import pytest

from medagentrx.errors import StatsError
from medagentrx.stats.multirule import (
    REJECTION_RULES,
    estimate_baseline,
    evaluate_rules,
    given_baseline,
    standardise,
)

ALL = ("1_2s", "1_3s", "2_2s", "R_4s", "10_x")
EPS = 1e-9


def fired(z: list[float], rules: tuple[str, ...] = ALL) -> set[str]:
    outcome = evaluate_rules(z, rules)
    return {*outcome.rejections, *outcome.warnings}


@pytest.mark.parametrize(("z", "expected"), [(2.0, set()), (-2.0, set()), (2.0 + EPS, {"1_2s"})])
def test_1_2s_boundary(z: float, expected: set[str]) -> None:
    assert fired([z]) == expected


def test_1_2s_only_warns() -> None:
    outcome = evaluate_rules([-2.5], ALL)
    assert outcome.warnings == ("1_2s",)
    assert outcome.rejections == ()
    assert outcome.in_control


@pytest.mark.parametrize(
    ("z", "expected"),
    [(3.0, {"1_2s"}), (-3.0, {"1_2s"}), (3.0 + EPS, {"1_2s", "1_3s"}), (-3.5, {"1_2s", "1_3s"})],
)
def test_1_3s_boundary(z: float, expected: set[str]) -> None:
    assert fired([z]) == expected
    assert evaluate_rules([z], ALL).in_control is ("1_3s" not in expected)


@pytest.mark.parametrize(
    ("previous", "latest", "rejects"),
    [
        (2.1, 2.1, True),
        (-2.1, -2.5, True),
        (2.0, 2.1, False),
        (2.1, 2.0, False),
        (2.1, -2.1, False),
    ],
)
def test_2_2s(previous: float, latest: float, rejects: bool) -> None:
    assert ("2_2s" in fired([previous, latest])) is rejects


@pytest.mark.parametrize(
    ("previous", "latest", "rejects"),
    [
        (2.1, -2.1, True),
        (-2.5, 2.2, True),
        (2.0, -2.1, False),
        (2.1, -2.0, False),
        (2.5, 2.5, False),
    ],
)
def test_r_4s(previous: float, latest: float, rejects: bool) -> None:
    assert ("R_4s" in fired([previous, latest])) is rejects


def test_10_x() -> None:
    assert "10_x" in fired([0.1] * 10)
    assert "10_x" in fired([-0.1] * 10)
    assert "10_x" in fired([-3.0, *[0.2] * 10])
    assert "10_x" not in fired([0.1] * 9)
    assert "10_x" not in fired([0.1] * 9 + [0.0])
    assert "10_x" not in fired([0.1] * 9 + [-0.1])


def test_rules_apply_only_when_listed() -> None:
    assert fired([3.5], ("1_2s",)) == {"1_2s"}
    assert fired([3.5], ("10_x",)) == set()
    assert fired([0.1] * 10, ("1_3s", "2_2s")) == set()
    assert set(REJECTION_RULES) == {"1_3s", "2_2s", "R_4s", "10_x"}


def test_rule_errors() -> None:
    with pytest.raises(StatsError, match="at least one run"):
        evaluate_rules([], ALL)
    with pytest.raises(StatsError, match="unknown QC rule"):
        evaluate_rules([0.0], ("4_1s",))


def test_given_baseline() -> None:
    baseline = given_baseline(0.5)
    assert (baseline.mean, baseline.sd, baseline.runs, baseline.floored) == (0.0, 0.5, 0, False)
    assert standardise([1.0, -0.5], baseline) == (2.0, -1.0)
    for bad in (0.0, -1.0, math.inf, math.nan):
        with pytest.raises(StatsError, match="sd must be positive"):
            given_baseline(bad)


def test_estimated_baseline_and_floor() -> None:
    baseline = estimate_baseline([1.0, 2.0, 3.0], floor=0.1)
    assert baseline.mean == pytest.approx(2.0)
    assert baseline.sd == pytest.approx(1.0)
    assert baseline.estimated_sd == pytest.approx(1.0)
    assert not baseline.floored
    assert baseline.runs == 3
    flat = estimate_baseline([5e-9] * 20, floor=1e-8)
    assert flat.sd == 1e-8
    assert flat.estimated_sd == pytest.approx(0.0)
    assert flat.floored
    assert standardise([5e-9], flat)[0] == pytest.approx(0.0)
    with pytest.raises(StatsError, match="at least two"):
        estimate_baseline([1.0], floor=0.1)
    with pytest.raises(StatsError, match="floor must be positive"):
        estimate_baseline([1.0, 2.0], floor=0.0)
