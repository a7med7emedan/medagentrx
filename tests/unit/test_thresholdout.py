# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import datetime as dt
import math
from pathlib import Path
from typing import Any

import pytest

from medagentrx import InputError
from medagentrx.checks import Finding, Status
from medagentrx.engine import evaluate
from medagentrx.guard import Guard, Validation
from medagentrx.ledger import LedgerError, build_entry, read_entries
from medagentrx.slack import STATISTICAL_CHECKS, Slack, aggregate, aggregate_against, slacks
from tests.helpers.cases import Case, make_case

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)


def _automatic(plan: dict[str, Any]) -> None:
    plan["modifications"][0]["automatic"] = True


def _validation(case: Case) -> Validation:
    return Validation(case.candidate, case.previous, case.anchor)


def _guard(case: Case, ledger: Path, seed: int = 1, **kwargs: Any) -> Guard:
    return Guard(
        case.plan,
        ledger,
        previous=case.previous,
        anchor=case.anchor,
        n_replicates=200,
        seed=seed,
        **kwargs,
    )


@pytest.fixture(scope="module")
def good(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("good"), plan_edit=_automatic)


@pytest.fixture(scope="module")
def good_validation(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("val"), plan_edit=_automatic, seed=11, n=3000)


@pytest.fixture(scope="module")
def miscalibrated(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("bad"), plan_edit=_automatic, candidate_scale=0.6)


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"candidate_scale": 0.6}, {"harm_site": "B"}, {"candidate_noise": 1.5}],
    ids=["good", "miscalibrated", "subgroup-harm", "worse"],
)
def test_aggregate_slack_matches_the_statistical_checks(
    tmp_path: Path, kwargs: dict[str, Any]
) -> None:
    evaluation = evaluate(**make_case(tmp_path, **kwargs).kwargs(), n_replicates=200, now=NOW)
    failed = [c for c in evaluation.failed_checks if c in STATISTICAL_CHECKS]
    found = slacks(evaluation.findings)
    assert {key.split(":")[0] for key in found} >= {"PERF-001", "PERF-003", "PERF-005", "LIFE-001"}
    assert (aggregate(found) > 0) == (not failed)
    for key, value in found.items():
        check = key.split(":")[0]
        if check not in failed:
            assert value.z() >= 0, key
    assert aggregate_against(found, found) == pytest.approx(aggregate(found))


def test_slack_edge_cases() -> None:
    assert Slack(0.1, 0.0, 1.0, True).z() == math.inf
    assert Slack(-0.1, 0.0, 1.0, False).z() == -math.inf
    assert Slack(-math.inf, 1.0, 0.0, False).z() == -math.inf
    assert Slack(1.0, 1.0, 1.0, False).z() < 0
    assert Slack(0.999, 1.0, 1.0, True).z() == 0
    assert Slack(0.3, 0.1, 1.645, True).scaled(0.2) == pytest.approx(1.5 - 1.645)
    assert aggregate({}) == math.inf
    holdout = {"a": Slack(0.3, 0.1, 1.0, True), "b": Slack(0.3, 0.0, 1.0, True)}
    assert aggregate_against({}, holdout) == -math.inf
    validation = {"a": Slack(0.2, 0.5, 1.0, False), "b": Slack(0.2, 0.5, 1.0, True)}
    assert aggregate_against(validation, holdout) == 0.0
    validation = {"a": Slack(0.2, 0.5, 1.0, False), "b": Slack(0.2, 0.5, 1.0, False)}
    assert aggregate_against(validation, holdout) == pytest.approx(-0.6)
    assert aggregate_against({"a": Slack(0.2, 0.5, 1.0, False)}, {"a": holdout["a"]}) == 1.0
    failed_fit = Finding("PERF-003", Status.FAIL, "Calibration cannot be estimated")
    assert slacks([failed_fit])["PERF-003:fit"].z() == -math.inf
    skipped = Finding("PERF-001", Status.SKIPPED, "Not assessed")
    assert slacks([skipped, Finding("DATA-001", Status.FAIL, "x")]) == {}


def test_insufficient_subgroups_count_only_when_they_fail() -> None:
    details = {
        "max_drop": 0.03,
        "subgroups": [{"column": "site", "level": "A", "status": "insufficient"}],
    }
    assert slacks([Finding("PERF-005", Status.WARN, "x", details)]) == {}
    failing = slacks([Finding("PERF-005", Status.FAIL, "x", details)])
    assert failing["PERF-005:site=A"].z() == -math.inf


def test_agreeing_validation_answers_without_the_test_set(
    good: Case, good_validation: Case, tmp_path: Path
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    guard = _guard(good, ledger, threshold=50.0)
    decision = guard.submit(
        good.candidate,
        good.model_meta,
        manifest=good.manifest,
        validation=_validation(good_validation),
        now=NOW,
    )
    assert decision.allowed
    assert decision.looks_used == 1
    assert read_entries(ledger)[0]["answer"] == {
        "mode": "thresholdout",
        "allowed": True,
        "source": "validation",
    }


def test_disagreeing_validation_falls_back_to_the_test_set(
    miscalibrated: Case, good_validation: Case, tmp_path: Path
) -> None:
    for seed in range(8):
        ledger = tmp_path / f"l{seed}.jsonl"
        decision = _guard(miscalibrated, ledger, seed=seed).submit(
            miscalibrated.candidate,
            miscalibrated.model_meta,
            manifest=miscalibrated.manifest,
            validation=_validation(good_validation),
            now=NOW,
        )
        assert not decision.allowed
        assert read_entries(ledger)[0]["answer"]["source"] == "holdout"


def test_answers_without_validation_come_from_the_test_set(good: Case, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _guard(good, ledger).submit(good.candidate, good.model_meta, manifest=good.manifest, now=NOW)
    assert read_entries(ledger)[0]["answer"]["source"] == "holdout"


def test_failures_that_do_not_use_labels_are_exact(
    good: Case, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from medagentrx.checks import doc_checks
    from medagentrx.errors import StatsError

    def broken(*_: object, **__: object) -> None:
        raise StatsError("outcomes are perfectly separated")

    monkeypatch.setattr(doc_checks, "calibration", broken)
    ledger = tmp_path / "ledger.jsonl"
    decision = _guard(good, ledger).submit(
        good.candidate, good.model_meta, manifest=good.manifest, now=NOW
    )
    assert not decision.allowed
    assert decision.failed_checks == ("DOC-001",)
    assert read_entries(ledger)[0]["answer"]["source"] == "exact"


def test_validation_files_must_share_rows(
    good: Case, good_validation: Case, tmp_path: Path
) -> None:
    mixed = Validation(good_validation.candidate, good.previous)
    with pytest.raises(InputError, match="validation predictions of the previous version"):
        _guard(good, tmp_path / "ledger.jsonl").submit(
            good.candidate, good.model_meta, manifest=good.manifest, validation=mixed, now=NOW
        )


def test_threshold_must_not_be_negative(good: Case, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="threshold"):
        Guard(good.plan, tmp_path / "l.jsonl", previous=good.previous, threshold=-1.0)


def test_only_guard_entries_record_an_answer(good: Case) -> None:
    evaluation = evaluate(**good.kwargs(), n_replicates=200, now=NOW)
    with pytest.raises(LedgerError, match="only guard entries"):
        build_entry(evaluation, seq=0, prev_hash="0" * 64, answer={"allowed": True})
