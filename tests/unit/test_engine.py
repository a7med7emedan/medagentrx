# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from medagentrx.checks import REGISTRY, Breaks, Family, Finding, Status, catalogue
from medagentrx.checks.registry import check
from medagentrx.engine import Evaluation, Verdict, alpha_after, decide, evaluate, json_safe
from medagentrx.errors import InputError
from medagentrx.exit_codes import ExitCode
from medagentrx.history import History, Release
from medagentrx.plan import load_plan, plan_fingerprint
from medagentrx.stats.alpha import initial_state, next_alpha, record
from tests.helpers.cases import Case, make_case

NOW = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)


def run(case: Case, history: History | None = None) -> Evaluation:
    return evaluate(**case.kwargs(), history=history, n_replicates=200, now=NOW)


def statuses(evaluation: Evaluation) -> dict[str, str]:
    return {f.check_id: f.status.value for f in evaluation.findings}


@pytest.fixture(scope="module")
def good(tmp_path_factory: pytest.TempPathFactory) -> Case:
    return make_case(tmp_path_factory.mktemp("good"))


@pytest.fixture(scope="module")
def good_eval(good: Case) -> Evaluation:
    return run(good)


def _history_for(case: Case, **changes: Any) -> History:
    plan = load_plan(case.plan)
    fields: dict[str, Any] = {
        "plan_id": plan.plan.id,
        "plan_revision": plan.plan.revision,
        "plan_fingerprint": plan_fingerprint(plan),
    }
    fields.update(changes)
    return History(**fields)


# Catalogue and verdict rule -------------------------------------------------------------


def test_catalogue_matches_the_brief() -> None:
    ids = [spec.check_id for spec in catalogue()]
    assert ids == [
        "PLAN-001",
        "PLAN-002",
        "PLAN-003",
        "PLAN-004",
        "DATA-001",
        "DATA-002",
        "DATA-003",
        "DATA-004",
        "DATA-005",
        "PERF-001",
        "PERF-002",
        "PERF-003",
        "PERF-004",
        "PERF-005",
        "PERF-006",
        "LIFE-001",
        "LIFE-002",
        "DOC-001",
    ]
    breaks = {spec.check_id: spec.breaks for spec in catalogue()}
    assert {k for k, v in breaks.items() if v is Breaks.OUTSIDE_PLAN} == {
        "PLAN-001",
        "PLAN-002",
        "PLAN-003",
        "PLAN-004",
        "DATA-001",
        "DATA-003",
        "DATA-004",
        "LIFE-002",
    }
    assert {k for k, v in breaks.items() if v is Breaks.WARNING} == {"DATA-005", "PERF-006"}
    assert all(spec.cross_reference and spec.title for spec in catalogue())


def test_duplicate_check_id_is_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        check("PLAN-001", Family.PLAN, "x", Breaks.FAILED, "x")(
            lambda ctx: Finding("PLAN-001", Status.PASS, "")
        )


@pytest.mark.parametrize(
    ("statuses_by_id", "expected"),
    [
        (
            {"PLAN-001": Status.PASS, "PERF-001": Status.PASS, "DATA-005": Status.WARN},
            Verdict.ACCEPTED,
        ),
        ({"PERF-001": Status.FAIL, "DATA-005": Status.WARN}, Verdict.FAILED),
        ({"PERF-001": Status.FAIL, "DATA-004": Status.FAIL}, Verdict.OUTSIDE_PLAN),
        ({"PLAN-002": Status.FAIL, "PERF-001": Status.SKIPPED}, Verdict.OUTSIDE_PLAN),
        ({"PERF-006": Status.WARN, "DOC-001": Status.NOT_APPLICABLE}, Verdict.ACCEPTED),
    ],
)
def test_verdict_rule(statuses_by_id: dict[str, Status], expected: Verdict) -> None:
    findings = [Finding(k, v, "") for k, v in statuses_by_id.items()]
    assert decide(findings) is expected


def test_exit_codes() -> None:
    assert [int(v.exit_code) for v in Verdict] == [0, 1, 2]
    assert [v.exit_code for v in Verdict] == [
        ExitCode.ACCEPTED,
        ExitCode.FAILED,
        ExitCode.OUTSIDE_PLAN,
    ]


# The good update -----------------------------------------------------------------------


def test_good_update_is_accepted(good_eval: Evaluation) -> None:
    assert good_eval.verdict is Verdict.ACCEPTED
    assert good_eval.failed_checks == []
    assert good_eval.touched_test_set
    assert good_eval.alpha_used == pytest.approx(0.05 / 12)
    assert good_eval.candidate_version == "2.1.0"
    assert set(good_eval.inputs) == {
        "plan",
        "candidate",
        "previous",
        "anchor",
        "manifest",
        "model_meta",
    }
    assert good_eval.finding("PERF-005").details["multiplicity"] == "holm"
    with pytest.raises(KeyError):
        good_eval.finding("NOPE-001")


def test_to_dict_is_strict_json(good_eval: Evaluation) -> None:
    text = json.dumps(good_eval.to_dict(), allow_nan=False)
    data = json.loads(text)
    assert data["verdict"] == "ACCEPTED"
    assert [c["id"] for c in data["checks"]] == [s.check_id for s in catalogue()]


def test_json_safe() -> None:
    import numpy as np

    assert json_safe(
        {"a": float("inf"), "b": [float("-inf"), float("nan")], "c": (np.float64(1.5),)}
    ) == {
        "a": "Infinity",
        "b": ["-Infinity", "NaN"],
        "c": [1.5],
    }


def test_identical_seed_gives_identical_result(good: Case, good_eval: Evaluation) -> None:
    again = run(good)
    assert again.to_dict() == good_eval.to_dict()


# PLAN checks -----------------------------------------------------------------------------


def test_invalid_plan_is_outside_plan(tmp_path: Path, good: Case) -> None:
    bad = tmp_path / "plan.yaml"
    bad.write_text("pccp_version: '9.9'\n", encoding="utf-8")
    result = evaluate(**dataclasses.replace(good, plan=bad).kwargs(), now=NOW)
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.failed_checks == ["PLAN-001"]
    assert {f.status for f in result.findings[1:]} == {Status.SKIPPED}
    assert result.plan_id is None
    assert not result.touched_test_set


def test_plan_revision_differs_from_ledger(good: Case) -> None:
    result = run(good, _history_for(good, plan_revision=2))
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert "PLAN-001" in result.failed_checks
    assert "revision 2" in result.finding("PLAN-001").message


def test_plan_changed_without_new_revision(good: Case) -> None:
    result = run(good, _history_for(good, plan_fingerprint="f" * 64))
    assert result.failed_checks == ["PLAN-001"]
    assert "without a new revision" in result.finding("PLAN-001").message


def test_plan_matches_ledger(good: Case) -> None:
    result = run(good, _history_for(good))
    assert statuses(result)["PLAN-001"] == "pass"
    assert result.finding("PLAN-001").message == "Plan is valid and unchanged"


def test_unlisted_modification(tmp_path: Path) -> None:
    case = make_case(tmp_path, meta_edit=lambda m: m.update(modification_id="M9"))
    result = run(case)
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.failed_checks == ["PLAN-002"]
    assert statuses(result)["PERF-001"] == "skipped"
    assert "outside the plan (PLAN-002)" in result.finding("PERF-001").message
    assert not result.touched_test_set
    assert result.alpha_used is None


def test_changed_intended_use(tmp_path: Path) -> None:
    case = make_case(tmp_path, meta_edit=lambda m: m.update(intended_use_sha256="c" * 64))
    assert run(case).failed_checks == ["PLAN-003"]


def test_update_count_exhausted(good: Case) -> None:
    releases = tuple(Release(f"2.0.{i}", NOW - dt.timedelta(days=400 + i)) for i in range(12))
    result = run(good, _history_for(good, releases=releases))
    assert result.failed_checks == ["PLAN-004"]
    assert "All 12 updates" in result.finding("PLAN-004").message


def test_update_frequency_exceeded(good: Case) -> None:
    releases = (Release("2.0.1", dt.datetime(2026, 4, 2, tzinfo=dt.UTC)),)
    result = run(good, _history_for(good, releases=releases))
    assert result.failed_checks == ["PLAN-004"]
    assert "this quarter" in result.finding("PLAN-004").message
    earlier = (Release("2.0.1", dt.datetime(2026, 3, 30, tzinfo=dt.UTC)),)
    assert run(good, _history_for(good, releases=earlier)).failed_checks == []


@pytest.mark.parametrize(
    ("period", "at", "start"),
    [
        ("month", dt.datetime(2026, 5, 17, 9), dt.datetime(2026, 5, 1)),
        ("quarter", dt.datetime(2026, 8, 17, 9), dt.datetime(2026, 7, 1)),
        ("year", dt.datetime(2026, 8, 17, 9), dt.datetime(2026, 1, 1)),
    ],
)
def test_period_start(period: str, at: dt.datetime, start: dt.datetime) -> None:
    from medagentrx.checks.plan_checks import period_start

    assert period_start(at, period) == start


# DATA checks -----------------------------------------------------------------------------


def test_tampered_labels_are_outside_plan(tmp_path: Path, good: Case) -> None:
    text = good.candidate.read_text(encoding="utf-8").splitlines()
    header, first = text[0], text[1].split(",")
    first[1] = "1" if first[1] == "0" else "0"
    tampered = tmp_path / "candidate.csv"
    tampered.write_text("\n".join([header, ",".join(first), *text[2:]]) + "\n", encoding="utf-8")
    result = run(dataclasses.replace(good, candidate=tampered))
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.failed_checks == ["DATA-001"]
    assert statuses(result)["PERF-001"] == "skipped"
    assert not result.touched_test_set
    assert result.alpha_used is None


def test_previous_with_other_rows(tmp_path: Path, good: Case) -> None:
    lines = good.previous.read_text(encoding="utf-8").splitlines()
    short = tmp_path / "previous.csv"
    short.write_text("\n".join(lines[:-5]) + "\n", encoding="utf-8")
    result = run(dataclasses.replace(good, previous=short))
    assert result.failed_checks == ["DATA-001"]
    assert "previous" in result.finding("DATA-001").message
    assert (
        result.finding("DATA-001").details["mismatches"]["previous"][0].startswith("5 missing rows")
    )


def test_leaky_training(tmp_path: Path) -> None:
    result = run(make_case(tmp_path, leak=300))
    assert result.verdict is Verdict.FAILED
    assert result.failed_checks == ["DATA-002"]
    assert result.finding("DATA-002").details["overlaps"]["patient_id"]["count"] == 300


def test_row_id_overlap(tmp_path: Path) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["data_management"]["forbid_overlap_on"] = ["row_id", "patient_id"]

    def manifest(m: dict[str, list[object]]) -> None:
        m["row_id"][0] = "T00000"

    result = run(make_case(tmp_path, plan_edit=edit, manifest_edit=manifest))
    assert result.failed_checks == ["DATA-002"]
    assert "row_id: 1" in result.finding("DATA-002").message


def test_out_of_scope_training_rows(tmp_path: Path) -> None:
    def paediatric(m: dict[str, list[object]]) -> None:
        for i in range(25):
            m["age"][i] = 9

    result = run(make_case(tmp_path, manifest_edit=paediatric))
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.failed_checks == ["DATA-003"]
    assert result.finding("DATA-003").details["failing"] == 25


def test_manifest_not_named_in_metadata(tmp_path: Path) -> None:
    case = make_case(tmp_path, meta_edit=lambda m: m.update(training_manifest_sha256="d" * 64))
    result = run(case)
    assert result.failed_checks == ["DATA-003"]
    assert "training_manifest_sha256" in result.finding("DATA-003").message


def test_evaluation_budget_exhausted(good: Case) -> None:
    result = run(good, _history_for(good, looks_used=20))
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.failed_checks == ["DATA-004"]
    assert not result.touched_test_set


def test_population_shift_warns_without_changing_verdict(tmp_path: Path) -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    extra = {"lactate": np.round(rng.normal(4.0, 1.0, 4000), 2).tolist()}

    def manifest(m: dict[str, list[object]]) -> None:
        m["lactate"] = np.round(rng.normal(2.0, 1.0, 3000), 2).tolist()

    result = run(make_case(tmp_path, test_extra=extra, manifest_edit=manifest))
    assert result.verdict is Verdict.ACCEPTED
    assert statuses(result)["DATA-005"] == "warn"
    assert result.finding("DATA-005").details["shifted"] == ["lactate"]


def test_no_shared_features(tmp_path: Path) -> None:
    def drop_site(m: dict[str, list[object]]) -> None:
        del m["site"]

    def plan(p: dict[str, Any]) -> None:
        p["data_management"]["training_inclusion"] = {"field": "age", "op": "ge", "value": 18}

    case = make_case(tmp_path, plan_edit=plan, manifest_edit=drop_site)
    assert statuses(run(case))["DATA-005"] == "not_applicable"


def test_categorical_shift(tmp_path: Path) -> None:
    def manifest(m: dict[str, list[object]]) -> None:
        m["site"] = ["A"] * len(m["site"])

    def plan(p: dict[str, Any]) -> None:
        p["data_management"]["training_inclusion"] = {"field": "age", "op": "ge", "value": 18}

    result = run(make_case(tmp_path, manifest_edit=manifest, plan_edit=plan))
    assert result.finding("DATA-005").details["shifted"] == ["site"]


# PERF, LIFE and DOC checks --------------------------------------------------------------


def test_miscalibrated_candidate(tmp_path: Path) -> None:
    result = run(make_case(tmp_path, candidate_scale=0.6))
    assert result.verdict is Verdict.FAILED
    assert "PERF-003" in result.failed_checks
    assert result.finding("PERF-003").details["candidate"]["slope"] == pytest.approx(0.6, abs=0.06)
    assert result.finding("PERF-003").details["candidate"]["slope"] == pytest.approx(0.6, abs=0.06)


def test_worse_candidate_fails_performance(tmp_path: Path) -> None:
    result = run(make_case(tmp_path, previous_noise=0.0, candidate_noise=1.2))
    assert result.verdict is Verdict.FAILED
    assert {"PERF-001", "PERF-004", "LIFE-001"} <= set(result.failed_checks)


def test_subgroup_harm(tmp_path: Path) -> None:
    result = run(make_case(tmp_path, n=6000, harm_site="C"))
    finding = result.finding("PERF-005")
    assert finding.status is Status.FAIL
    assert "site=C" in finding.message
    groups = finding.details["subgroups"]
    worst = min(groups, key=lambda g: g["delta"])
    assert (worst["column"], worst["level"], worst["status"]) == ("site", "C", "fail")
    others = [g for g in groups if g["column"] == "site" and g["level"] != "C"]
    assert all(g["status"] == "pass" for g in others)


@pytest.mark.parametrize(("policy", "status"), [("fail", Status.FAIL), ("warn", Status.WARN)])
def test_insufficient_subgroup_evidence(tmp_path: Path, policy: str, status: Status) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["performance"]["subgroups"]["min_events"] = 1000
        plan["performance"]["subgroups"]["on_insufficient"] = policy

    finding = run(make_case(tmp_path, plan_edit=edit)).finding("PERF-005")
    assert finding.status is status
    assert finding.message.startswith("Insufficient evidence in")


def test_bonferroni_subgroups(tmp_path: Path) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["performance"]["subgroups"]["multiplicity"] = "bonferroni"

    finding = run(make_case(tmp_path, plan_edit=edit)).finding("PERF-005")
    assert finding.status is Status.PASS
    levels = [g["alpha_used"] for g in finding.details["subgroups"]]
    assert levels == [pytest.approx((0.05 / 12) / 8)] * 8


def test_underpowered(tmp_path: Path) -> None:
    result = run(make_case(tmp_path, n=600, seed=3))
    assert statuses(result)["PERF-006"] == "warn"


def test_bio_creep_against_anchor(tmp_path: Path) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["performance"]["criteria"][0]["vs"] = ["previous"]

    case = make_case(
        tmp_path, previous_noise=1.6, anchor_noise=0.0, candidate_noise=0.9, plan_edit=edit
    )
    result = run(case)
    assert "LIFE-001" in result.failed_checks
    assert statuses(result)["PERF-001"] == "pass"
    assert result.finding("LIFE-001").details["test"]["delta"] < 0


def test_alpha_budget_exhausted(good: Case) -> None:
    state = initial_state("bonferroni", 0.05, 12)
    for _ in range(12):
        state = record(state, next_alpha(state), rejected=True)
    result = run(good, _history_for(good, alpha=state))
    assert result.verdict is Verdict.OUTSIDE_PLAN
    assert result.failed_checks == ["LIFE-002"]
    assert statuses(result)["PERF-001"] == "skipped"
    assert alpha_after(state, result) == state


def test_alpha_after_records_accepted(good: Case, good_eval: Evaluation) -> None:
    state = initial_state("alpha_investing", 0.05, 12)
    after = alpha_after(state, good_eval)
    assert after.updates_tested == 1
    assert after.wealth > state.wealth


def test_plan_without_optional_criteria(tmp_path: Path) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["performance"]["criteria"] = [
            c for c in plan["performance"]["criteria"] if c["metric"] == "calibration_slope"
        ]
        plan["performance"].pop("subgroups")
        plan["update_procedures"]["require_model_card_update"] = False

    result = run(make_case(tmp_path, plan_edit=edit))
    got = statuses(result)
    for check_id in ("PERF-001", "PERF-002", "PERF-004", "PERF-005", "PERF-006", "DOC-001"):
        assert got[check_id] == "not_applicable", check_id
    assert result.verdict is Verdict.ACCEPTED


def test_specificity_criterion(tmp_path: Path) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["performance"]["criteria"].append(
            {
                "metric": "specificity_at_threshold",
                "test": "non_inferiority",
                "vs": ["anchor"],
                "margin": 0.03,
            }
        )

    finding = run(make_case(tmp_path, plan_edit=edit)).finding("PERF-002")
    assert set(finding.details["tests"]) == {"sensitivity_vs_previous", "specificity_vs_anchor"}


def test_calibration_not_estimable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from medagentrx.checks import doc_checks, perf_checks
    from medagentrx.errors import StatsError

    def broken(*_: object, **__: object) -> None:
        raise StatsError("outcomes are perfectly separated")

    monkeypatch.setattr(perf_checks, "calibration", broken)
    monkeypatch.setattr(doc_checks, "calibration", broken)
    result = run(make_case(tmp_path))
    assert set(result.failed_checks) == {"PERF-003", "DOC-001"}
    assert "separated" in result.finding("DOC-001").message


def test_missing_key_column_is_an_input_error(tmp_path: Path) -> None:
    def edit(plan: dict[str, Any]) -> None:
        plan["data_management"]["forbid_overlap_on"] = ["encounter_id"]

    with pytest.raises(InputError, match="encounter_id"):
        run(make_case(tmp_path, plan_edit=edit))


def test_registry_has_every_check() -> None:
    assert len(REGISTRY) == 18


def test_other_overlap_key_and_blank_feature(tmp_path: Path) -> None:
    def plan(p: dict[str, Any]) -> None:
        p["data_management"]["forbid_overlap_on"] = ["patient_id", "encounter_id"]

    def manifest(m: dict[str, list[object]]) -> None:
        m["encounter_id"] = [f"E{i}" for i in range(len(m["row_id"]))]
        m["note"] = [""] * len(m["row_id"])
        m["ward"] = [f"W{i}" for i in range(len(m["row_id"]))]

    extra: dict[str, list[object]] = {
        "encounter_id": [f"E{i}" for i in range(2, 4002)],
        "note": [""] * 4000,
        "ward": [f"W{i}" for i in range(4000)],
    }
    result = run(make_case(tmp_path, plan_edit=plan, manifest_edit=manifest, test_extra=extra))
    assert result.failed_checks == ["DATA-002"]
    assert result.finding("DATA-002").details["overlaps"]["encounter_id"]["count"] == 2998
    shift = result.finding("DATA-005").details
    assert "note" not in shift["smd"]
    assert "encounter_id" not in shift["smd"]
    assert shift["skipped_high_cardinality"] == ["ward"]


def test_only_auroc_criterion_and_strong_power(tmp_path: Path) -> None:
    def plan(p: dict[str, Any]) -> None:
        p["performance"]["criteria"] = [p["performance"]["criteria"][0]]

    result = run(make_case(tmp_path, n=12000, plan_edit=plan))
    got = statuses(result)
    assert got["PERF-003"] == "not_applicable"
    assert got["PERF-006"] == "pass"


def test_previous_calibration_not_estimable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from medagentrx.checks import perf_checks
    from medagentrx.errors import StatsError
    from medagentrx.stats.calibration import calibration as real

    calls = {"n": 0}

    def second_fails(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise StatsError("separated")
        return real(*args, **kwargs)

    monkeypatch.setattr(perf_checks, "calibration", second_fails)
    finding = run(make_case(tmp_path)).finding("PERF-003")
    assert finding.status is Status.PASS
    assert finding.details["previous"] is None


def test_numeric_feature_parsing() -> None:
    from medagentrx.checks.data_checks import _numeric

    assert _numeric([1, "2.5", 3.0]) == [1.0, 2.5, 3.0]
    assert _numeric([True, 1]) is None
    assert _numeric(["inf", 1]) is None
    assert _numeric(["x", 1]) is None


def test_condition_on_unsupported_value_type() -> None:
    from medagentrx.plan.conditions import evaluate
    from medagentrx.plan.models import LeafCondition

    assert not evaluate(LeafCondition(field="x", op="eq", value=1), {"x": [1]})


def test_paired_test_from_checks_margin() -> None:
    import numpy as np

    from medagentrx.errors import StatsError
    from medagentrx.stats.delong import delong, paired_test_from

    result = delong(np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8]))
    with pytest.raises(StatsError, match="margin"):
        paired_test_from(result, 0, 0, margin=-0.1, alpha=0.025)
