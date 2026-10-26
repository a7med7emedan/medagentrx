# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0

import json
import re
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any

import pytest

from medagentrx.errors import InputError
from medagentrx.notify import (
    Notice,
    check_url,
    detect_format,
    notice_for,
    payload,
    send,
    should_send,
)

NOTICE = Notice("qc run", "OUTSIDE_PLAN", "P", 2, "2.0.0", ("LIVE-004",), ("LIVE-003",))


def test_notice_text_and_summary() -> None:
    assert NOTICE.text == (
        "MedAgentRx qc run: OUTSIDE_PLAN for version 2.0.0 (plan P revision 2). "
        "Failed: LIVE-004. Warnings: LIVE-003"
    )
    plain = Notice("check", "OUTSIDE_PLAN", None, None, None)
    assert plain.text == "MedAgentRx check: OUTSIDE_PLAN for version ? (no plan)"
    summary = NOTICE.summary()
    assert summary["source"] == "medagentrx"
    assert summary["failed_checks"] == ["LIVE-004"]


def test_notice_for_findings() -> None:
    findings = [
        SimpleNamespace(check_id="A-1", status=SimpleNamespace(value="fail")),
        SimpleNamespace(check_id="A-2", status="warn"),
        SimpleNamespace(check_id="A-3", status="pass"),
    ]
    notice = notice_for(
        "check", "FAILED", plan_id="P", plan_revision=1, version="1.0", findings=findings
    )
    assert notice.failed_checks == ("A-1",)
    assert notice.warnings == ("A-2",)


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.slack.com/x",
        "ftp://example.org",
        "https:///nohost",
        "https://u:p@example.org/",
    ],
)
def test_only_plain_https(url: str) -> None:
    with pytest.raises(InputError):
        check_url(url)


def test_formats() -> None:
    assert detect_format("hooks.slack.com") == "slack"
    assert detect_format("prod-01.westeurope.logic.azure.com") == "teams"
    assert detect_format("x.webhook.office.com") == "teams"
    assert detect_format("example.org") == "json"
    assert payload(NOTICE, "slack") == {"text": NOTICE.text}
    teams = payload(NOTICE, "teams")
    assert teams["attachments"][0]["content"]["body"][0]["text"] == NOTICE.text
    assert payload(NOTICE, "json")["verdict"] == "OUTSIDE_PLAN"


def test_when_to_send() -> None:
    quiet = Notice("check", "ACCEPTED", "P", 1, "1")
    assert not should_send(quiet, "problems")
    assert should_send(quiet, "always")
    assert should_send(Notice("qc run", "IN_CONTROL", "P", 1, "1", (), ("LIVE-004",)), "problems")
    assert should_send(NOTICE, "problems")


class _Opener:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        assert timeout == 10.0
        self.requests.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        del args


def _install(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> _Opener:
    opener = _Opener(outcome)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    return opener


def test_send(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _install(monkeypatch, _Response(200))
    assert send("https://hooks.slack.com/services/T/B/x", NOTICE) == "hooks.slack.com"
    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert json.loads(request.data or b"") == {"text": NOTICE.text}  # type: ignore[arg-type]
    assert request.get_header("Content-type") == "application/json"
    send("https://example.org/hook", NOTICE, fmt="teams")
    assert "attachments" in json.loads(opener.requests[1].data or b"")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (_Response(302), "answered HTTP 302"),
        (
            urllib.error.HTTPError("https://e.org", 403, "no", {}, None),  # type: ignore[arg-type]
            "answered HTTP 403",
        ),
        (urllib.error.URLError("no route"), "cannot be reached (no route)"),
        (TimeoutError("slow"), "cannot be reached (slow)"),
    ],
)
def test_send_failures(monkeypatch: pytest.MonkeyPatch, outcome: Any, message: str) -> None:
    _install(monkeypatch, outcome)
    with pytest.raises(InputError, match=re.escape(message)):
        send("https://example.org/hook", NOTICE)


def test_redirects_are_refused() -> None:
    from medagentrx.notify import _NoRedirect

    _NoRedirect().redirect_request(None, None, 302, "", {}, "https://x")
