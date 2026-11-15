"""The comparison engine: an earlier report vs a later, fresh run on the same part.

Two situations use it, and only the wording differs:
  arrival - the buyer tests the item on arrival against the seller's report
            ("it arrived dead" vs "it left here working")
  return  - the seller tests an item that came back against their own
            pre-shipping report (was the card I shipped the card I got back?)

Either way it turns a he-said-she-said dispute into a diff of two independent
measurement runs.

Verdict order matters, and is deliberately conservative:
  1. INCONCLUSIVE    - a GPU is missing from either report, or either report
                       failed its data-integrity checks
  2. DIFFERENT_CARD  - the GPU's unique ID differs: a swap, by either party
  3. TAMPERED        - same ID but model name, memory size or firmware changed
  4. DEGRADED        - same card, measurably worse
  5. INCONCLUSIVE    - same card, but the data conflict or a load test was
                       too light to compare condition
  6. MATCH           - same card, same condition
"""

from datetime import datetime

MATCH, DEGRADED, DIFFERENT_CARD, TAMPERED, INCONCLUSIVE = (
    "MATCH", "DEGRADED", "DIFFERENT_CARD", "TAMPERED", "INCONCLUSIVE")

VERDICT_COPY = {
    MATCH: ("Same card, same condition",
            "The buyer's measurements match the seller's. Nothing electronic "
            "changed between the two runs."),
    DEGRADED: ("Same card, measurably worse",
               "This is the same physical card, but one or more measurements are "
               "worse on arrival than before shipping."),
    DIFFERENT_CARD: ("Different card",
                     "The card the buyer tested is not the card the seller tested. "
                     "Its unique hardware ID is different."),
    TAMPERED: ("Firmware or identity changed",
               "Same card ID, but its model name, memory size or firmware changed "
               "between the two runs. Firmware doesn't change in transit."),
    INCONCLUSIVE: ("Inconclusive",
                   "There isn't enough reliable data to compare the two runs."),
}

MODES = ("arrival", "return")

# column headings and page subtitle for each mode
LABELS = {
    "arrival": ("Seller", "Buyer", "Before shipping vs. on arrival"),
    "return": ("Shipped", "Returned", "Shipped vs. returned"),
}

# wording that changes when the seller is checking an item that came back
RETURN_COPY = {
    MATCH: ("Same card came back",
            "The returned card is the card that was shipped, and its measurements "
            "match the pre-shipping run."),
    DEGRADED: ("Same card, now worse",
               "The returned card is the card that was shipped, but one or more "
               "measurements are worse than before it shipped."),
    DIFFERENT_CARD: ("A different card came back",
                     "The returned card is not the card that was shipped. Its unique "
                     "hardware ID is different."),
}

CANNOT_DETERMINE = [
    "Physical or cosmetic damage, including shipping damage",
    "Damaged power connectors, bent pins, cracked PCBs",
    "Who ran each test. The server can't see who is at the keyboard",
    "Damage caused by the second machine's PSU, motherboard or setup",
    "The identity of a card too damaged to be detected at all",
    "Anything that happened after the second run",
]

PEAK_TEMP_WORSE_C = 10      # room temperature alone can move peaks by a few degrees
CLOCK_DROP_WORSE_PTS = 10
HOURS_SLACK = 2


def _row(group, label, seller, buyer, status, note=None):
    return {"group": group, "label": label, "seller": seller, "buyer": buyer,
            "status": status, "note": note}


def _fmt(v, unit=""):
    if v is None:
        return None
    if isinstance(v, float):
        v = round(v, 1)
    return f"{v:,}{unit}" if isinstance(v, (int, float)) else f"{v}{unit}"


def compare(seller: dict, buyer: dict, mode: str = "arrival") -> dict:
    """`seller` is the earlier report, `buyer` the later fresh run."""
    mode = mode if mode in MODES else "arrival"
    first, second, _ = LABELS[mode]
    s_res, b_res = seller["result"], buyer["result"]
    s_at: datetime = seller["created_at"]
    b_at: datetime = buyer["created_at"]
    elapsed_h = (b_at - s_at).total_seconds() / 3600

    rows, worse, conflicts, notes = [], [], [], []

    s_gpu = next((c for c in s_res.get("components", []) if c["kind"] == "gpu"), None)
    b_gpus = [c for c in b_res.get("components", []) if c["kind"] == "gpu"]
    b_gpu = None
    if s_gpu and b_gpus:
        b_gpu = next((c for c in b_gpus if c.get("hardware_id")
                      and c["hardware_id"] == s_gpu.get("hardware_id")), b_gpus[0])

    verdict, reason = None, None

    if not s_gpu or not b_gpu:
        verdict, reason = INCONCLUSIVE, "One of the reports contains no graphics card."
    else:
        ss, bs = s_gpu.get("snapshot") or {}, b_gpu.get("snapshot") or {}

        same_id = bool(ss.get("uuid")) and ss.get("uuid") == bs.get("uuid")
        rows.append(_row("Identity", "Card ID (UUID)", ss.get("uuid"), bs.get("uuid"),
                         "same" if same_id else "changed"))

        identity_changes = []
        for key, label, unit in (("name", "Model", ""), ("vram_mb", "Memory", " MB"),
                                 ("vbios", "VBIOS", "")):
            a, b = ss.get(key), bs.get(key)
            changed = a is not None and b is not None and a != b
            if changed:
                identity_changes.append(label)
            rows.append(_row("Identity", label, _fmt(a, unit), _fmt(b, unit),
                             "changed" if changed else ("same" if a == b else "na")))

        # memory errors (only exposed on workstation / datacenter cards)
        ea, eb = ss.get("ecc"), bs.get("ecc")
        if isinstance(ea, int) and isinstance(eb, int):
            st = "worse" if eb > ea else "same"
            if st == "worse":
                worse.append(f"Uncorrected memory errors rose from {ea} to {eb}.")
            rows.append(_row("Health", "Memory errors", _fmt(ea), _fmt(eb), st))

        # behaviour under load: only comparable when both runs worked the card hard
        sa, sb = s_gpu.get("stats") or {}, b_gpu.get("stats") or {}
        both_loaded = bool(s_gpu.get("load_conclusive") and b_gpu.get("load_conclusive"))

        def load_row(label, a, b, unit, worse_if, why):
            if not both_loaded or a is None or b is None:
                rows.append(_row("Under load", label, _fmt(a, unit), _fmt(b, unit), "na"))
                return
            bad = worse_if(a, b)
            if bad:
                worse.append(why(a, b))
            rows.append(_row("Under load", label, _fmt(a, unit), _fmt(b, unit),
                             "worse" if bad else "same"))

        load_row("Peak temperature", sa.get("peak_temp_c"), sb.get("peak_temp_c"), " °C",
                 lambda a, b: b - a >= PEAK_TEMP_WORSE_C,
                 lambda a, b: f"Peak temperature rose {b - a:.0f} °C ({a} → {b} °C).")
        load_row("Thermal/hardware throttling",
                 sa.get("throttled_pct"), sb.get("throttled_pct"), "% of run",
                 lambda a, b: b >= 5 and b - a >= 5,
                 lambda a, b: f"Throttling rose from {a}% to {b}% of the run.")
        load_row("Clock dip under load", sa.get("clock_drop_pct"), sb.get("clock_drop_pct"), "%",
                 lambda a, b: b - a > CLOCK_DROP_WORSE_PTS,
                 lambda a, b: f"Clock stability worsened ({a}% → {b}% dip).")
        load_row("Average power", sa.get("avg_power_w"), sb.get("avg_power_w"), " W",
                 lambda a, b: False, lambda a, b: "")
        load_row("Power vs. limit", sa.get("power_pct_of_limit"), sb.get("power_pct_of_limit"), "%",
                 lambda a, b: False, lambda a, b: "")
        if not both_loaded:
            notes.append("Thermal and clock behaviour weren't compared: at least one "
                         "run didn't load the card heavily enough for long enough.")
        elif sa.get("peak_temp_c") is not None and sb.get("peak_temp_c") is not None:
            notes.append("Room temperature and case airflow differ between homes. "
                         "Peak-temperature changes under 10 °C are treated as normal.")

        # drives that appear in both reports (seller may be selling only the GPU)
        b_drives = {c["hardware_id"]: c for c in b_res.get("components", [])
                    if c["kind"] == "drive" and c.get("hardware_id")}
        for sd in (c for c in s_res.get("components", []) if c["kind"] == "drive"):
            bd = b_drives.get(sd.get("hardware_id"))
            if not bd:
                continue
            a, b = sd.get("snapshot") or {}, bd.get("snapshot") or {}
            g = f"Drive: {sd['label']}"
            ha, hb = a.get("power_on_hours"), b.get("power_on_hours")
            if isinstance(ha, int) and isinstance(hb, int):
                delta = hb - ha
                if delta < 0 or delta > max(0, elapsed_h) + HOURS_SLACK:
                    conflicts.append(f"{sd['label']}: powered-on hours changed by {delta:,} "
                                     f"in {elapsed_h:.0f} real hours, which isn't possible.")
                    st = "changed"
                else:
                    st = "same" if delta <= HOURS_SLACK else "changed"
                rows.append(_row(g, "Powered-on hours", _fmt(ha), _fmt(hb), st,
                                 f"+{delta:,} h" if delta > 0 else None))
            for key, label in (("reallocated_sectors", "Reallocated sectors"),
                               ("pending_sectors", "Pending sectors"),
                               ("uncorrectable", "Uncorrectable errors"),
                               ("media_errors", "Media errors")):
                x, y = a.get(key), b.get(key)
                if isinstance(x, int) and isinstance(y, int):
                    bad = y > x
                    if bad:
                        worse.append(f"{sd['label']}: {label.lower()} rose from {x} to {y}.")
                    rows.append(_row(g, label, _fmt(x), _fmt(y), "worse" if bad else "same"))
            wa, wb = a.get("data_written_tb"), b.get("data_written_tb")
            if wa is not None and wb is not None:
                rows.append(_row(g, "Data written", _fmt(wa, " TB"), _fmt(wb, " TB"),
                                 "same" if abs(wb - wa) < 0.01 else "changed"))

        s_flags, b_flags = s_res.get("flags") or [], b_res.get("flags") or []
        if s_flags or b_flags:
            who = " and ".join(w for w, f in ((first.lower(), s_flags), (second.lower(), b_flags)) if f)
            verdict, reason = INCONCLUSIVE, (
                f"The {who} report failed data-integrity checks, so the two can't be "
                "compared with confidence.")
        elif not same_id:
            verdict, reason = DIFFERENT_CARD, "The two reports were made on different physical cards."
        elif identity_changes:
            verdict, reason = TAMPERED, (
                f"{', '.join(identity_changes)} changed on the same card between runs.")
        elif worse:
            verdict, reason = DEGRADED, " ".join(worse)
        elif conflicts:
            verdict, reason = INCONCLUSIVE, " ".join(conflicts)
        elif not both_loaded:
            verdict, reason = INCONCLUSIVE, (
                "Same card, but at least one load test was too light to compare its "
                "condition. Re-run the full 5-minute test.")
        else:
            verdict, reason = MATCH, "Same card ID, same firmware, same behaviour under load."

    days = elapsed_h / 24
    if days >= 21:
        notes.append(f"The reports are {days:.0f} days apart. The longer the gap, the "
                     "less this says about the item's condition when it was handed over.")

    copy = RETURN_COPY if mode == "return" else {}
    title, summary = copy.get(verdict, VERDICT_COPY[verdict])
    return {
        "verdict": verdict,
        "mode": mode,
        "labels": list(LABELS[mode]),
        "title": title,
        "summary": summary,
        "reason": reason,
        "rows": rows,
        "notes": notes,
        "cannot_determine": CANNOT_DETERMINE,
        "elapsed_hours": round(elapsed_h, 1),
        "seller_report_id": seller["id"],
        "buyer_report_id": buyer["id"],
    }
