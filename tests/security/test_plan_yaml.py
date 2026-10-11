# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Hostile plan files must be refused before any value is used."""

from collections.abc import Callable
from pathlib import Path

import pytest

from medagentrx import PlanError, load_plan
from medagentrx.plan import parse_plan_text
from tests.conftest import EXAMPLE_PLAN

BILLION_LAUGHS = """
a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: [*d,*d,*d,*d,*d,*d,*d,*d,*d]
"""


def _refused(text: str) -> PlanError:
    with pytest.raises(PlanError) as exc:
        parse_plan_text(text, source="hostile.yaml")
    return exc.value


def test_billion_laughs_is_refused() -> None:
    assert "anchors and aliases are not allowed" in str(_refused(BILLION_LAUGHS))


def test_python_object_tag_is_refused_without_running(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    text = f"pccp_version: !!python/object/apply:os.system ['touch {marker}']\n"
    error = _refused(text)
    assert "not valid YAML" in error.summary
    assert "python/object/apply" in str(error)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a: 1\na: 2\n", "line 2: duplicate key 'a'"),
        ("- 1\n- 2\n", "must be a mapping at the top level"),
        ("a: 1\n---\nb: 2\n", "not valid YAML"),
        ("a: .nan\n", "a: NaN and infinity are not allowed"),
        ("a: [1, .inf]\n", "a[1]: NaN and infinity are not allowed"),
        ("a: !!binary aGVsbG8=\n", "unsupported YAML type bytes"),
        ("a: !!set {x, y}\n", "unsupported YAML type set"),
        ("1: one\n", "keys must be strings"),
        ("? [a, b]\n: c\n", "mapping keys must be plain values"),
        ("a: !custom 1\n", "not valid YAML"),
        ("a: [unclosed\n", "not valid YAML"),
        ("a: \x00\n", "unacceptable character"),
        pytest.param("[" * 5000 + "]" * 5000, "nesting is too deep", id="deep-nesting"),
    ],
)
def test_hostile_yaml_is_refused(text: str, message: str) -> None:
    assert message in str(_refused(text))


def test_timestamps_and_explicit_dates(write_plan: Callable[[object], Path]) -> None:
    text = EXAMPLE_PLAN.read_text(encoding="utf-8").replace(
        "authorised: 2026-03-01", "authorised: !!timestamp 2026-03-01"
    )
    assert load_plan(write_plan(text)).plan.authorised.isoformat() == "2026-03-01"


def test_oversized_plan_is_refused_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "big.yaml"
    path.write_text("a: " + "x" * 2000 + "\n", encoding="utf-8")
    with pytest.raises(PlanError, match="larger than the limit of 1000 bytes"):
        load_plan(path, max_bytes=1000)


def test_non_utf8_plan_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "latin1.yaml"
    path.write_bytes("device: caf\xe9\n".encode("latin-1"))
    with pytest.raises(PlanError, match="not UTF-8 text"):
        load_plan(path)


def test_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="not a regular file"):
        load_plan(tmp_path)


def test_unreadable_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "secret.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    path.chmod(0)
    try:
        if path.stat().st_mode & 0o400 or _can_read(path):
            pytest.skip("permissions are not enforced for this user")
        with pytest.raises(PlanError, match="cannot be read"):
            load_plan(path)
    finally:
        path.chmod(0o600)


def _can_read(path: Path) -> bool:
    try:
        path.read_bytes()
    except OSError:
        return False
    return True


def test_html_in_plan_strings_is_kept_as_data(write_plan: Callable[[object], Path]) -> None:
    text = EXAMPLE_PLAN.read_text(encoding="utf-8").replace(
        'device: "Sepsis risk score v2"', 'device: "<script>alert(1)</script>"'
    )
    assert load_plan(write_plan(text)).plan.device == "<script>alert(1)</script>"
