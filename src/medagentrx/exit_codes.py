# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Process exit codes shared by the CLI and its integrations."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes of the ``medagentrx`` command."""

    ACCEPTED = 0
    FAILED = 1
    OUTSIDE_PLAN = 2
    USAGE_ERROR = 3
