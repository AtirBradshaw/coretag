"""Turns raw telemetry into a report.

To support a new kind of part (CPU, RAM, PSU...), write a scorer module with
a `score(component, session_elapsed_s=..., history_lookup=...)` function and
register it in SCORERS below. Nothing else on the server needs to change.
"""

from . import drive, gpu
from .common import CAUTION, FAIL, PASS, SEVERITY_ORDER, flag, obj, text

SCORERS = {
    "gpu": gpu.score,
    "drive": drive.score,
}

MAX_COMPONENTS = 16

VERDICT_COPY = {
    PASS: ("Nothing flagged",
           "Every measured value fell inside its expected range."),
    CAUTION: ("Review before buying",
              "Some measurements fall outside expected ranges. None are "
              "automatically disqualifying. Each one is explained below."),
    FAIL: ("Failing hardware detected",
           "One or more measurements indicate hardware that is degrading or "
           "already faulty."),
}


def score_report(telemetry: dict, *, session_elapsed_s=None, history_lookup=None) -> dict:
    comps = telemetry.get("components")
    comps = comps if isinstance(comps, list) else []

    components, findings, flags = [], [], []
    for raw in comps[:MAX_COMPONENTS]:
        if not isinstance(raw, dict):
            continue
        scorer = SCORERS.get(raw.get("kind"))
        if not scorer:
            continue
        out = scorer(raw, session_elapsed_s=session_elapsed_s, history_lookup=history_lookup)
        components.append(out["component"])
        findings.extend(out["findings"])
        flags.extend(out["flags"])

    if not components:
        flags.append(flag("no_hardware", "No hardware in report",
                          "The report contained no readable components."))

    findings.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])

    sevs = {f["severity"] for f in findings}
    if FAIL in sevs:
        verdict = FAIL
    elif CAUTION in sevs or flags:
        # any integrity flag downgrades a clean report
        verdict = CAUTION
    else:
        verdict = PASS

    # the report's headline subject: a GPU if there is one, else the first part
    gpus = [c for c in components if c["kind"] == "gpu"]
    subject = (gpus or components or [{"label": "Unknown hardware"}])[0]["label"]

    sysinfo = obj(telemetry.get("system"))
    return {
        "verdict": verdict,
        "subject": subject,
        "findings": findings,
        "flags": flags,
        "components": components,
        "system": {
            "os": text(sysinfo.get("os"), 40),
            "os_version": text(sysinfo.get("os_version"), 60),
            "cpu": text(sysinfo.get("cpu"), 120),
        },
        "agent_version": text(telemetry.get("agent_version"), 32),
        "session_elapsed_s": round(session_elapsed_s) if session_elapsed_s is not None else None,
    }
