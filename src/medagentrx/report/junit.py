# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""JUnit XML: one test case per check, so CI test widgets show each check."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any


def render_junit(report: dict[str, Any]) -> str:
    """The report as a JUnit XML document."""
    checks = report["checks"]
    failures = sum(c["status"] == "fail" for c in checks)
    skipped = sum(c["status"] in ("skipped", "not_applicable") for c in checks)
    plan_id = report["plan"]["id"] or "invalid plan"
    version = report.get("candidate_version") or report.get("model_version") or ""
    prefix = "medagentrx qc" if report.get("kind") == "qc" else "medagentrx"
    suite_name = f"{prefix} {plan_id} {version}".strip()
    suites = ET.Element(
        "testsuites", name="medagentrx", tests=str(len(checks)), failures=str(failures)
    )
    suite = ET.SubElement(
        suites,
        "testsuite",
        name=suite_name,
        tests=str(len(checks)),
        failures=str(failures),
        errors="0",
        skipped=str(skipped),
        timestamp=report.get("evaluated_at") or report["run_at"],
    )
    properties = ET.SubElement(suite, "properties")
    for name, value in (("verdict", report["verdict"]), ("tool_version", report["tool_version"])):
        ET.SubElement(properties, "property", name=name, value=str(value))
    for c in checks:
        case = ET.SubElement(
            suite,
            "testcase",
            classname=f"medagentrx.{c['family']}",
            name=f"{c['id']} {c['title']}",
            time="0",
        )
        if c["status"] == "fail":
            failure = ET.SubElement(case, "failure", type=c["breaks"], message=c["message"])
            failure.text = json.dumps(c["details"], indent=2, sort_keys=True)
        elif c["status"] in ("skipped", "not_applicable"):
            ET.SubElement(case, "skipped", message=c["message"])
        elif c["status"] == "warn":
            ET.SubElement(case, "system-out").text = f"WARNING: {c['message']}"
    ET.indent(suites)
    body = ET.tostring(suites, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
