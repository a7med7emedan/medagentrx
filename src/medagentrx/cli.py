# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Command line interface."""

import typer

from medagentrx import __version__

app = typer.Typer(
    name="medagentrx",
    help=(
        "Check every model update, by an engineer, a pipeline or an AI agent, "
        "against its approved change plan."
    ),
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback()
def main() -> None:
    """Check every model update against its approved change plan."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"medagentrx {__version__}")
