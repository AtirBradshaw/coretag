import math
import os
import random
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# each test run gets its own throwaway database
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ.pop("RENDER_EXTERNAL_URL", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from server.app import db  # noqa: E402
from server.app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def gpu_samples(*, seconds=300, peak=70, power=165, limit=170, core=1800,
                throttle_mask=4, noise=True, seed=1, idle_first=2, util=99):
    """A realistic recording: a couple of idle samples, then a card warming
    from 40 °C toward its peak with sensor noise."""
    rnd = random.Random(seed)
    j = (lambda a: rnd.uniform(-a, a)) if noise else (lambda a: 0)
    out = []
    for i in range(int(seconds / 2)):
        t = i * 2 + j(0.05)
        if i < idle_first:
            out.append({"t": round(t, 2), "temp_c": 40, "core_mhz": 210, "power_w": 18.0,
                        "util_pct": 2, "fan_pct": 30, "throttle_mask": 1})
            continue
        warm = 1 - math.exp(-(t - idle_first * 2) / 60)
        out.append({
            "t": round(t, 2),
            "temp_c": round(40 + (peak - 40) * warm + j(0.6)),
            "core_mhz": round(core + j(25)),
            "power_w": round(min(limit, power + j(4)), 2),
            "util_pct": util,
            "fan_pct": round(35 + 30 * warm),
            "throttle_mask": throttle_mask,
        })
    return out


def gpu_component(*, name="NVIDIA GeForce RTX 3060", uuid="GPU-1111-aaaa", vram=12288,
                  vbios="94.06.2F.00.9A", limit=170.0, samples=None, renderer="NVIDIA GeForce RTX 3060/PCIe/SSE2"):
    comp = {
        "kind": "gpu", "vendor": "nvidia",
        "identity": {"name": name, "uuid": uuid, "vbios_version": vbios,
                     "pci_device_id": "250310de"},
        "static": {"vram_total_mb": vram, "power_limit_w": limit, "default_power_limit_w": limit,
                   "max_graphics_clock_mhz": 2100, "fan_count": 2, "ecc_errors_total": None,
                   "driver_version": "610.88"},
    }
    if samples is not None:
        comp["load_test"] = {"interval_s": 2.0, "load_source": "coretag_builtin",
                             "renderer": renderer, "samples": samples}
    return comp


def drive_component(*, model="Samsung SSD 980 1TB", serial_hash="abc123", hours=4200,
                    realloc=None, media=0, written=18.4):
    return {"kind": "drive",
            "identity": {"model": model, "serial_hash": serial_hash},
            "static": {"type": "NVMe SSD", "smart_passed": True, "power_on_hours": hours,
                       "percentage_used": 3, "data_written_tb": written,
                       "reallocated_sectors": realloc, "media_errors": media,
                       "capacity_gb": 1000.2}}


def telemetry(*components):
    return {"schema": 2, "agent_version": "0.2.0-test", "collected_at": "2026-11-11T00:00:00Z",
            "system": {"os": "Windows", "os_version": "11", "cpu": "Test CPU"},
            "components": list(components)}


def publish(client, tel, *, claim=None, claim_mode=None, session_age_s=400, expect=200):
    """Do what the agent does: get a nonce, then submit. The nonce's issue
    time is backdated so a 5-minute recording fits inside the session."""
    nonce = client.post("/api/v1/session").json()["nonce"]
    with db.engine.begin() as c:
        c.execute(update(db.sessions).where(db.sessions.c.nonce == nonce)
                  .values(issued_at=db.utcnow() - timedelta(seconds=session_age_s)))
    body = {"nonce": nonce, "telemetry": tel}
    if claim:
        body["claim_code"] = claim
    if claim_mode:
        body["claim_mode"] = claim_mode
    r = client.post("/api/v1/report", json=body)
    assert r.status_code == expect, r.text
    return r.json()
