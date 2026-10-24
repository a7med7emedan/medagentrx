# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Everything the LIVE checks read for one deployment QC run."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from medagentrx.io.predictions import Scores
from medagentrx.plan.models import ChangePlan, DeploymentQC


@dataclass(frozen=True)
class QcHistoryRun:
    """An earlier QC run of the same model version, read from the ledger.

    Attributes:
        seq: Ledger sequence number.
        recorded_at: Time of the run.
        bias: Mean of live minus expected score.
        in_control: Whether the run was IN_CONTROL.
    """

    seq: int
    recorded_at: dt.datetime
    bias: float
    in_control: bool


@dataclass
class QcContext:
    """Inputs of one QC run.

    Attributes:
        plan: The validated change plan.
        plan_fingerprint: Its fingerprint.
        qc: The plan's deployment QC block.
        model_version: Version the live system reports it is running.
        released_version: Version the ledger says is released: the latest release
            record, or the anchor version when there is none.
        live: Scores of the live system on the control set.
        expected: Expected scores of ``model_version``, or None when the plan has none.
        live_sha256: SHA-256 of the live score file.
        expected_sha256: SHA-256 of the expected score file.
        control_inputs_sha256: SHA-256 of the raw control file, when supplied.
        history: Earlier QC runs of ``model_version``, oldest first.
        now: Time of the run.
    """

    plan: ChangePlan
    plan_fingerprint: str
    qc: DeploymentQC
    model_version: str
    released_version: str
    live: Scores
    expected: Scores
    live_sha256: str
    expected_sha256: str
    control_inputs_sha256: str | None
    history: tuple[QcHistoryRun, ...]
    now: dt.datetime
    blockers: list[str] = field(default_factory=list)

    @property
    def measurement_blocker(self) -> str | None:
        """Why the run cannot be measured, or None when it can."""
        if self.blockers:
            failed = ", ".join(self.blockers)
            return f"the run is not bound to the released version and control set ({failed})"
        return None
