"""Shared helpers for every component scorer.

A *finding* is one plain-English statement about the hardware, always tied
to the measurement it came from. A *flag* is a data-integrity concern: the
numbers don't look like they came from real hardware.
"""

import math

PASS, CAUTION, FAIL, INFO = "pass", "caution", "fail", "info"
SEVERITY_ORDER = {FAIL: 0, CAUTION: 1, PASS: 2, INFO: 3}


def num(v):
    """A finite number, or None. Booleans and strings are rejected so a
    forged payload can't slip `true` or `"99"` past a comparison."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def obj(v):
    """A dict, or an empty dict if the agent sent something else."""
    return v if isinstance(v, dict) else {}


def integer(v):
    v = num(v)
    return int(v) if v is not None else None


def text(v, limit=160):
    if v is None:
        return None
    s = str(v).strip()
    return s[:limit] if s else None


def percentile(values, p):
    vals = sorted(v for v in values if num(v) is not None)
    if not vals:
        return None
    k = round((p / 100) * (len(vals) - 1))
    return vals[max(0, min(len(vals) - 1, k))]


def mean(values):
    vals = [v for v in values if num(v) is not None]
    return sum(vals) / len(vals) if vals else None


def stdev(values):
    vals = [v for v in values if num(v) is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def finding(severity, title, detail, component=None, measured=None):
    return {"severity": severity, "title": title, "detail": detail,
            "component": component, "measured": measured}


def flag(code, title, detail, component=None):
    return {"code": code, "title": title, "detail": detail, "component": component}


def fact(label, value, unit=""):
    """One row in a component's data table. Missing values show as a dash."""
    if value is None or value == "":
        return {"label": label, "value": None, "unit": ""}
    return {"label": label, "value": str(value), "unit": unit}
