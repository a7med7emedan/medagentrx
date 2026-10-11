# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Command line interface.

Exit codes: 0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN, 3 input or usage error.
User mistakes are reported in plain text, never as a traceback.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from medagentrx import __version__
from medagentrx.errors import MedAgentRxError
from medagentrx.exit_codes import ExitCode
from medagentrx.io.fingerprint import fingerprint_file
from medagentrx.io.limits import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_ROWS, Limits
from medagentrx.plan import load_plan_with_warnings, parse_plan_text, plan_fingerprint
from medagentrx.plan.schema import plan_json_schema_text
from medagentrx.plan.template import PlanAnswers, render_plan_template

if TYPE_CHECKING:
    from medagentrx.engine import Evaluation

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


def run() -> None:
    """Console entry point. Maps usage errors to exit code 3."""
    try:
        code = app(standalone_mode=False)
    except typer.Abort:
        typer.echo("Aborted.", err=True)
        code = ExitCode.USAGE_ERROR
    except typer.TyperException as exc:
        show = getattr(exc, "show", None)
        if callable(show):
            show()
        else:
            typer.echo(f"error: {exc}", err=True)
        code = ExitCode.USAGE_ERROR
    sys.exit(int(code or 0))


def _fail(exc: MedAgentRxError) -> typer.Exit:
    typer.echo(f"error: {exc}", err=True)
    return typer.Exit(ExitCode.USAGE_ERROR)


@app.callback()
def main() -> None:
    """Check every model update against its approved change plan."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"medagentrx {__version__}")


@app.command()
def schema() -> None:
    """Print the JSON Schema of the change plan."""
    typer.echo(plan_json_schema_text(), nl=False)


@app.command()
def validate(
    plan: Annotated[Path, typer.Argument(help="Path to change-plan.yaml.", metavar="PLAN")],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Also print the plan fingerprint.")
    ] = False,
) -> None:
    """Check a change plan against the schema and its own logic."""
    try:
        loaded = load_plan_with_warnings(plan)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    header = loaded.plan.plan
    typer.echo(f"valid: {header.id} revision {header.revision}")
    for warning in loaded.warnings:
        typer.echo(f"warning: {warning}")
    if verbose:
        typer.echo(f"plan fingerprint: {plan_fingerprint(loaded.plan)}")


MaxFileBytesOption = Annotated[
    int, typer.Option("--max-file-bytes", min=1, help="Largest input file accepted, in bytes.")
]
MaxRowsOption = Annotated[
    int, typer.Option("--max-rows", min=1, help="Largest number of rows in one input file.")
]


@app.command()
def fingerprint(
    test_preds: Annotated[
        Path, typer.Argument(help="Prediction file on the locked test set.", metavar="TEST_PREDS")
    ],
    max_file_bytes: MaxFileBytesOption = DEFAULT_MAX_FILE_BYTES,
    max_rows: MaxRowsOption = DEFAULT_MAX_ROWS,
) -> None:
    """Print the canonical fingerprint of the locked test set."""
    limits = Limits(max_file_bytes=max_file_bytes, max_rows=max_rows)
    try:
        digest = fingerprint_file(test_preds, limits=limits)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    typer.echo(digest)


@app.command()
def check(
    plan: Annotated[Path, typer.Argument(help="Path to change-plan.yaml.", metavar="PLAN")],
    candidate: Annotated[Path, typer.Option("--candidate", help="Candidate predictions.")],
    previous: Annotated[
        Path, typer.Option("--previous", help="Predictions of the version replaced.")
    ],
    anchor: Annotated[
        Path, typer.Option("--anchor", help="Predictions of the authorised version.")
    ],
    manifest: Annotated[Path, typer.Option("--manifest", help="Training data manifest.")],
    model_meta: Annotated[Path, typer.Option("--model-meta", help="Candidate model.yaml.")],
    ledger: Annotated[Path, typer.Option("--ledger", help="Decision ledger, created if missing.")],
    out: Annotated[Path, typer.Option("--out", help="Directory for the reports.")],
    seed: Annotated[int, typer.Option("--seed", help="Seed for every resampling step.")] = 0,
    replicates: Annotated[
        int, typer.Option("--replicates", min=100, help="Bootstrap replicates.")
    ] = 2000,
    max_file_bytes: MaxFileBytesOption = DEFAULT_MAX_FILE_BYTES,
    max_rows: MaxRowsOption = DEFAULT_MAX_ROWS,
) -> None:
    """Check one model update against its change plan and record the decision.

    Exit codes: 0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN, 3 input or usage error.
    """
    from medagentrx.engine import evaluate
    from medagentrx.ledger import append, exclusive, load_history
    from medagentrx.report.json_report import write_json

    limits = Limits(max_file_bytes=max_file_bytes, max_rows=max_rows)
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with exclusive(ledger):
            evaluation = evaluate(
                plan=plan,
                candidate=candidate,
                previous=previous,
                anchor=anchor,
                manifest=manifest,
                model_meta=model_meta,
                history=load_history(ledger),
                seed=seed,
                n_replicates=replicates,
                limits=limits,
            )
            entry = None
            if evaluation.plan_id is not None:
                entry = append(ledger, evaluation, already_locked=True)
        ledger_info = None if entry is None else {"seq": entry["seq"], "hash": entry["hash"]}
        report = write_json(out, evaluation, ledger=ledger_info)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    _print_summary(evaluation)
    typer.echo(f"report: {report}")
    if entry is not None:
        typer.echo(f"ledger: entry {entry['seq']} {entry['hash'][:12]}")
    raise typer.Exit(evaluation.exit_code)


def _print_summary(evaluation: Evaluation) -> None:
    typer.echo(f"verdict: {evaluation.verdict.value}")
    for finding in evaluation.findings:
        if finding.status.value in ("fail", "warn"):
            typer.echo(f"  {finding.status.value.upper():4} {finding.check_id}: {finding.message}")


ledger_app = typer.Typer(help="Inspect and verify the decision ledger.", no_args_is_help=True)
app.add_typer(ledger_app, name="ledger")


@ledger_app.command("verify")
def ledger_verify(
    ledger: Annotated[Path, typer.Argument(help="Path to ledger.jsonl.", metavar="LEDGER")],
    head: Annotated[
        Path | None, typer.Option("--head", help="Head file. Defaults to LEDGER.head.")
    ] = None,
) -> None:
    """Recompute the hash chain and compare it with the recorded head.

    Exit codes: 0 intact, 1 fails verification, 3 input or usage error.
    """
    from medagentrx.ledger import verify

    try:
        result = verify(ledger, head_path=head)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    if result.ok:
        typer.echo(f"ok: {result.entries} entries, head {result.head}")
        return
    typer.echo(f"ledger fails verification: {ledger}", err=True)
    for problem in result.problems:
        typer.echo(f"  - {problem}", err=True)
    raise typer.Exit(1)


@ledger_app.command("show")
def ledger_show(
    ledger: Annotated[Path, typer.Argument(help="Path to ledger.jsonl.", metavar="LEDGER")],
) -> None:
    """List every evaluation in the ledger, oldest first."""
    from medagentrx.ledger import read_entries, summarize

    try:
        entries = read_entries(ledger)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    if not entries:
        typer.echo("the ledger is empty")
        return
    header = f"{'seq':>4}  {'recorded':<19} {'version':<10} {'verdict':<12} {'alpha':>8}  checks"
    typer.echo(header)
    for e in entries:
        used = e.get("alpha", {}).get("used")
        alpha = "-" if used is None else f"{used:.5f}"
        failed = ",".join(e.get("failed_checks", [])) or "-"
        typer.echo(
            f"{e.get('seq', '?'):>4}  {str(e.get('recorded_at', ''))[:19]:<19} "
            f"{e.get('candidate_version', '')!s:<10} {e.get('verdict', '')!s:<12} "
            f"{alpha:>8}  {failed}"
        )
    history = summarize(entries)
    typer.echo(
        f"looks used: {history.looks_used}; releases: {len(history.releases)}; "
        f"alpha spent: {history.alpha.spent if history.alpha else 0.0:.5f}"
    )


@app.command()
def init(
    out: Annotated[Path, typer.Option("--out", "-o", help="Where to write the plan.")] = Path(
        "change-plan.yaml"
    ),
    defaults: Annotated[
        bool, typer.Option("--defaults", help="Use default answers without prompting.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write a commented starter change-plan.yaml."""
    if out.is_symlink():
        typer.echo(f"error: {out} is a symbolic link; refusing to write through it", err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    if out.exists() and not force:
        typer.echo(f"error: {out} exists; use --force to overwrite it", err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    answers = PlanAnswers() if defaults else _ask()
    text = render_plan_template(answers)
    try:
        loaded = parse_plan_text(text, source=str(out))
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {out}")
    for warning in loaded.warnings:
        typer.echo(f"warning: {warning}")


def _ask() -> PlanAnswers:
    base = PlanAnswers()
    plan_id = typer.prompt("Plan identifier", default=base.plan_id)
    device = typer.prompt("Device or model name", default=base.device)
    anchor = typer.prompt("Authorised (anchor) model version", default=base.anchor_version)
    authorised = typer.prompt("Date the plan was authorised (YYYY-MM-DD)", default=base.authorised)
    intended_file = typer.prompt(
        "Intended-use statement file (blank to fill in later)", default="", show_default=False
    )
    intended_sha = base.intended_use_sha256
    if intended_file:
        try:
            intended_sha = hashlib.sha256(Path(intended_file).read_bytes()).hexdigest()
        except OSError as exc:
            typer.echo(f"error: {intended_file}: cannot be read ({exc.strerror})", err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR) from None
    max_updates = typer.prompt("Updates allowed under the plan", default=base.max_updates)
    max_evaluations = typer.prompt(
        "Looks allowed at the locked test set", default=base.max_evaluations
    )
    alpha_total = typer.prompt("Total alpha across all updates", default=base.alpha_total)
    threshold = typer.prompt("Operating risk threshold", default=base.operating_threshold)
    subgroups = typer.prompt(
        "Subgroup columns, comma separated (blank for none)", default=",".join(base.subgroups)
    )
    return PlanAnswers(
        plan_id=plan_id,
        device=device,
        anchor_version=anchor,
        authorised=authorised,
        intended_use_sha256=intended_sha,
        max_updates=max_updates,
        max_evaluations=max_evaluations,
        alpha_total=alpha_total,
        operating_threshold=threshold,
        subgroups=[s.strip() for s in subgroups.split(",") if s.strip()],
    )
