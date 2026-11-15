"""NVIDIA GPUs via NVML, NVIDIA's own management library (read-only)."""

from ..util import safe, to_str


def _nvml():
    import pynvml
    pynvml.nvmlInit()
    return pynvml


def throttle_mask(pynvml, h):
    """NVML renamed this call; try both. Raw bitmask, decoded on the server."""
    for fn in ("nvmlDeviceGetCurrentClocksEventReasons",
               "nvmlDeviceGetCurrentClocksThrottleReasons"):
        if hasattr(pynvml, fn):
            v = safe(lambda: getattr(pynvml, fn)(h))
            if v is not None:
                return int(v)
    return None


def read_sample(pynvml, h):
    """One point of the load-test recording."""
    return {
        "temp_c": safe(lambda: pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)),
        "core_mhz": safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS)),
        "mem_mhz": safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM)),
        "power_w": safe(lambda: round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0, 2)),
        "util_pct": safe(lambda: pynvml.nvmlDeviceGetUtilizationRates(h).gpu),
        "fan_pct": safe(lambda: pynvml.nvmlDeviceGetFanSpeed(h)),
        "throttle_mask": throttle_mask(pynvml, h),
    }


def collect():
    try:
        pynvml = _nvml()
    except ImportError:
        return [], ["NVIDIA library not installed (nvidia-ml-py)."]
    except Exception:
        return [], ["No NVIDIA graphics card or driver found."]

    comps = []
    try:
        driver = to_str(safe(pynvml.nvmlSystemGetDriverVersion))
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            s = lambda fn, *a: to_str(safe(lambda: fn(h, *a)))  # noqa: E731
            pci = safe(lambda: pynvml.nvmlDeviceGetPciInfo(h))
            mem = safe(lambda: pynvml.nvmlDeviceGetMemoryInfo(h))
            comps.append({
                "kind": "gpu",
                "vendor": "nvidia",
                "index": i,
                "identity": {
                    "name": s(pynvml.nvmlDeviceGetName),
                    "uuid": s(pynvml.nvmlDeviceGetUUID),
                    "serial": s(pynvml.nvmlDeviceGetSerial),  # empty on GeForce
                    "vbios_version": s(pynvml.nvmlDeviceGetVbiosVersion),
                    "pci_bus_id": to_str(getattr(pci, "busId", None)) if pci else None,
                    "pci_device_id": (f"{pci.pciDeviceId:08x}" if pci else None),
                    "pci_subsystem_id": (f"{pci.pciSubSystemId:08x}" if pci else None),
                },
                "static": {
                    "driver_version": driver,
                    "architecture": safe(lambda: pynvml.nvmlDeviceGetArchitecture(h)),
                    "vram_total_mb": (mem.total // (1024 ** 2)) if mem else None,
                    "max_graphics_clock_mhz": safe(lambda: pynvml.nvmlDeviceGetMaxClockInfo(
                        h, pynvml.NVML_CLOCK_GRAPHICS)),
                    "max_mem_clock_mhz": safe(lambda: pynvml.nvmlDeviceGetMaxClockInfo(
                        h, pynvml.NVML_CLOCK_MEM)),
                    "power_limit_w": safe(lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0),
                    "default_power_limit_w": safe(
                        lambda: pynvml.nvmlDeviceGetPowerManagementDefaultLimit(h) / 1000.0),
                    "ecc_errors_total": safe(lambda: pynvml.nvmlDeviceGetTotalEccErrors(
                        h, pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED, pynvml.NVML_VOLATILE_ECC)),
                    "fan_count": safe(lambda: pynvml.nvmlDeviceGetNumFans(h)),
                    "total_energy_j": safe(lambda: pynvml.nvmlDeviceGetTotalEnergyConsumption(h) / 1000.0),
                    "idle": read_sample(pynvml, h),
                },
            })
    finally:
        safe(pynvml.nvmlShutdown)
    return comps, []
