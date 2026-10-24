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
from typing import TYPE_CHECKING, Annotated, Any

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
    plans: Annotated[
        list[Path], typer.Argument(help="One or more change-plan.yaml files.", metavar="PLAN...")
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Also print the plan fingerprint.")
    ] = False,
) -> None:
    """Check change plans against the schema and their own logic.

    Exit codes: 0 every plan is valid, 3 at least one is not.
    """
    failed = False
    for plan in plans:
        prefix = f"{plan}: " if len(plans) > 1 else ""
        try:
            loaded = load_plan_with_warnings(plan)
        except MedAgentRxError as exc:
            typer.echo(f"error: {exc}", err=True)
            failed = True
            continue
        header = loaded.plan.plan
        typer.echo(f"{prefix}valid: {header.id} revision {header.revision}")
        for warning in loaded.warnings:
            typer.echo(f"{prefix}warning: {warning}")
        if verbose:
            typer.echo(f"{prefix}plan fingerprint: {plan_fingerprint(loaded.plan)}")
    if failed:
        raise typer.Exit(ExitCode.USAGE_ERROR)


SigningKeyOption = Annotated[
    Path | None,
    typer.Option(
        "--signing-key",
        envvar="MEDAGENTRX_SIGNING_KEY",
        help="Ed25519 private key that signs the ledger head.",
    ),
]
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


@app.command("sample-size")
def sample_size(
    auroc: Annotated[
        float, typer.Option("--auroc", help="Expected AUROC of the deployed version.")
    ],
    prevalence: Annotated[
        float, typer.Option("--prevalence", help="Share of positives in the test population.")
    ],
    plan: Annotated[
        Path | None,
        typer.Argument(
            help="Change plan to read the margin, level and power from.", metavar="PLAN"
        ),
    ] = None,
    margin: Annotated[
        float | None, typer.Option("--margin", help="Non-inferiority margin; overrides the plan.")
    ] = None,
    alpha: Annotated[
        float | None,
        typer.Option("--alpha", help="One-sided level per update; overrides the plan."),
    ] = None,
    power: Annotated[
        float | None, typer.Option("--power", help="Target power; overrides the plan.")
    ] = None,
    correlation: Annotated[
        float,
        typer.Option(
            "--correlation",
            help="Correlation of the two AUROC estimates; 0.5 to 0.8 is typical for retraining.",
        ),
    ] = 0.6,
    true_difference: Annotated[
        float,
        typer.Option("--true-difference", help="AUROC change the candidate is expected to have."),
    ] = 0.0,
) -> None:
    """Size the locked test set so the AUROC criterion has the power the plan asks for."""
    from medagentrx.plan import load_plan
    from medagentrx.plan.models import NonInferiorityCriterion
    from medagentrx.stats.alpha import initial_state, next_alpha
    from medagentrx.stats.power import required_test_size

    min_events = None
    try:
        if plan is not None:
            loaded = load_plan(plan)
            perf = loaded.performance
            margins = [
                c.margin
                for c in perf.criteria
                if isinstance(c, NonInferiorityCriterion) and c.metric == "auroc"
            ]
            if margin is None and margins:
                margin = min(margins)
            if alpha is None:
                alpha = next_alpha(
                    initial_state(perf.alpha_spending, perf.alpha_total, loaded.max_updates)
                )
            if power is None and perf.power is not None:
                power = perf.power.min_power
            min_events = perf.subgroups.min_events if perf.subgroups else None
        if margin is None or alpha is None:
            typer.echo(
                "error: give a plan with an AUROC criterion, or --margin and --alpha", err=True
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)
        power = 0.80 if power is None else power
        size = required_test_size(
            auc=auroc,
            prevalence=prevalence,
            margin=margin,
            alpha=alpha,
            power=power,
            correlation=correlation,
            true_difference=true_difference,
        )
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    typer.echo(
        f"Locked test set: at least {size.n:,} rows "
        f"({size.n_pos:,} positives, {size.n_neg:,} negatives)"
    )
    typer.echo(
        f"Power {size.power:.3f} to show non-inferiority at margin {margin:g}, "
        f"one-sided level {alpha:.4g}"
    )
    typer.echo(
        f"Assumes AUROC {auroc:g}, prevalence {prevalence:g}, correlation {correlation:g} "
        f"and a true difference of {true_difference:+g} (Hanley and McNeil variance)"
    )
    if min_events is not None:
        typer.echo(
            f"Every subgroup level also needs at least {min_events} positives and "
            f"{min_events} negatives"
        )


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
    report_format: Annotated[
        str, typer.Option("--format", help="Report formats, comma separated: html,json,md,junit.")
    ] = "html,json,md,junit",
    signing_key: SigningKeyOption = None,
    max_file_bytes: MaxFileBytesOption = DEFAULT_MAX_FILE_BYTES,
    max_rows: MaxRowsOption = DEFAULT_MAX_ROWS,
) -> None:
    """Check one model update against its change plan and record the decision.

    Exit codes: 0 ACCEPTED, 1 FAILED, 2 OUTSIDE_PLAN, 3 input or usage error.
    """
    from medagentrx.api import check as run_check
    from medagentrx.report.writer import parse_formats

    limits = Limits(max_file_bytes=max_file_bytes, max_rows=max_rows)
    try:
        result = run_check(
            plan=plan,
            candidate=candidate,
            previous=previous,
            anchor=anchor,
            manifest=manifest,
            model_meta=model_meta,
            ledger=ledger,
            out=out,
            seed=seed,
            n_replicates=replicates,
            formats=parse_formats(report_format),
            limits=limits,
            signing_key=signing_key,
        )
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    evaluation, entry, written = result.evaluation, result.ledger_entry, result.reports
    _print_summary(evaluation)
    for path in written.values():
        typer.echo(f"report: {path}")
    if entry is not None:
        typer.echo(f"ledger: entry {entry['seq']} {entry['hash'][:12]}")
    raise typer.Exit(evaluation.exit_code)


def _print_summary(evaluation: Evaluation) -> None:
    typer.echo(f"verdict: {evaluation.verdict.value}")
    for finding in evaluation.findings:
        if finding.status.value in ("fail", "warn"):
            typer.echo(f"  {finding.status.value.upper():4} {finding.check_id}: {finding.message}")


ledger_app = typer.Typer(
    help="Verify, inspect and add records to the decision ledger.", no_args_is_help=True
)
app.add_typer(ledger_app, name="ledger")


@ledger_app.command("verify")
def ledger_verify(
    ledger: Annotated[Path, typer.Argument(help="Path to ledger.jsonl.", metavar="LEDGER")],
    head: Annotated[
        Path | None, typer.Option("--head", help="Head file. Defaults to LEDGER.head.")
    ] = None,
    public_key: Annotated[
        Path | None,
        typer.Option("--public-key", help="Require a valid head signature by this public key."),
    ] = None,
    plan: Annotated[
        Path | None,
        typer.Option("--plan", help="Change plan whose pinned signing key the head must match."),
    ] = None,
) -> None:
    """Recompute the hash chain and compare it with the recorded head.

    Exit codes: 0 intact, 1 fails verification, 3 input or usage error.
    """
    from medagentrx.ledger import verify
    from medagentrx.plan import load_plan
    from medagentrx.signing import key_fingerprint, load_public_key

    try:
        key = load_public_key(public_key) if public_key is not None else None
        pinned = load_plan(plan).ledger_signing_key_sha256 if plan is not None else None
        result = verify(ledger, head_path=head, public_key=key)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    fingerprint = key_fingerprint(key) if key is not None else None
    if pinned is not None and fingerprint != pinned:
        typer.echo(
            "ledger fails verification: the plan pins signing key "
            f"{pinned[:16]}, but {'no key' if key is None else 'key ' + str(fingerprint)[:16]} "
            "was given",
            err=True,
        )
        raise typer.Exit(1)
    if result.ok:
        signed = f", signature valid (key {str(fingerprint)[:16]})" if key is not None else ""
        typer.echo(f"ok: {result.entries} entries, head {result.head}{signed}")
        return
    typer.echo(f"ledger fails verification: {ledger}", err=True)
    for problem in result.problems:
        typer.echo(f"  - {problem}", err=True)
    raise typer.Exit(1)


@ledger_app.command("keygen")
def ledger_keygen(
    out: Annotated[Path, typer.Option("--out", help="Folder for the key pair.")] = Path(),
) -> None:
    """Create an Ed25519 key pair for signing ledger heads.

    Keep ledger-signing.key secret, for example as a CI secret. Commit
    ledger-signing.pub, and put the printed fingerprint in the plan as
    ledger_signing_key_sha256. Set MEDAGENTRX_SIGNING_KEY_PASSPHRASE to encrypt
    the private key.
    """
    from medagentrx.signing import generate_key_pair

    try:
        fingerprint = generate_key_pair(out / "ledger-signing.key", out / "ledger-signing.pub")
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    typer.echo(f"wrote {out / 'ledger-signing.key'} (secret) and {out / 'ledger-signing.pub'}")
    typer.echo(f'ledger_signing_key_sha256: "{fingerprint}"')


@ledger_app.command("release")
def ledger_release(
    ledger: Annotated[Path, typer.Argument(help="Path to ledger.jsonl.", metavar="LEDGER")],
    version: Annotated[str, typer.Option("--version", help="Accepted version put into service.")],
    qc_expected: Annotated[
        Path | None,
        typer.Option(
            "--qc-expected",
            help="Expected scores of this version on the deployment QC control set.",
        ),
    ] = None,
    signing_key: SigningKeyOption = None,
) -> None:
    """Record that an accepted version was put into service.

    With --qc-expected, the release record also binds the version's expected
    QC scores, so deployment QC can check it without a change to the plan.
    """
    from medagentrx.io.hashing import sha256_file
    from medagentrx.io.paths import resolve_input
    from medagentrx.io.predictions import load_scores
    from medagentrx.ledger import record
    from medagentrx.signing import load_private_key

    try:
        key = load_private_key(signing_key) if signing_key is not None else None
        details = {}
        if qc_expected is not None:
            load_scores(qc_expected)
            details["qc_expected_sha256"] = sha256_file(resolve_input(qc_expected))
        entry = record(ledger, "release", version, details=details, signing_key=key)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    typer.echo(f"recorded the release of {version} as entry {entry['seq']}")
    if qc_expected is not None:
        typer.echo(f"with expected QC scores {details['qc_expected_sha256'][:12]}")


@ledger_app.command("show")
def ledger_show(
    ledger: Annotated[Path, typer.Argument(help="Path to ledger.jsonl.", metavar="LEDGER")],
) -> None:
    """List every entry in the ledger, oldest first."""
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
        if e.get("kind") in ("release", "card"):
            failed = f"{e['kind']} of the accepted entry {e.get('evaluation', {}).get('seq')}"
        if e.get("kind") == "qc":
            bias = (e.get("qc") or {}).get("bias")
            measured = f"bias {bias:.3g}" if isinstance(bias, int | float) else "not measured"
            failed = f"qc: {measured}; {failed}"
        version = e.get("candidate_version") or e.get("model_version", "")
        typer.echo(
            f"{e.get('seq', '?'):>4}  {str(e.get('recorded_at', ''))[:19]:<19} "
            f"{version!s:<10} {e.get('verdict', '')!s:<12} "
            f"{alpha:>8}  {failed}"
        )
    history = summarize(entries)
    qc_runs = [e for e in entries if e.get("kind") == "qc"]
    rejected = sum(1 for e in qc_runs if e.get("verdict") != "IN_CONTROL")
    typer.echo(
        f"looks used: {history.looks_used}; accepted: {len(history.releases)}; "
        f"in service: {len(history.deployed)}; "
        f"alpha spent: {history.alpha.spent if history.alpha else 0.0:.5f}; "
        f"QC runs: {len(qc_runs)} ({rejected} outside the plan)"
    )


qc_app = typer.Typer(
    help="Deployment QC: control samples scored by the live system.", no_args_is_help=True
)
app.add_typer(qc_app, name="qc")


@qc_app.command("init")
def qc_init_command(
    control_inputs: Annotated[
        Path,
        typer.Option("--control-inputs", help="Raw control records with a row_id column."),
    ],
    scores: Annotated[
        Path, typer.Option("--scores", help="Expected scores of VERSION on the control set.")
    ],
    version: Annotated[str, typer.Option("--version", help="Version the scores belong to.")],
    test_set: Annotated[
        Path | None,
        typer.Option("--test-set", help="Locked test-set predictions; control ids must differ."),
    ] = None,
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", help="Training manifest; control ids must differ."),
    ] = None,
    plan: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            help="Plan with a deployment_qc block: print the new version's release command.",
        ),
    ] = None,
    tolerance: Annotated[
        float,
        typer.Option(
            "--tolerance", min=1e-12, max=1.0, help="Largest per-record difference allowed."
        ),
    ] = 1.0e-6,
    max_file_bytes: MaxFileBytesOption = DEFAULT_MAX_FILE_BYTES,
    max_rows: MaxRowsOption = DEFAULT_MAX_ROWS,
) -> None:
    """Fingerprint a control set and print the deployment_qc block for the plan.

    After a new release, run it again with --plan and --version: it checks the
    control set is the plan's and prints the ledger release command that records
    the new version's expected scores.
    """
    from medagentrx.qc import qc_block_yaml, qc_init, qc_release_command

    limits = Limits(max_file_bytes=max_file_bytes, max_rows=max_rows)
    try:
        init = qc_init(
            control_inputs=control_inputs,
            scores=scores,
            version=version,
            test_set=test_set,
            manifest=manifest,
            plan=plan,
            limits=limits,
        )
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    checked = " and ".join(init.checked_against) or "nothing; pass --test-set and --manifest"
    typer.echo(f"{init.records} control records; disjointness checked against {checked}", err=True)
    if plan is not None:
        typer.echo(
            f"expected scores of {version}: {init.expected_sha256}; record them with the "
            "release, so the plan stays unchanged:",
            err=True,
        )
        typer.echo(qc_release_command(init, scores), nl=False)
    else:
        typer.echo(qc_block_yaml(init, tolerance=tolerance), nl=False)


@qc_app.command("run")
def qc_run_command(
    plan: Annotated[Path, typer.Argument(help="Path to change-plan.yaml.", metavar="PLAN")],
    scores: Annotated[
        Path, typer.Option("--scores", help="Live system's scores on the control set.")
    ],
    expected: Annotated[
        Path, typer.Option("--expected", help="Expected scores of the model version.")
    ],
    model_version: Annotated[
        str, typer.Option("--model-version", help="Version the live system reports.")
    ],
    ledger: Annotated[Path, typer.Option("--ledger", help="Decision ledger, created if missing.")],
    out: Annotated[Path, typer.Option("--out", help="Directory for the reports.")],
    control_inputs: Annotated[
        Path | None,
        typer.Option("--control-inputs", help="Raw control file, checked against the plan."),
    ] = None,
    report_format: Annotated[
        str, typer.Option("--format", help="Report formats, comma separated: html,json,md,junit.")
    ] = "html,json,md,junit",
    signing_key: SigningKeyOption = None,
    max_file_bytes: MaxFileBytesOption = DEFAULT_MAX_FILE_BYTES,
    max_rows: MaxRowsOption = DEFAULT_MAX_ROWS,
) -> None:
    """Judge one QC run of the live system and record it.

    Exit codes: 0 IN_CONTROL, 2 OUTSIDE_PLAN, 3 input or usage error.
    """
    from medagentrx.api import qc as run_qc_api
    from medagentrx.report.writer import parse_formats

    limits = Limits(max_file_bytes=max_file_bytes, max_rows=max_rows)
    try:
        result = run_qc_api(
            plan=plan,
            scores=scores,
            expected=expected,
            model_version=model_version,
            ledger=ledger,
            out=out,
            control_inputs=control_inputs,
            formats=parse_formats(report_format),
            limits=limits,
            signing_key=signing_key,
        )
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    run = result.run
    typer.echo(f"qc verdict: {run.verdict.value}")
    for finding in run.findings:
        if finding.status.value in ("fail", "warn"):
            typer.echo(f"  {finding.status.value.upper():4} {finding.check_id}: {finding.message}")
    for note in run.notes:
        typer.echo(f"  NOTE {note}")
    for path in result.reports.values():
        typer.echo(f"report: {path}")
    entry = result.ledger_entry
    typer.echo(f"ledger: entry {entry['seq']} {entry['hash'][:12]}")
    raise typer.Exit(run.exit_code)


@app.command("render-plan")
def render_plan(
    plan: Annotated[Path, typer.Argument(help="Path to change-plan.yaml.", metavar="PLAN")],
    out: Annotated[Path, typer.Option("--out", help="Directory for the PCCP document.")],
    doc_format: Annotated[
        str, typer.Option("--format", help="Document formats, comma separated: md,html.")
    ] = "md,html",
) -> None:
    """Write the PCCP document (FDA components and EU cross-reference) from the plan."""
    from medagentrx.document import to_html, to_markdown
    from medagentrx.io.paths import safe_output_path
    from medagentrx.plan import load_plan
    from medagentrx.render_plan import build_document

    renderers = {"md": to_markdown, "html": to_html}
    chosen = list(dict.fromkeys(f.strip() for f in doc_format.split(",") if f.strip()))
    if not chosen or any(f not in renderers for f in chosen):
        typer.echo(f"error: --format must list md and/or html, got {doc_format!r}", err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    try:
        document = build_document(load_plan(plan))
        out.mkdir(parents=True, exist_ok=True)
        for name in chosen:
            target = safe_output_path(out, f"pccp-document.{name}")
            target.write_text(renderers[name](document), encoding="utf-8")
            typer.echo(f"wrote {target}")
    except MedAgentRxError as exc:
        raise _fail(exc) from None


@app.command()
def card(
    plan: Annotated[Path, typer.Argument(help="Path to change-plan.yaml.", metavar="PLAN")],
    report: Annotated[Path, typer.Option("--report", help="report.json of an accepted update.")],
    out: Annotated[Path, typer.Option("--out", help="Model card file to create or update.")],
    ledger: Annotated[
        Path | None,
        typer.Option("--ledger", help="Record the card update in this ledger (DOC-001)."),
    ] = None,
    signing_key: SigningKeyOption = None,
) -> None:
    """Add or replace this version's performance section in the model card."""
    from medagentrx.card import load_report, update_card
    from medagentrx.io.hashing import sha256_file
    from medagentrx.ledger import check_record, record, signing_policy
    from medagentrx.plan import load_plan

    try:
        change_plan = load_plan(plan)
        loaded = load_report(report)
        key = signing_policy(change_plan, signing_key) if ledger is not None else None
        if ledger is not None:
            check_record(
                ledger,
                "card",
                loaded["candidate_version"],
                candidate_sha256=loaded["inputs"].get("candidate"),
            )
        written = update_card(out, change_plan, loaded)
        if ledger is not None:
            record(
                ledger,
                "card",
                loaded["candidate_version"],
                details={"card_sha256": sha256_file(written)},
                candidate_sha256=loaded["inputs"].get("candidate"),
                signing_key=key,
            )
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    typer.echo(f"updated {written}")
    if ledger is not None:
        typer.echo(f"recorded the card update for {loaded['candidate_version']} in {ledger}")


@app.command()
def demo(
    out: Annotated[
        Path, typer.Option("--out", help="Directory for the scenario files and reports.")
    ] = Path("medagentrx-demo"),
    scenario: Annotated[
        list[str] | None,
        typer.Option("--scenario", help="Run only this scenario. Repeat for more."),
    ] = None,
    replicates: Annotated[
        int, typer.Option("--replicates", min=100, help="Bootstrap replicates.")
    ] = 2000,
) -> None:
    """Run the planted scenarios on synthetic data and check each verdict.

    The update scenarios come first, then the deployment QC scenarios.
    Exit codes: 0 every scenario gave its expected verdict, 1 otherwise.
    """
    from medagentrx.demo import QC_SCENARIOS, SCENARIOS, run_all, run_all_qc
    from medagentrx.ledger import read_entries
    from medagentrx.qc import QcRun
    from medagentrx.report.qc_report import write_qc_reports
    from medagentrx.report.writer import write_reports

    unknown = [n for n in scenario or [] if n not in SCENARIOS and n not in QC_SCENARIOS]
    if unknown:
        typer.echo(f"error: unknown scenario(s): {', '.join(unknown)}", err=True)
        typer.echo(f"choose from: {', '.join([*SCENARIOS, *QC_SCENARIOS])}", err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)
    update_names = [n for n in scenario or [] if n in SCENARIOS]
    qc_names = [n for n in scenario or [] if n in QC_SCENARIOS]

    def write(directory: Path, evaluation: Evaluation, entry: dict[str, Any] | None) -> None:
        ledger = directory / "ledger.jsonl"
        if not ledger.exists():
            ledger = directory.parent / "ledger.jsonl"
        entries = read_entries(ledger) if ledger.exists() else []
        write_reports(directory / "report", evaluation, entry=entry, entries=entries)

    def write_qc(directory: Path, run: QcRun, entry: dict[str, Any]) -> None:
        entries = read_entries(directory / "ledger.jsonl")
        write_qc_reports(directory / "report", run, entry=entry, entries=entries)

    typer.echo("Synthetic data only. No real patient data is used.")
    results: list[Any] = []
    if update_names or not qc_names:
        results += run_all(out, names=update_names or None, n_replicates=replicates, on_step=write)
    if qc_names or not update_names:
        results += run_all_qc(out, names=qc_names or None, on_step=write_qc)
    width = max(len(r.scenario.name) for r in results) + 1
    typer.echo(
        f"{'scenario':<{width}} {'steps':>5}  {'expected':<14} {'got':<14} {'checks':<17} ok"
    )
    for result in results:
        rows: list[list[Any]] = []
        for step in result.steps:
            expected = step.step.expected
            got = step.verdict
            row = [
                getattr(expected, "value", expected),
                getattr(got, "value", got),
                ",".join(step.failed)
                or ("warn " + ",".join(step.warnings) if step.warnings else "-"),
                "yes" if step.ok else "NO",
            ]
            if rows and rows[-1][1:] == row:
                rows[-1][0] += 1
            else:
                rows.append([1, *row])
        for count, expected, got, checks, mark in rows:
            name = result.scenario.name
            typer.echo(f"{name:<{width}} {count:>5}  {expected:<14} {got:<14} {checks:<17} {mark}")
    passed = sum(r.ok for r in results)
    typer.echo(f"{passed} of {len(results)} scenarios gave their expected verdict. Files: {out}")
    raise typer.Exit(0 if passed == len(results) else 1)


@app.command()
def serve(
    ledger: Annotated[Path, typer.Option("--ledger", help="Decision ledger to show.")],
    reports: Annotated[
        Path | None, typer.Option("--reports", help="Folder searched for report.json files.")
    ] = None,
    plan: Annotated[
        Path | None, typer.Option("--plan", help="Change plan, for budget limits.")
    ] = None,
    host: Annotated[str, typer.Option("--host", help="Address to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port to bind.")] = 8765,
) -> None:
    """Serve a read-only dashboard of the ledger and reports (needs the web extra)."""
    try:
        import uvicorn

        from medagentrx.web.app import bind_warning, create_app
    except ImportError:
        typer.echo(
            "error: the dashboard needs the web extra: pip install 'medagentrx[web]'", err=True
        )
        raise typer.Exit(ExitCode.USAGE_ERROR) from None
    try:
        application = create_app(ledger=ledger, reports=reports, plan=plan)
    except MedAgentRxError as exc:
        raise _fail(exc) from None
    warning = bind_warning(host)
    if warning:
        typer.echo(warning, err=True)
    typer.echo(f"MedAgentRx dashboard on http://{host}:{port} (read-only, press Ctrl+C to stop)")
    uvicorn.run(application, host=host, port=port, log_level="warning", server_header=False)


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
