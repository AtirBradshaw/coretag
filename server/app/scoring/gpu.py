"""NVIDIA GPU scoring.

Input: the raw component the agent sent (identity, static readings and the
raw load-test samples). Every summary number is computed HERE from the raw
samples; the agent never sends averages or verdicts.
"""

import json
from pathlib import Path

from .common import (CAUTION, FAIL, INFO, PASS, fact, finding, flag, integer,
                     mean, num, obj, percentile, text)
from .integrity import check_gpu_load, check_identity_history

SPECS = json.loads((Path(__file__).parent.parent / "specs" / "nvidia_desktop.json")
                   .read_text(encoding="utf-8"))["cards"]

# NVML "clock event reason" bits. sw_power_cap = the card is at its rated
# power limit, which EVERY healthy GPU does under full load. Not a fault.
THROTTLE_BITS = {
    1: "gpu_idle", 2: "applications_clocks_setting", 4: "sw_power_cap",
    8: "hw_slowdown", 16: "sync_boost", 32: "sw_thermal_slowdown",
    64: "hw_thermal_slowdown", 128: "hw_power_brake_slowdown",
    256: "display_clock_setting",
}
PROBLEM_THROTTLES = {"hw_slowdown", "sw_thermal_slowdown",
                     "hw_thermal_slowdown", "hw_power_brake_slowdown"}
FRIENDLY = {
    "hw_slowdown": "hardware slowdown",
    "sw_thermal_slowdown": "driver thermal slowdown",
    "hw_thermal_slowdown": "hardware thermal slowdown",
    "hw_power_brake_slowdown": "power-brake slowdown",
}

MAX_SAMPLES = 2000


def decode_throttle(mask):
    mask = integer(mask)
    if mask is None or mask < 0:
        return []
    return [name for bit, name in THROTTLE_BITS.items() if mask & bit]


def is_laptop(name):
    n = (name or "").lower()
    return any(k in n for k in ("laptop", "mobile", "max-q", "max-p"))


def lookup_spec(name):
    """Longest match wins, so 'RTX 4070 Ti Super' doesn't resolve to 'RTX 4070'."""
    if not name or is_laptop(name):
        return None, None
    n = name.lower().replace("nvidia", "").replace("geforce", "")
    n = " ".join(n.split())
    best = None
    for key in SPECS:
        if f" {key} " in f" {n} " and (best is None or len(key) > len(best)):
            best = key
    return (best, SPECS[best]) if best else (None, None)


# ----------------------------------------------------------------------
# raw samples -> statistics
# ----------------------------------------------------------------------

def clean_samples(raw):
    out = []
    for s in (raw or [])[:MAX_SAMPLES]:
        if not isinstance(s, dict) or num(s.get("t")) is None:
            continue
        out.append({
            "t": float(s["t"]),
            "temp_c": num(s.get("temp_c")),
            "core_mhz": num(s.get("core_mhz")),
            "power_w": num(s.get("power_w")),
            "util_pct": num(s.get("util_pct")),
            "fan_pct": num(s.get("fan_pct")),
            "reasons": decode_throttle(s.get("throttle_mask")),
        })
    return out


def load_stats(samples, power_limit_w):
    if not samples:
        return None
    loaded = [s for s in samples if (s["util_pct"] or 0) > 50]
    basis = loaded or samples

    def col(src, k):
        return [s[k] for s in src if s[k] is not None]

    temps, cores, powers = col(basis, "temp_c"), col(basis, "core_mhz"), col(basis, "power_w")
    all_temps = col(samples, "temp_c")

    loaded_dur = sum(b["t"] - a["t"] for a, b in zip(samples, samples[1:])
                     if (a["util_pct"] or 0) > 50 and (b["util_pct"] or 0) > 50
                     and 0 < b["t"] - a["t"] < 15)

    problem = sorted({r for s in basis for r in s["reasons"] if r in PROBLEM_THROTTLES})
    at_cap = sum(1 for s in basis if "sw_power_cap" in s["reasons"])

    avg_core = mean(cores)
    p5_core = percentile(cores, 5)
    p90_power = percentile(powers, 90)

    return {
        "sample_count": len(samples),
        "loaded_sample_count": len(loaded),
        "duration_s": round(samples[-1]["t"] - samples[0]["t"], 1),
        "loaded_duration_s": round(loaded_dur, 1),
        "peak_temp_c": max(temps) if temps else None,
        "avg_temp_c": round(mean(temps), 1) if temps else None,
        "start_temp_c": all_temps[0] if all_temps else None,
        "temp_rise_c": (max(all_temps) - min(all_temps)) if all_temps else None,
        "peak_power_w": round(max(powers), 1) if powers else None,
        "avg_power_w": round(mean(powers), 1) if powers else None,
        "power_pct_of_limit": (round(100 * p90_power / power_limit_w)
                               if p90_power and power_limit_w else None),
        "avg_core_mhz": round(avg_core) if avg_core else None,
        "low_core_mhz": round(p5_core) if p5_core else None,   # 5th percentile
        "max_core_mhz": max(cores) if cores else None,
        "clock_drop_pct": (round(100 * (avg_core - p5_core) / avg_core, 1)
                           if avg_core and p5_core else None),
        "peak_util_pct": max(col(samples, "util_pct") or [0]),
        "avg_util_pct": round(mean(col(loaded, "util_pct"))) if loaded else 0,
        "at_power_limit_pct": round(100 * at_cap / len(basis)) if basis else 0,
        "problem_throttles": problem,
        "throttled_pct": round(100 * sum(1 for s in basis
                               if any(r in PROBLEM_THROTTLES for r in s["reasons"]))
                               / len(basis)) if basis else 0,
    }


MIN_LOADED_S = 120
FULL_POWER_PCT = 85        # at/near its power limit: unambiguously working hard
BUSY_UTIL_PCT = 95         # ...or fully busy for minutes,
BUSY_MIN_POWER_PCT = 65    # ...drawing a substantial share of its power budget


def load_is_conclusive(stats):
    """Was the card worked hard enough, for long enough, to reveal a cooling
    or stability problem? Some healthy cards sit 100% busy at top clock yet
    draw only ~80% of their limit on Coretag's shader (an RTX 3060 measured
    ~135 of 170 W), so "fully busy" counts as well as "at the power limit"."""
    if not stats or (stats.get("loaded_duration_s") or 0) < MIN_LOADED_S:
        return False
    power = stats.get("power_pct_of_limit") or 0
    util = stats.get("avg_util_pct") or 0
    return power >= FULL_POWER_PCT or (util >= BUSY_UTIL_PCT and power >= BUSY_MIN_POWER_PCT)


def trace_points(samples, keep=300):
    """Downsampled points for the report chart."""
    if not samples:
        return []
    step = max(1, len(samples) // keep)
    return [{"t": s["t"] - samples[0]["t"], "temp": s["temp_c"], "core": s["core_mhz"],
             "bad": any(r in PROBLEM_THROTTLES for r in s["reasons"])}
            for s in samples[::step]]


# ----------------------------------------------------------------------
# the scorer
# ----------------------------------------------------------------------

def score(comp, *, session_elapsed_s=None, history_lookup=None):
    ident = obj(comp.get("identity"))
    st = obj(comp.get("static"))
    name = text(ident.get("name"), 120) or "Unknown NVIDIA GPU"
    uuid = text(ident.get("uuid"), 80)
    label = name
    laptop = is_laptop(name)
    findings, flags = [], []

    def F(sev, title, detail, measured=None):
        findings.append(finding(sev, title, detail, label, measured))

    vram = integer(st.get("vram_total_mb"))
    pl = num(st.get("power_limit_w"))
    dpl = num(st.get("default_power_limit_w"))
    max_clock = integer(st.get("max_graphics_clock_mhz"))
    vbios = text(ident.get("vbios_version"), 40)

    # --- identity
    if not uuid or not uuid.startswith("GPU-"):
        flags.append(flag("missing_identity", "No hardware identity",
            "The card's unique ID (UUID) is missing, so this report can't be "
            "tied to a physical card.", label))

    # --- does the card match the model it claims to be?
    key, spec = lookup_spec(name)
    if laptop:
        F(INFO, "Laptop GPU",
          "Laptop GPUs share names with desktop cards but have different memory "
          "sizes and power limits, so they are not checked against the desktop "
          "reference table.")
    elif not spec:
        F(INFO, "Model not in reference table",
          "There's no reference spec on file for this model, so its identity "
          "couldn't be cross-checked. The measurements are still valid.")
    else:
        model = key.upper()
        if vram is not None:
            if any(abs(vram - v) <= 512 for v in spec["vram_mb"]):
                F(PASS, "Memory size matches model",
                  f"Consistent with a {model}.", f"{vram:,} MB")
            else:
                expected = " or ".join(f"{v:,} MB" for v in spec["vram_mb"])
                F(FAIL, "Memory size does not match model",
                  f"A {model} ships with {expected}. A mismatch strongly suggests "
                  "modified firmware or a misrepresented card.", f"{vram:,} MB")
        if dpl is not None:
            delta = abs(dpl - spec["tdp_w"]) / spec["tdp_w"] * 100
            if delta <= 12:
                F(PASS, "Power rating matches model",
                  f"In line with the {spec['tdp_w']} W reference.", f"{dpl:.0f} W")
            elif delta <= 35:
                F(INFO, "Power rating differs from reference",
                  f"Reference is {spec['tdp_w']} W. Board partners vary this; "
                  "usually a model variant, not a problem.", f"{dpl:.0f} W")
            else:
                F(CAUTION, "Power rating far from reference",
                  f"Reference is {spec['tdp_w']} W for a {model}. Worth asking "
                  "the seller about.", f"{dpl:.0f} W")
        if max_clock and max_clock < spec["boost_mhz"] * 0.80:
            F(CAUTION, "Maximum clock below reference",
              f"Reference boost for a {model} is {spec['boost_mhz']} MHz.",
              f"{max_clock} MHz")

    # --- power limit changed from factory (laptops change this dynamically)
    if pl is not None and dpl is not None and not laptop:
        if abs(pl - dpl) > 1:
            F(INFO, "Power limit adjusted",
              f"Factory default is {dpl:.0f} W. Common on enthusiast systems and "
              "reversible in software.", f"{pl:.0f} W")
        else:
            F(PASS, "Power limit at factory default",
              "Consistent with unmodified firmware.", f"{pl:.0f} W")

    # --- memory errors (consumer GeForce cards have no ECC counters)
    ecc = integer(st.get("ecc_errors_total"))
    if ecc is not None and ecc > 0:
        F(FAIL, "Uncorrected memory errors", "Indicates failing video memory.", f"{ecc}")
    elif ecc == 0:
        F(PASS, "No memory errors", "No uncorrected video-memory errors recorded.", "0")
    else:
        F(INFO, "Memory error counters not available",
          "Consumer GeForce cards don't expose memory error counters. Stability "
          "under load is the available indicator.")

    fans = integer(st.get("fan_count"))
    if fans:
        F(PASS, "Fans detected", "Fans present and reporting.", f"{fans}")

    # --- behaviour under sustained load
    lt = obj(comp.get("load_test"))
    raw_samples = lt.get("samples")
    samples = clean_samples(raw_samples if isinstance(raw_samples, list) else [])
    stats = load_stats(samples, pl) if samples else None
    renderer = text(lt.get("renderer"), 120)
    aborted = text(lt.get("aborted"), 120)
    if aborted:
        F(CAUTION, "Load test stopped early for safety",
          "Coretag removed the load before the test finished, because "
          f"{aborted}. A healthy card shouldn't trigger this under Coretag's load.")

    if stats and stats["loaded_sample_count"] == 0:
        detail = "The load generator didn't put this card under load."
        if renderer and "nvidia" not in renderer.lower():
            detail += (f" Windows ran it on '{renderer}' instead. On laptops, set "
                       "Python to 'High performance' in Windows Graphics settings.")
        F(INFO, "Card was not loaded", detail)
        stats_ok = False
    elif stats:
        stats_ok = load_is_conclusive(stats)
        peak, dur = stats["peak_temp_c"], int(stats["loaded_duration_s"])
        hot_line = 90 if laptop else 86
        if stats["problem_throttles"]:
            names = ", ".join(FRIENDLY[r] for r in stats["problem_throttles"])
            thermal = any("thermal" in r for r in stats["problem_throttles"])
            F(CAUTION,
              "Thermal throttling under load" if thermal else "Hardware slowdown under load",
              ("The card's own protection reduced clocks because of heat. Usually "
               "worn thermal paste or pads, or heavy dust." if thermal else
               "Can indicate a power delivery or cooling problem.") +
              f" Active for {stats['throttled_pct']}% of the loaded run ({names}).",
              f"{peak} °C peak")
        elif peak is not None:
            if peak >= hot_line:
                F(CAUTION, "Runs hot under load",
                  "Warm, but no throttling occurred.", f"{peak} °C peak")
            else:
                F(PASS if stats_ok else INFO, "Cooling performing normally",
                  f"No thermal throttling across {dur} s of load.", f"{peak} °C peak")

        if (stats["at_power_limit_pct"] or 0) >= 50 and stats["avg_power_w"]:
            F(PASS, "Drawing full rated power",
              f"At its power limit for {stats['at_power_limit_pct']}% of the run, "
              "which is normal: the card is delivering its rated performance.",
              f"{stats['avg_power_w']:.0f} W average")

        drop = stats["clock_drop_pct"]
        if drop is not None:
            if drop > 15:
                F(CAUTION, "Clocks unstable under load",
                  f"Core clock dipped to {stats['low_core_mhz']} MHz against a "
                  f"{stats['avg_core_mhz']} MHz average.", f"{drop:.0f}% drop")
            else:
                F(PASS if stats_ok else INFO, "Clocks stable under load",
                  f"Held a {stats['avg_core_mhz']} MHz average.", f"{drop:.0f}% max dip")

        if not stats_ok:
            pp, util = stats.get("power_pct_of_limit"), stats.get("avg_util_pct")
            if (stats.get("loaded_duration_s") or 0) < MIN_LOADED_S:
                why = f"The card was under load for only {int(stats['loaded_duration_s'])} s, "
            elif util is not None and util < BUSY_UTIL_PCT:
                why = f"The card was only {util}% busy on average, "
            elif pp is not None:
                why = f"The card reached only {pp}% of its rated power, "
            else:
                why = "The run was too light, "
            F(INFO, "Load test inconclusive",
              why + "so it wasn't worked hard enough to reveal a cooling problem. "
              "Treat the thermal results as unconfirmed.")

        flags.extend(check_gpu_load(samples, stats, st, session_elapsed_s, label))
    else:
        stats_ok = False
        F(INFO, "No load test recorded",
          "This report covers idle readings only. A load test reveals thermal "
          "and clock behaviour.")

    # --- cross-check against earlier reports for this physical card
    hardware_id = f"gpu:{uuid}" if uuid and uuid.startswith("GPU-") else None
    prior = history_lookup(hardware_id) if (hardware_id and history_lookup) else []
    flags.extend(check_identity_history("gpu", label, {}, prior, name))
    if prior:
        last = prior[-1]
        old_vbios = (last.get("snapshot") or {}).get("vbios")
        if old_vbios and vbios and old_vbios != vbios:
            F(INFO, "Firmware changed since an earlier report",
              f"Report {last['report_id']} recorded VBIOS {old_vbios}.", vbios)

    facts = [
        fact("Model", name),
        fact("Card ID (UUID)", uuid),
        fact("VBIOS", vbios),
        fact("Memory", f"{vram:,}" if vram else None, " MB"),
        fact("Enforced power limit", f"{pl:.0f}" if pl is not None else None, " W"),
        fact("Factory power limit", f"{dpl:.0f}" if dpl is not None else None, " W"),
        fact("Max core clock", max_clock, " MHz"),
        fact("Fans", fans),
        fact("PCI device", text(ident.get("pci_device_id"), 20)),
        fact("Driver", text(st.get("driver_version"), 40)),
    ]
    load_facts = []
    if stats and stats["loaded_sample_count"]:
        load_facts = [
            fact("Peak temperature", stats["peak_temp_c"], " °C"),
            fact("Average temperature", stats["avg_temp_c"], " °C"),
            fact("Temperature rise", stats["temp_rise_c"], " °C"),
            fact("Peak power", stats["peak_power_w"], " W"),
            fact("Average power", stats["avg_power_w"], " W"),
            fact("Power vs. limit", stats["power_pct_of_limit"], " %"),
            fact("Average utilisation", stats["avg_util_pct"], " %"),
            fact("Average core clock", stats["avg_core_mhz"], " MHz"),
            fact("Low core clock (5th pct)", stats["low_core_mhz"], " MHz"),
            fact("Time at power limit", stats["at_power_limit_pct"], " %"),
            fact("Time under load", int(stats["loaded_duration_s"]), " s"),
        ]

    return {
        "component": {
            "kind": "gpu",
            "hardware_id": hardware_id,
            "label": label,
            "laptop": laptop,
            "facts": facts,
            "load_facts": load_facts,
            "stats": stats,
            "load_conclusive": stats_ok,
            "trace": trace_points(samples),
            "snapshot": {"name": name, "uuid": uuid, "vbios": vbios, "vram_mb": vram,
                         "ecc": ecc,
                         "peak_temp_c": stats["peak_temp_c"] if stats else None,
                         "load_conclusive": stats_ok},
        },
        "findings": findings,
        "flags": flags,
    }
