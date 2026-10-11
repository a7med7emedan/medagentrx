# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Exceptions raised for user mistakes. The CLI shows them without a traceback."""

from __future__ import annotations

from collections.abc import Iterable


class MedAgentRxError(Exception):
    """Base for errors caused by inputs or usage rather than by a bug.

    Args:
        summary: One line describing what went wrong.
        details: Optional list of specific problems, one per line.
    """

    def __init__(self, summary: str, details: Iterable[str] = ()) -> None:
        self.summary = summary
        self.details = tuple(details)
        super().__init__(self.__str__())

    def __str__(self) -> str:
        lines = [self.summary, *(f"  - {item}" for item in self.details)]
        return "\n".join(lines)


class PlanError(MedAgentRxError):
    """The change plan cannot be read or is not valid."""


class InputError(MedAgentRxError):
    """A prediction file, manifest, metadata file or path is not acceptable."""


class StatsError(MedAgentRxError):
    """A statistic cannot be computed from the data given, for example one class only."""
