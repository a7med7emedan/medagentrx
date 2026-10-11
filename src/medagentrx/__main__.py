# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Allow ``python -m medagentrx``."""

from medagentrx.cli import app

if __name__ == "__main__":
    app(prog_name="medagentrx")
