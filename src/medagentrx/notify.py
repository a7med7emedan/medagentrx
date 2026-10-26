# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Post a short message to a chat or incident webhook after a decision.

This is the only network call MedAgentRx makes, and it is off unless a
webhook URL is given. The message carries the verdict, the plan, the version
and the identifiers of failed checks, never any data rows. The URL must use
HTTPS, redirects are refused, and the URL is never printed or recorded,
because a webhook URL is a secret.

Slack and Microsoft Teams (Workflows) webhooks get their own message shape;
any other URL receives a JSON summary. A failed notification is reported as
a warning and never changes the verdict or the exit code.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from medagentrx import __version__
from medagentrx.errors import InputError

NotifyFormat = Literal["auto", "slack", "teams", "json"]
NotifyWhen = Literal["problems", "always"]
ENV_URL = "MEDAGENTRX_NOTIFY_URL"
TIMEOUT_SECONDS = 10.0
GOOD_VERDICTS = frozenset({"ACCEPTED", "IN_CONTROL"})


@dataclass(frozen=True)
class Notice:
    """What one notification says.

    Attributes:
        command: ``check`` or ``qc run``.
        verdict: The verdict, for example ``OUTSIDE_PLAN``.
        plan_id: Plan identifier, or None when the plan was invalid.
        plan_revision: Plan revision.
        version: Model version checked.
        failed_checks: Identifiers of failed checks.
        warnings: Identifiers of checks that warned.
    """

    command: str
    verdict: str
    plan_id: str | None
    plan_revision: int | None
    version: str | None
    failed_checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """One line for people."""
        plan = f"plan {self.plan_id} revision {self.plan_revision}" if self.plan_id else "no plan"
        line = (
            f"MedAgentRx {self.command}: {self.verdict} for version {self.version or '?'} ({plan})"
        )
        if self.failed_checks:
            line += f". Failed: {', '.join(self.failed_checks)}"
        if self.warnings:
            line += f". Warnings: {', '.join(self.warnings)}"
        return line

    def summary(self) -> dict[str, Any]:
        """JSON summary sent to generic webhooks."""
        return {
            "source": "medagentrx",
            "tool_version": __version__,
            "command": self.command,
            "verdict": self.verdict,
            "plan": {"id": self.plan_id, "revision": self.plan_revision},
            "version": self.version,
            "failed_checks": list(self.failed_checks),
            "warnings": list(self.warnings),
            "text": self.text,
        }


def check_url(url: str) -> urllib.parse.SplitResult:
    """Parse a webhook URL, refusing anything but HTTPS with a host.

    Raises:
        InputError: If the URL is not an HTTPS URL.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise InputError("the notification URL must be an https:// URL")
    if parts.username or parts.password:
        raise InputError("the notification URL must not carry a user name or password")
    return parts


def detect_format(host: str) -> Literal["slack", "teams", "json"]:
    """Message shape for a webhook host."""
    host = host.lower()
    if host == "hooks.slack.com":
        return "slack"
    if host.endswith((".webhook.office.com", ".logic.azure.com", ".powerplatform.com")):
        return "teams"
    return "json"


def payload(notice: Notice, fmt: Literal["slack", "teams", "json"]) -> dict[str, Any]:
    """Request body for one notification."""
    if fmt == "slack":
        return {"text": notice.text}
    if fmt == "teams":
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [{"type": "TextBlock", "text": notice.text, "wrap": True}],
                    },
                }
            ],
        }
    return notice.summary()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        del args, kwargs


def should_send(notice: Notice, when: NotifyWhen) -> bool:
    """True when ``notice`` must be sent under ``when``."""
    return when == "always" or notice.verdict not in GOOD_VERDICTS or bool(notice.warnings)


def send(
    url: str,
    notice: Notice,
    *,
    fmt: NotifyFormat = "auto",
    timeout: float = TIMEOUT_SECONDS,
) -> str:
    """Post ``notice`` to ``url`` and return the host it went to.

    Raises:
        InputError: If the URL is not HTTPS, or the webhook refuses or cannot be reached.
    """
    parts = check_url(url)
    host = parts.hostname or ""
    shape = detect_format(host) if fmt == "auto" else fmt
    body = json.dumps(payload(notice, shape)).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310  # https only, checked above
        urllib.parse.urlunsplit(parts),
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"medagentrx/{__version__}",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise InputError(f"the webhook at {host} answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise InputError(f"the webhook at {host} cannot be reached ({reason})") from None
    if not 200 <= status < 300:
        raise InputError(f"the webhook at {host} answered HTTP {status}")
    return host


def notice_for(
    command: str,
    verdict: str,
    *,
    plan_id: str | None,
    plan_revision: int | None,
    version: str | None,
    findings: Iterable[Any],
) -> Notice:
    """Build a notice from a verdict and its findings."""
    failed, warned = [], []
    for finding in findings:
        status = getattr(finding.status, "value", finding.status)
        if status == "fail":
            failed.append(finding.check_id)
        elif status == "warn":
            warned.append(finding.check_id)
    return Notice(command, verdict, plan_id, plan_revision, version, tuple(failed), tuple(warned))
