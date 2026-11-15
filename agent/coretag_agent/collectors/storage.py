"""Storage drives via smartctl (smartmontools), read-only.

Never reads or writes any data on the drive: smartctl -a only asks the
drive's controller for its health log.
"""

import json

from ..util import find_tool, is_admin, run_cmd, stable_hash

SMARTCTL_GUESSES = (
    r"C:\Program Files\smartmontools\bin\smartctl.exe",
    r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe",
)


def parse_drive(d: dict) -> dict:
    """Turn one `smartctl -a -j` result into a Coretag component."""
    attrs, norms = {}, {}
    for a in (d.get("ata_smart_attributes") or {}).get("table", []):
        attrs[a.get("name")] = (a.get("raw") or {}).get("value")
        norms[a.get("name")] = a.get("value")
    nvme = d.get("nvme_smart_health_information_log") or {}

    cap = d.get("user_capacity") or {}
    cap_bytes = cap.get("bytes")
    if not cap_bytes and cap.get("blocks"):
        cap_bytes = cap["blocks"] * (d.get("logical_block_size") or 512)
    if not cap_bytes and isinstance(d.get("nvme_total_capacity"), int):
        cap_bytes = d["nvme_total_capacity"]

    # total written: NVMe directly (units of 512,000 bytes), SATA via vendor attributes
    written_tb = None
    if nvme.get("data_units_written"):
        written_tb = round(nvme["data_units_written"] * 512000 / 1e12, 2)
    else:
        for key, to_bytes in (("Total_LBAs_Written", 512),
                              ("Host_Writes_32MiB", 32 * 1024 ** 2),
                              ("Lifetime_Writes_GiB", 1024 ** 3),
                              ("Total_Writes_GB", 1e9)):
            v = attrs.get(key)
            if isinstance(v, int) and v > 0:
                written_tb = round(v * to_bytes / 1e12, 2)
                break

    # endurance used: NVMe reports it; SATA wear indicators count DOWN from 100
    used_pct = nvme.get("percentage_used")
    if used_pct is None:
        for key in ("Wear_Leveling_Count", "SSD_Life_Left",
                    "Media_Wearout_Indicator", "Percent_Lifetime_Remain"):
            nv = norms.get(key)
            if isinstance(nv, int) and 0 <= nv <= 100:
                used_pct = 100 - nv
                break

    is_nvme = bool(nvme) or (d.get("device") or {}).get("type") == "nvme"
    rot = d.get("rotation_rate")
    kind = "NVMe SSD" if is_nvme else ("SATA SSD" if rot == 0 else ("Hard drive" if rot else None))

    return {
        "kind": "drive",
        "identity": {
            "model": d.get("model_name"),
            "serial_hash": stable_hash("drive", d.get("serial_number")),
        },
        "static": {
            "type": kind,
            "firmware": d.get("firmware_version"),
            "capacity_gb": round(cap_bytes / 1e9, 1) if cap_bytes else None,
            "smart_passed": (d.get("smart_status") or {}).get("passed"),
            "power_on_hours": (d.get("power_on_time") or {}).get("hours") or nvme.get("power_on_hours"),
            "power_cycles": d.get("power_cycle_count") or nvme.get("power_cycles"),
            "percentage_used": used_pct,
            "data_written_tb": written_tb,
            "reallocated_sectors": attrs.get("Reallocated_Sector_Ct"),
            "pending_sectors": attrs.get("Current_Pending_Sector"),
            "uncorrectable": attrs.get("Offline_Uncorrectable") or attrs.get("Reported_Uncorrect"),
            "crc_errors": attrs.get("UDMA_CRC_Error_Count"),
            "media_errors": nvme.get("media_errors"),
            "nvme_critical_warning": nvme.get("critical_warning"),
            "available_spare_pct": nvme.get("available_spare"),
            "available_spare_threshold_pct": nvme.get("available_spare_threshold"),
            "temperature_c": nvme.get("temperature") or (d.get("temperature") or {}).get("current"),
        },
    }


def collect():
    smartctl = find_tool("smartctl", SMARTCTL_GUESSES)
    if not smartctl:
        return [], ["Drive health skipped: smartmontools isn't installed "
                    "(free, from smartmontools.org)."]

    scan = run_cmd([smartctl, "--scan", "-j"])
    devices = []
    try:
        devices = json.loads(scan).get("devices", []) if scan else []
    except ValueError:
        pass
    if not devices:
        hint = "" if is_admin() else " Try running Coretag as administrator."
        return [], ["No drives could be read." + hint]

    comps, seen = [], set()
    for dev in devices:
        raw = run_cmd([smartctl, "-a", "-j", dev.get("name"), "-d", dev.get("type") or "auto"])
        try:
            d = json.loads(raw) if raw else None
        except ValueError:
            d = None
        if not d or not d.get("model_name"):
            continue
        comp = parse_drive(d)
        key = comp["identity"]["serial_hash"] or dev.get("name")
        if key in seen:      # the same drive can be listed under two names
            continue
        seen.add(key)
        comps.append(comp)

    problems = []
    if not comps:
        problems.append("No drives could be read." + ("" if is_admin() else
                        " Try running Coretag as administrator."))
    return comps, problems
