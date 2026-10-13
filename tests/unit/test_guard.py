# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from medagentrx.engine import Verdict, evaluate
from medagentrx.guard import Guard
from medagentrx.ledger import append, load_history, read_entries, verify
from tests.helpers.cases import Case, make_case

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)


def _automatic(plan: dict[str, Any]) -> None:
    plan["modifications"][0]["automatic"] = True


def _guard(case: Case, ledger: Path, mode: Any = "thresholdout", **kwargs: Any) -> Guard:
    return Guard(
        case.plan,
        ledger,
        mode,
        previous=case.previous,
        anchor=case.anchor,
        n_replicates=200,
        seed=1,
        **kwargs,
    )


def _submit(guard: Guard, case: Case, hours: int = 0) -> Any:
    return guard.submit(
        case.candidate, case.model_meta, manifest=case.manifest, now=NOW + dt.timedelta(hours=hours)
    )


@pytest.fixture(scope="module")
def agent_case(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("agent"), plan_edit=_automatic)


def test_allowed_modifications(agent_case: Case, tmp_path: Path) -> None:
    guard = _guard(agent_case, tmp_path / "ledger.jsonl")
    assert [m.id for m in guard.allowed_modifications()] == ["M1"]


def test_manual_modification_is_refused_before_any_data(tmp_path: Path) -> None:
    case = make_case(tmp_path / "c")
    ledger = tmp_path / "ledger.jsonl"
    guard = _guard(case, ledger)
    assert guard.allowed_modifications() == []
    decision = _submit(guard, case)
    assert not decision.allowed
    assert decision.failed_checks == ("PLAN-002",)
    assert decision.looks_used == 0
    entry = read_entries(ledger)[0]
    assert entry["kind"] == "guard"
    assert entry["touched_test_set"] is False
    assert entry["inputs"] == {}
    assert verify(ledger).ok


def test_thresholdout_answers_hide_metrics(agent_case: Case, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    decision = _submit(_guard(agent_case, ledger), agent_case)
    assert decision.allowed
    assert decision.verdict is None
    assert decision.failed_checks == ()
    assert decision.reason == "Passes the plan's criteria (noisy answer)"
    assert (decision.looks_used, decision.looks_remaining) == (1, 19)
    entry = read_entries(ledger)[0]
    assert entry["kind"] == "guard"
    assert entry["metrics"] == {}
    assert entry["alpha"]["used"] is None
    assert entry["verdict"] == "ACCEPTED"


def test_guard_looks_spend_no_alpha_and_release_nothing(agent_case: Case, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    guard = _guard(agent_case, ledger)
    for hour in range(3):
        _submit(guard, agent_case, hour)
    history = load_history(ledger)
    assert history.looks_used == 3
    assert history.releases == ()
    assert history.alpha is not None
    assert history.alpha.spent == 0.0
    later = NOW + dt.timedelta(hours=3)
    formal = evaluate(**agent_case.kwargs(), history=history, n_replicates=200, now=later)
    assert formal.verdict is Verdict.ACCEPTED
    assert formal.finding("DATA-004").details["this_look"] == 4
    append(ledger, formal)
    assert len(load_history(ledger).releases) == 1


def test_exact_mode_reports_failures(tmp_path: Path) -> None:
    case = make_case(tmp_path / "c", plan_edit=_automatic, candidate_scale=0.6)
    decision = _submit(_guard(case, tmp_path / "ledger.jsonl", "exact"), case)
    assert not decision.allowed
    assert decision.verdict is Verdict.FAILED
    assert "PERF-003" in decision.failed_checks
    assert decision.reason.startswith("Fails: ")


def test_exact_mode_accepts(agent_case: Case, tmp_path: Path) -> None:
    decision = _submit(_guard(agent_case, tmp_path / "ledger.jsonl", "exact"), agent_case)
    assert decision.allowed
    assert decision.verdict is Verdict.ACCEPTED
    assert decision.reason == "Meets the plan's criteria"


def test_thresholdout_fails_on_other_criteria(tmp_path: Path) -> None:
    case = make_case(tmp_path / "c", plan_edit=_automatic, candidate_scale=0.6)
    for seed in range(5):
        guard = Guard(
            case.plan,
            tmp_path / f"l{seed}.jsonl",
            previous=case.previous,
            n_replicates=200,
            seed=seed,
        )
        assert not _submit(guard, case).allowed


def test_thresholdout_noise_on_a_borderline_candidate(tmp_path: Path) -> None:
    def tight(plan: dict[str, Any]) -> None:
        _automatic(plan)
        plan["performance"]["criteria"] = [plan["performance"]["criteria"][0]]
        plan["performance"]["criteria"][0]["margin"] = 0.0
        plan["performance"]["criteria"][0]["vs"] = ["previous"]
        plan["performance"]["cumulative_drift"]["max_drop_vs_anchor"] = 0.5
        plan["performance"].pop("subgroups")
        plan["data_management"]["locked_test_set"]["max_evaluations"] = 100

    case = make_case(tmp_path / "c", plan_edit=tight, previous_noise=0.0, candidate_noise=0.05)
    answers = set()
    for seed in range(12):
        guard = Guard(
            case.plan,
            tmp_path / f"l{seed}.jsonl",
            previous=case.previous,
            n_replicates=200,
            seed=seed,
            noise_scale=3.0,
        )
        answers.add(_submit(guard, case).allowed)
    assert answers == {True, False}


def test_outside_plan_answers_name_the_check(agent_case: Case, tmp_path: Path) -> None:
    def small(plan: dict[str, Any]) -> None:
        _automatic(plan)
        plan["data_management"]["locked_test_set"]["max_evaluations"] = 1

    case = make_case(tmp_path / "c", plan_edit=small)
    guard = _guard(case, tmp_path / "ledger.jsonl")
    assert _submit(guard, case, 0).looks_remaining == 0
    refused = _submit(guard, case, 1)
    assert not refused.allowed
    assert refused.reason == "Refused: outside the plan (DATA-004)"
    assert refused.verdict is None
    exact = _guard(case, tmp_path / "ledger.jsonl", "exact")
    assert _submit(exact, case, 2).verdict is Verdict.OUTSIDE_PLAN


def test_guard_arguments(agent_case: Case, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        Guard(agent_case.plan, tmp_path / "l.jsonl", "loose", previous=agent_case.previous)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="noise_scale"):
        Guard(agent_case.plan, tmp_path / "l.jsonl", previous=agent_case.previous, noise_scale=0)
    guard = Guard(agent_case.plan, tmp_path / "l.jsonl", previous=agent_case.previous)
    assert guard.anchor == guard.previous
