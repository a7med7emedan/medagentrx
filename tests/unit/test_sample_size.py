# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from medagentrx.cli import app
from medagentrx.errors import StatsError
from medagentrx.stats.power import analytic_power, required_test_size

runner = CliRunner()
EXAMPLE = Path("examples/sepsis-risk/change-plan.yaml")
ARGS: dict[str, Any] = {
    "auc": 0.8,
    "prevalence": 0.12,
    "margin": 0.02,
    "alpha": 0.025,
    "power": 0.8,
    "correlation": 0.6,
}


def _power(n: int, n_pos: int) -> float:
    return analytic_power(
        auc=0.8, n_pos=n_pos, n_neg=n - n_pos, margin=0.02, alpha=0.025, correlation=0.6
    )


def test_smallest_size_that_reaches_the_power() -> None:
    size = required_test_size(**ARGS)
    assert size.n_pos + size.n_neg == size.n
    assert size.n_pos == round(0.12 * size.n)
    assert size.power >= 0.8
    smaller = size.n - 1
    assert _power(smaller, round(0.12 * smaller)) < 0.8


def test_size_grows_as_the_question_gets_harder() -> None:
    base = required_test_size(**ARGS).n
    assert required_test_size(**{**ARGS, "margin": 0.01}).n > 3 * base
    assert required_test_size(**{**ARGS, "power": 0.9}).n > base
    assert required_test_size(**{**ARGS, "correlation": 0.8}).n < base
    assert required_test_size(**{**ARGS, "true_difference": 0.01}).n < base
    assert required_test_size(**{**ARGS, "prevalence": 0.05}).n > base


def test_tiny_requirements() -> None:
    assert required_test_size(**{**ARGS, "margin": 0.6, "power": 0.06}).n == 2


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"prevalence": 0.0}, "prevalence"),
        ({"power": 0.01}, "power"),
        ({"power": 1.0}, "power"),
        ({"true_difference": -0.03}, "true difference"),
        ({"alpha": 0.0}, "alpha"),
        ({"margin": 0.0001, "max_rows": 1000}, "not reached"),
    ],
)
def test_invalid_requests(change: dict[str, Any], message: str) -> None:
    with pytest.raises(StatsError, match=message):
        required_test_size(**{**ARGS, **change})


def test_cli_reads_the_plan() -> None:
    result = runner.invoke(
        app, ["sample-size", str(EXAMPLE), "--auroc", "0.8", "--prevalence", "0.12"]
    )
    assert result.exit_code == 0, result.output
    assert (
        "Locked test set: at least 15,088 rows (1,811 positives, 13,277 negatives)" in result.output
    )
    assert "one-sided level 0.004167" in result.output
    assert "at least 30 positives and 30 negatives" in result.output


def test_cli_options_override_the_plan() -> None:
    result = runner.invoke(
        app,
        [
            "sample-size",
            str(EXAMPLE),
            "--margin",
            "0.02",
            "--alpha",
            "0.025",
            "--power",
            "0.8",
            "--prevalence",
            "0.12",
        ],
    )
    assert result.exit_code == 0
    assert f"{required_test_size(**ARGS).n:,} rows" in result.output


def test_cli_needs_a_margin_and_a_level() -> None:
    result = runner.invoke(app, ["sample-size", "--margin", "0.02"])
    assert result.exit_code == 3
    assert "--margin and --alpha" in result.output


def test_cli_reports_impossible_requests() -> None:
    result = runner.invoke(
        app, ["sample-size", "--margin", "0.02", "--alpha", "0.025", "--prevalence", "1.5"]
    )
    assert result.exit_code == 3
    assert "prevalence" in result.output
