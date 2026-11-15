"""Data-integrity checks: does this look like it came from real hardware?

A patched agent can always send invented numbers; nothing on the server can
make that impossible. These checks make lazy forgery fail and careful
forgery expensive. Any flag downgrades a clean report to "review" and is
shown to the buyer in its own section, so nothing is hidden.

Each check is written to stay quiet on healthy, honest hardware: a false
alarm on a seller's good card costs more trust than a missed forgery.
"""

from .common import flag, num, percentile, stdev


def check_gpu_load(samples, stats, static, session_elapsed_s, label):
    out = []
    if not samples or not stats:
        return out

    ts = [s["t"] for s in samples]

    # --- sampling cadence: the agent samples on a fixed clock
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    if any(g <= 0 for g in gaps):
        out.append(flag("time_not_increasing", "Sample times go backwards",
            "Measurement timestamps are not in order, which a real recording "
            "cannot produce.", label))
    elif gaps:
        med = percentile(gaps, 50)
        odd = sum(1 for g in gaps if abs(g - med) > med * 0.6)
        if not (0.8 <= med <= 6.0) or odd > max(3, len(gaps) * 0.15):
            out.append(flag("irregular_sampling", "Irregular sampling",
                f"Measurements were expected every ~2 s; the median gap was "
                f"{med:.1f} s with {odd} irregular gaps.", label))

    # --- the test can't have run longer than the time since the server
    # issued this run's one-time code
    duration = ts[-1] - ts[0] if len(ts) > 1 else 0
    if session_elapsed_s is not None and duration > session_elapsed_s + 20:
        out.append(flag("longer_than_session", "Load test longer than the session",
            f"The recording covers {duration:.0f} s, but only "
            f"{session_elapsed_s:.0f} s passed between the server issuing this "
            "run's code and receiving the result.", label))

    loaded = [s for s in samples if (num(s.get("util_pct")) or 0) > 50]
    temps = [s.get("temp_c") for s in loaded if num(s.get("temp_c")) is not None]
    powers = [s.get("power_w") for s in loaded if num(s.get("power_w")) is not None]
    limit = num(static.get("power_limit_w"))

    # --- physically impossible readings
    all_temps = [s.get("temp_c") for s in samples if num(s.get("temp_c")) is not None]
    if all_temps and (min(all_temps) < 5 or max(all_temps) > 115):
        out.append(flag("temp_out_of_range", "Temperature outside physical range",
            f"Readings ranged {min(all_temps)}–{max(all_temps)} °C.", label))

    max_clock = num(static.get("max_graphics_clock_mhz"))
    peak_core = stats.get("max_core_mhz")
    if max_clock and peak_core and peak_core > max_clock * 1.05 + 30:
        out.append(flag("clock_above_max", "Clock above the card's own maximum",
            f"Recorded {peak_core} MHz, but the card reports a {max_clock} MHz "
            "maximum.", label))

    if len(loaded) >= 20:
        # real sensors always wander a little under load
        if temps and (max(temps) - min(temps)) <= 1 and (stdev(temps) or 0) < 0.3:
            out.append(flag("flat_temperature", "Temperature never changed",
                f"Temperature stayed at {temps[0]} °C for {len(temps)} loaded "
                "samples. Real cards drift by at least a degree or two.", label))
        if powers and (max(powers) - min(powers)) < 1.0:
            out.append(flag("constant_power", "Power draw never changed",
                f"Power stayed within 1 W across {len(powers)} loaded samples. "
                "Real power readings fluctuate continuously.", label))

        avg_util = sum(s["util_pct"] for s in loaded) / len(loaded)
        p90_power = percentile(powers, 90)
        if limit and p90_power is not None and avg_util >= 95 and p90_power < 0.25 * limit:
            out.append(flag("power_too_low", "Power implausibly low for the load",
                f"Utilisation averaged {avg_util:.0f}% but power peaked near "
                f"{p90_power:.0f} W of a {limit:.0f} W limit.", label))

        # a card working near its power limit for minutes must warm up,
        # unless it was already hot when the test began
        started_idle = (num(samples[0].get("util_pct")) or 0) < 50
        rise = stats.get("temp_rise_c")
        avg_p = stats.get("avg_power_w")
        if (started_idle and limit and avg_p and avg_p > 0.5 * limit
                and (stats.get("loaded_duration_s") or 0) >= 120
                and rise is not None and rise < 3):
            out.append(flag("no_thermal_rise", "No temperature rise under load",
                f"Drew ~{avg_p:.0f} W for {stats['loaded_duration_s']:.0f} s but "
                f"temperature rose only {rise} °C.", label))

    return out


def check_identity_history(kind, label, current, prior, label_now):
    """Compare this component against earlier reports for the same hardware ID."""
    out = []
    for p in prior:
        if kind == "gpu" and p.get("label") and label_now and p["label"] != label_now:
            out.append(flag("identity_changed", "Same card ID, different model name",
                f"This card's hardware ID was reported as '{p['label']}' on "
                f"{p['created_at']:%d %b %Y} (report {p['report_id']}). A card "
                "can't change model; this suggests modified firmware or data.", label))
            break
        if kind == "drive":
            then = (p.get("snapshot") or {}).get("power_on_hours")
            now = current.get("power_on_hours")
            if isinstance(then, int) and isinstance(now, int) and now + 24 < then:
                out.append(flag("hours_went_backwards", "Drive hours went backwards",
                    f"Report {p['report_id']} recorded {then:,} powered-on hours; "
                    f"this one records {now:,}. The counter only goes up.", label))
                break
    return out
