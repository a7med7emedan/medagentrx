# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Typed model of a change plan (``change-plan.yaml``).

The plan follows the three components of an FDA Predetermined Change Control
Plan: Description of Modifications, Modification Protocol and Impact
Assessment. Every model forbids unknown keys and is immutable once built.

Conditions are structured data. They are never parsed as expressions and
never evaluated as code.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

Sha256 = Annotated[
    str,
    Field(pattern=SHA256_PATTERN, description="SHA-256 digest as 64 lowercase hex characters."),
]
Identifier = Annotated[
    str,
    Field(
        pattern=IDENTIFIER_PATTERN,
        description="Identifier of letters, digits, dot, underscore or hyphen.",
    ),
]
Probability = Annotated[float, Field(gt=0.0, lt=1.0)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Scalar = str | int | float | bool

COMPARISON_OPS = ("eq", "ne", "lt", "le", "gt", "ge")
ORDER_OPS = ("lt", "le", "gt", "ge")
LIST_OPS = ("in", "not_in")
NULL_OPS = ("is_null", "not_null")
ConditionOp = Literal[
    "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "between", "is_null", "not_null"
]


class StrictModel(BaseModel):
    """Base for every plan model: unknown keys are an error and values are frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# Plan header ---------------------------------------------------------------------------


class PlanHeader(StrictModel):
    """Identity of the authorised plan."""

    id: Identifier = Field(description="Stable identifier of the plan.")
    revision: int = Field(
        ge=1, description="Plan revision. Any change to the plan itself must bump this."
    )
    authorised: dt.date = Field(description="Date the plan was authorised, as YYYY-MM-DD.")
    device: Text = Field(description="Name of the device or model the plan governs.")
    intended_use_sha256: Sha256 = Field(
        description="SHA-256 of the intended-use statement. A change means a new intended use."
    )


class UpdateFrequency(StrictModel):
    """How often updates may be released."""

    max_per: Literal["month", "quarter", "year"] = Field(description="Calendar period.")
    count: int = Field(ge=1, description="Maximum number of updates in each period.")


# Description of Modifications -----------------------------------------------------------


class Modification(StrictModel):
    """One pre-specified modification (FDA Description of Modifications)."""

    id: Identifier = Field(description="Identifier referenced by model metadata.")
    type: Literal["retrain_same_architecture", "recalibrate", "fine_tune"] = Field(
        description="Kind of change. A new architecture is never covered by a plan."
    )
    automatic: bool = Field(
        description="True if a pipeline or agent may trigger the change without a human."
    )
    scope: Literal["global", "local"] = Field(
        description="global: the same model for all sites. local: adapted per site."
    )
    description: Text | None = Field(
        default=None, description="Optional free-text description of the modification."
    )


# Conditions -----------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


class LeafCondition(StrictModel):
    """A single comparison of one field against a literal value."""

    field: Annotated[str, Field(min_length=1, max_length=128)] = Field(
        description="Column name in the training data manifest."
    )
    op: ConditionOp = Field(description="Comparison operator from a closed list.")
    value: Scalar | list[Scalar] | None = Field(
        default=None,
        description=(
            "Literal operand. A scalar for eq, ne, lt, le, gt, ge. A list for in and not_in. "
            "Two ordered values for between. Absent for is_null and not_null. "
            "Dates are written as YYYY-MM-DD strings."
        ),
    )

    @model_validator(mode="after")
    def _check_value_shape(self) -> LeafCondition:
        op, value = self.op, self.value
        if op in NULL_OPS:
            if value is not None:
                raise ValueError(f"op '{op}' takes no value")
        elif op in LIST_OPS:
            if not isinstance(value, list) or not value:
                raise ValueError(f"op '{op}' needs a non-empty list value")
        elif op == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("op 'between' needs a list of exactly two values")
            low, high = value
            if not _orderable_pair(low, high):
                raise ValueError("op 'between' needs two numbers or two strings")
            if low > high:  # type: ignore[operator]
                raise ValueError("op 'between' needs the lower value first")
        else:
            if value is None or isinstance(value, list):
                raise ValueError(f"op '{op}' needs a single value")
            if op in ORDER_OPS and isinstance(value, bool):
                raise ValueError(f"op '{op}' cannot compare a boolean")
        return self


def _orderable_pair(low: object, high: object) -> bool:
    both_numbers = _is_number(low) and _is_number(high)
    both_strings = isinstance(low, str) and isinstance(high, str)
    return both_numbers or both_strings


class AllCondition(StrictModel):
    """True when every inner condition is true."""

    all_: list[Condition] = Field(
        alias="all", min_length=1, description="Conditions that must all hold."
    )


class AnyCondition(StrictModel):
    """True when at least one inner condition is true."""

    any_: list[Condition] = Field(
        alias="any", min_length=1, description="Conditions of which at least one must hold."
    )


class NotCondition(StrictModel):
    """True when the inner condition is false."""

    not_: Condition = Field(alias="not", description="Condition that must not hold.")


def _condition_tag(value: Any) -> str:  # noqa: ANN401
    if isinstance(value, BaseModel):
        return f"<{type(value).__name__}>"
    keys = set(value) if isinstance(value, dict) else set()
    for key, tag in (
        ("all", "<AllCondition>"),
        ("any", "<AnyCondition>"),
        ("not", "<NotCondition>"),
    ):
        if key in keys:
            return tag
    return "<LeafCondition>"


Condition = Annotated[
    Annotated[LeafCondition, Tag("<LeafCondition>")]
    | Annotated[AllCondition, Tag("<AllCondition>")]
    | Annotated[AnyCondition, Tag("<AnyCondition>")]
    | Annotated[NotCondition, Tag("<NotCondition>")],
    Discriminator(_condition_tag),
]


# Modification Protocol: data management -------------------------------------------------


class LockedTestSet(StrictModel):
    """The sequestered test set every update is evaluated on."""

    sha256: Sha256 = Field(
        description="Canonical fingerprint of the test set, from `medagentrx fingerprint`."
    )
    max_evaluations: int = Field(
        ge=1, description="Looks at the locked test set allowed over the life of the plan."
    )


class DataManagement(StrictModel):
    """FDA Modification Protocol, element 1: data management."""

    training_inclusion: Condition = Field(
        description="Condition every row of the training manifest must meet."
    )
    locked_test_set: LockedTestSet = Field(description="The locked test set.")
    forbid_overlap_on: list[Annotated[str, Field(min_length=1)]] = Field(
        min_length=1,
        description="Keys that must never be shared by training and test rows.",
    )


# Modification Protocol: performance evaluation ------------------------------------------


class NonInferiorityCriterion(StrictModel):
    """The candidate must not be worse than a comparator by more than a margin."""

    metric: Literal[
        "auroc", "sensitivity_at_threshold", "specificity_at_threshold", "net_benefit"
    ] = Field(description="Metric compared between the candidate and each comparator.")
    test: Literal["non_inferiority"] = Field(description="Paired non-inferiority test.")
    vs: list[Literal["previous", "anchor"]] = Field(
        min_length=1, description="Comparators: the previous version, the anchor, or both."
    )
    margin: float = Field(ge=0.0, lt=1.0, description="Non-inferiority margin on the metric.")
    at_thresholds: list[Probability] | None = Field(
        default=None,
        description="Risk thresholds for net_benefit. Required for that metric only.",
    )

    @model_validator(mode="after")
    def _check_thresholds(self) -> NonInferiorityCriterion:
        if self.metric == "net_benefit":
            if not self.at_thresholds:
                raise ValueError("metric 'net_benefit' needs at_thresholds")
            if len(set(self.at_thresholds)) != len(self.at_thresholds):
                raise ValueError("at_thresholds must not repeat a value")
        elif self.at_thresholds is not None:
            raise ValueError(f"at_thresholds applies to net_benefit only, not '{self.metric}'")
        if len(set(self.vs)) != len(self.vs):
            raise ValueError("vs must not repeat a comparator")
        return self


class WithinCriterion(StrictModel):
    """The candidate's metric must lie inside fixed bounds."""

    metric: Literal["calibration_slope", "calibration_intercept"] = Field(
        description="Calibration measure of the candidate on the locked test set."
    )
    test: Literal["within"] = Field(description="Bounds test on the candidate alone.")
    bounds: tuple[float, float] = Field(description="Inclusive lower and upper bound.")

    @model_validator(mode="after")
    def _check_bounds(self) -> WithinCriterion:
        if self.bounds[0] >= self.bounds[1]:
            raise ValueError("bounds must be [lower, upper] with lower < upper")
        return self


def _criterion_tag(value: Any) -> str:  # noqa: ANN401
    if isinstance(value, BaseModel):
        return f"<{type(value).__name__}>"
    test = value.get("test") if isinstance(value, dict) else None
    return "<WithinCriterion>" if test == "within" else "<NonInferiorityCriterion>"


Criterion = Annotated[
    Annotated[NonInferiorityCriterion, Tag("<NonInferiorityCriterion>")]
    | Annotated[WithinCriterion, Tag("<WithinCriterion>")],
    Discriminator(_criterion_tag),
]


class CumulativeDrift(StrictModel):
    """Bio-creep guard: the candidate is always compared with the anchor."""

    metric: Literal["auroc"] = Field(description="Metric tracked against the anchor.")
    max_drop_vs_anchor: float = Field(
        ge=0.0, lt=1.0, description="Largest allowed drop below the anchor (CI lower bound)."
    )


class Subgroups(StrictModel):
    """Subgroup criterion applied to every level of every listed column."""

    by: list[Annotated[str, Field(min_length=1)]] = Field(
        min_length=1, description="Subgroup columns in the prediction files."
    )
    metric: Literal["auroc"] = Field(description="Metric compared within each subgroup.")
    max_drop: float = Field(ge=0.0, lt=1.0, description="Largest allowed drop in any subgroup.")
    min_events: int = Field(
        ge=1, description="Positives and negatives each needed, else insufficient evidence."
    )
    on_insufficient: Literal["fail", "warn"] = Field(
        description="What an insufficient-evidence subgroup does to the verdict."
    )
    multiplicity: Literal["holm", "bonferroni"] = Field(description="Correction across subgroups.")


class Power(StrictModel):
    """Power requirement for the locked test set."""

    min_power: Probability = Field(description="Warn when power to detect the margin is lower.")


class Performance(StrictModel):
    """FDA Modification Protocol, element 3: performance evaluation."""

    alpha_total: Probability = Field(
        description="Family-wise error rate across all updates under this plan."
    )
    alpha_spending: Literal["bonferroni", "alpha_investing"] = Field(
        description="How alpha_total is spent across updates."
    )
    operating_threshold: Probability = Field(
        description="Risk threshold at which sensitivity and specificity are assessed."
    )
    criteria: list[Criterion] = Field(min_length=1, description="Acceptance criteria.")
    cumulative_drift: CumulativeDrift = Field(description="Bio-creep guard against the anchor.")
    subgroups: Subgroups | None = Field(default=None, description="Subgroup criterion.")
    power: Power | None = Field(default=None, description="Power requirement.")


# Modification Protocol: update procedures -----------------------------------------------


class UpdateProcedures(StrictModel):
    """FDA Modification Protocol, element 4: update procedures."""

    require_model_card_update: bool = Field(
        description="True if each release must update the model card."
    )
    user_communication: Text = Field(description="How users are told about an update.")
    real_world_monitoring: Text = Field(description="How performance is monitored after release.")


# Impact Assessment ----------------------------------------------------------------------


class Risk(StrictModel):
    """One risk of the planned modifications and its mitigation."""

    risk: Text = Field(description="The risk.")
    mitigation: Text = Field(description="How the plan mitigates it.")


class ImpactAssessment(StrictModel):
    """FDA third component: benefits and risks of the planned modifications."""

    benefits: Text = Field(description="Expected benefits.")
    risks: list[Risk] = Field(min_length=1, description="Risks and mitigations.")


class RegulatoryMap(StrictModel):
    """Informative cross-reference, rendered in the plan document."""

    fda: Text | None = Field(default=None, description="FDA reference.")
    eu: list[Text] = Field(default_factory=list, description="EU references.")


# The plan -------------------------------------------------------------------------------


class ChangePlan(StrictModel):
    """An approved change plan for one clinical prediction model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        title="MedAgentRx change plan",
        json_schema_extra={
            "description": (
                "An approved change plan (FDA PCCP, EU AI Act Art. 43(4)). "
                "Every model update is checked against it."
            )
        },
    )

    pccp_version: Literal["1.0"] = Field(description="Version of this file format.")
    plan: PlanHeader = Field(description="Identity, revision and authorisation of the plan.")
    anchor_version: Annotated[str, Field(min_length=1, max_length=64)] = Field(
        description="The originally authorised model version. It never changes."
    )
    anchor_predictions_sha256: Sha256 | None = Field(
        default=None,
        description=(
            "SHA-256 of the anchor's prediction file on the locked test set, recorded at "
            "authorisation. When given, the anchor file of every check must match it."
        ),
    )
    max_updates: int = Field(ge=1, description="Updates allowed under this plan.")
    update_frequency: UpdateFrequency = Field(description="Release frequency limit.")
    modifications: list[Modification] = Field(
        min_length=1, description="FDA Description of Modifications."
    )
    data_management: DataManagement = Field(description="Modification Protocol, data management.")
    performance: Performance = Field(description="Modification Protocol, performance evaluation.")
    update_procedures: UpdateProcedures = Field(
        description="Modification Protocol, update procedures."
    )
    impact_assessment: ImpactAssessment = Field(description="FDA Impact Assessment.")
    regulatory_map: RegulatoryMap | None = Field(
        default=None, description="Informative regulatory cross-reference."
    )


AllCondition.model_rebuild()
AnyCondition.model_rebuild()
NotCondition.model_rebuild()
DataManagement.model_rebuild()
