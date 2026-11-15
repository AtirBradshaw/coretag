"""Storage drive scoring (SATA and NVMe, from smartctl readings)."""

from .common import CAUTION, FAIL, INFO, PASS, fact, finding, integer, num, obj, text
from .integrity import check_identity_history


def score(comp, *, session_elapsed_s=None, history_lookup=None):
    ident = obj(comp.get("identity"))
    st = obj(comp.get("static"))
    model = text(ident.get("model"), 120) or "Unknown drive"
    serial_hash = text(ident.get("serial_hash"), 80)
    label = model
    findings, flags = [], []

    def F(sev, title, detail, measured=None):
        findings.append(finding(sev, title, detail, label, measured))

    smart = st.get("smart_passed")
    if smart is False:
        F(FAIL, "Drive reports itself as failing",
          "The drive's own SMART self-assessment did not pass.", "FAILED")
    elif smart is True:
        F(PASS, "SMART self-assessment passed", "The drive considers itself healthy.", "PASSED")

    clean = True
    for key, name, sev, note in (
        ("reallocated_sectors", "Reallocated sectors", CAUTION,
         "Sectors have failed and been replaced with spares."),
        ("pending_sectors", "Pending sectors", FAIL,
         "Sectors are unreadable and waiting to be replaced."),
        ("uncorrectable", "Uncorrectable errors", FAIL,
         "Data could not be recovered from these sectors."),
        ("media_errors", "Media errors", FAIL,
         "The drive's controller reported unrecoverable errors."),
    ):
        v = integer(st.get(key))
        if v is not None and v > 0:
            clean = False
            F(sev, name, note, f"{v:,}")

    crc = integer(st.get("crc_errors"))
    if crc:
        F(INFO, "Interface (cable) errors",
          "Usually a loose or poor-quality cable, not the drive itself.", f"{crc:,}")

    warn = integer(st.get("nvme_critical_warning"))
    if warn:
        clean = False
        F(FAIL, "NVMe critical warning", "The drive raised its own critical-warning flag.",
          f"0x{warn:02x}")

    spare, spare_min = integer(st.get("available_spare_pct")), integer(st.get("available_spare_threshold_pct"))
    if spare is not None and spare_min is not None and spare < spare_min:
        clean = False
        F(FAIL, "Spare blocks below threshold",
          f"The drive's reserve of spare blocks is below its own {spare_min}% minimum.",
          f"{spare}%")

    if clean and smart is True:
        F(PASS, "No bad sectors or media errors", "No failure precursors recorded.")

    hours = integer(st.get("power_on_hours"))
    if hours is not None:
        F(INFO, "Runtime", f"About {hours / 8760:.1f} years of powered-on time.",
          f"{hours:,} hours")

    used = integer(st.get("percentage_used"))
    if used is not None:
        F(CAUTION if used >= 80 else PASS, "Endurance used",
          "Share of the drive's rated write endurance already consumed.", f"{used}%")

    hardware_id = f"drive:{serial_hash}" if serial_hash else None
    prior = history_lookup(hardware_id) if (hardware_id and history_lookup) else []
    flags.extend(check_identity_history("drive", label, {"power_on_hours": hours}, prior, model))

    cap = num(st.get("capacity_gb"))
    written = num(st.get("data_written_tb"))
    facts = [
        fact("Model", model),
        fact("Firmware", text(st.get("firmware"), 40)),
        fact("Type", text(st.get("type"), 20)),
        fact("Capacity", f"{cap:,.0f}" if cap else None, " GB"),
        fact("Powered-on hours", f"{hours:,}" if hours is not None else None),
        fact("Power cycles", integer(st.get("power_cycles"))),
        fact("Data written", written, " TB"),
        fact("Endurance used", used, " %"),
        fact("Reallocated sectors", integer(st.get("reallocated_sectors"))),
        fact("Pending sectors", integer(st.get("pending_sectors"))),
        fact("Media errors", integer(st.get("media_errors"))),
        fact("SMART status", "Passed" if smart is True else ("Failed" if smart is False else None)),
    ]
    return {
        "component": {
            "kind": "drive",
            "hardware_id": hardware_id,
            "label": label,
            "facts": facts,
            "snapshot": {
                "model": model, "power_on_hours": hours, "data_written_tb": written,
                "reallocated_sectors": integer(st.get("reallocated_sectors")),
                "pending_sectors": integer(st.get("pending_sectors")),
                "uncorrectable": integer(st.get("uncorrectable")),
                "media_errors": integer(st.get("media_errors")),
                "percentage_used": used,
            },
        },
        "findings": findings,
        "flags": flags,
    }
