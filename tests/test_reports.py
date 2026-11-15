from server.app import db
from conftest import (drive_component, gpu_component, gpu_samples, publish,
                      telemetry)


def report_result(rid):
    return db.get_report(rid)["result"]


# ----------------------------------------------------------------------
# honest hardware must come back clean
# ----------------------------------------------------------------------

def test_healthy_card_comes_back_clean(client):
    res = publish(client, telemetry(gpu_component(samples=gpu_samples()), drive_component()))
    assert res["verdict"] == "pass", report_result(res["id"])["findings"]
    assert res["flags"] == []
    page = client.get(f"/r/{res['id']}")
    assert page.status_code == 200
    assert "Nothing flagged" in page.text
    assert res["id"] in page.text


def test_power_cap_is_not_a_fault(client):
    # sw_power_cap (bit 4) on every sample: the card sitting at its limit
    res = publish(client, telemetry(gpu_component(samples=gpu_samples(throttle_mask=4))))
    titles = [f["title"] for f in report_result(res["id"])["findings"]]
    assert "Drawing full rated power" in titles
    assert not any("throttl" in t.lower() for t in titles)


def test_fully_busy_card_below_power_limit_is_conclusive(client):
    # what a real RTX 3060 did on Coretag's load: 100% busy, top clock,
    # ~135 of 170 W, never at the power cap
    samples = gpu_samples(seed=7, power=135, peak=60, core=1942, throttle_mask=0, util=100)
    res = publish(client, telemetry(gpu_component(uuid="GPU-3060-real", samples=samples)))
    titles = [f["title"] for f in report_result(res["id"])["findings"]]
    assert "Load test inconclusive" not in titles
    assert "Cooling performing normally" in titles
    assert res["verdict"] == "pass", titles


def test_half_busy_card_is_inconclusive(client):
    samples = gpu_samples(seed=8, power=135, throttle_mask=0, util=70)
    res = publish(client, telemetry(gpu_component(uuid="GPU-half", samples=samples)))
    found = {f["title"]: f for f in report_result(res["id"])["findings"]}
    assert "Load test inconclusive" in found
    assert "70% busy" in found["Load test inconclusive"]["detail"]


def test_real_thermal_throttling_is_reported(client):
    res = publish(client, telemetry(gpu_component(samples=gpu_samples(peak=92, throttle_mask=4 | 64))))
    assert res["verdict"] == "caution"
    titles = [f["title"] for f in report_result(res["id"])["findings"]]
    assert "Thermal throttling under load" in titles


# ----------------------------------------------------------------------
# identity checks
# ----------------------------------------------------------------------

def test_laptop_gpu_is_not_accused_of_being_fake(client):
    comp = gpu_component(name="NVIDIA GeForce RTX 3060 Laptop GPU", vram=6144, limit=115.0,
                         uuid="GPU-laptop-1", samples=gpu_samples(power=110, limit=115))
    res = publish(client, telemetry(comp))
    sevs = {f["severity"] for f in report_result(res["id"])["findings"]}
    assert "fail" not in sevs
    assert res["verdict"] == "pass"


def test_desktop_card_with_wrong_memory_fails(client):
    comp = gpu_component(vram=6144, uuid="GPU-fake-3060")
    res = publish(client, telemetry(comp))
    assert res["verdict"] == "fail"


def test_ti_super_not_matched_as_plain_4070(client):
    from server.app.scoring.gpu import lookup_spec
    assert lookup_spec("NVIDIA GeForce RTX 4070 Ti SUPER")[0] == "rtx 4070 ti super"
    assert lookup_spec("NVIDIA GeForce RTX 3060 Ti")[0] == "rtx 3060 ti"
    assert lookup_spec("NVIDIA GeForce RTX 3060 Laptop GPU")[0] is None


# ----------------------------------------------------------------------
# anti-tamper
# ----------------------------------------------------------------------

def test_nonce_cannot_be_replayed(client):
    nonce = client.post("/api/v1/session").json()["nonce"]
    tel = telemetry(gpu_component())
    assert client.post("/api/v1/report", json={"nonce": nonce, "telemetry": tel}).status_code == 200
    assert client.post("/api/v1/report", json={"nonce": nonce, "telemetry": tel}).status_code == 409


def test_forged_nonce_rejected(client):
    r = client.post("/api/v1/report", json={"nonce": "made-up-nonce-1234", "telemetry": telemetry()})
    assert r.status_code == 409


def test_flat_temperature_is_flagged(client):
    samples = gpu_samples(seed=3)
    for s in samples:
        s["temp_c"] = 65
    res = publish(client, telemetry(gpu_component(uuid="GPU-flat", samples=samples)))
    codes = {f["code"] for f in report_result(res["id"])["flags"]}
    assert "flat_temperature" in codes
    assert res["verdict"] != "pass"


def test_constant_power_and_too_low_power_flagged(client):
    samples = gpu_samples(seed=4)
    for s in samples:
        s["power_w"] = 30.0
    res = publish(client, telemetry(gpu_component(uuid="GPU-lowpower", samples=samples)))
    codes = {f["code"] for f in report_result(res["id"])["flags"]}
    assert {"constant_power", "power_too_low"} <= codes


def test_recording_longer_than_session_flagged(client):
    res = publish(client, telemetry(gpu_component(uuid="GPU-fast", samples=gpu_samples())),
                  session_age_s=30)
    codes = {f["code"] for f in report_result(res["id"])["flags"]}
    assert "longer_than_session" in codes


def test_no_thermal_rise_flagged(client):
    samples = gpu_samples(seed=5, peak=41)
    res = publish(client, telemetry(gpu_component(uuid="GPU-cold", samples=samples)))
    codes = {f["code"] for f in report_result(res["id"])["flags"]}
    assert "no_thermal_rise" in codes


def test_same_uuid_different_model_flagged(client):
    publish(client, telemetry(gpu_component(uuid="GPU-chameleon")))
    res = publish(client, telemetry(gpu_component(uuid="GPU-chameleon",
                                                  name="NVIDIA GeForce RTX 3080", vram=10240)))
    codes = {f["code"] for f in report_result(res["id"])["flags"]}
    assert "identity_changed" in codes


def test_drive_hours_going_backwards_flagged(client):
    publish(client, telemetry(drive_component(serial_hash="rollback", hours=9000)))
    res = publish(client, telemetry(drive_component(serial_hash="rollback", hours=100)))
    codes = {f["code"] for f in report_result(res["id"])["flags"]}
    assert "hours_went_backwards" in codes


def test_agent_text_is_escaped_on_the_page(client):
    comp = gpu_component(name='<script>alert("x")</script>', uuid="GPU-xss")
    res = publish(client, telemetry(comp))
    page = client.get(f"/r/{res['id']}").text
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_garbage_input_does_not_crash(client):
    tel = {"components": [{"kind": "gpu", "identity": "nope", "static": [1, 2],
                           "load_test": {"samples": [None, {"t": "x"}, {"t": True}]}},
                          {"kind": "drive", "static": {"power_on_hours": "lots"}}, 7, "x"]}
    nonce = client.post("/api/v1/session").json()["nonce"]
    r = client.post("/api/v1/report", json={"nonce": nonce, "telemetry": tel})
    assert r.status_code == 200
    assert client.get(f"/r/{r.json()['id']}").status_code == 200


def test_unknown_report_is_404(client):
    assert client.get("/r/AAAAAA").status_code == 404
    assert client.get("/r/not-a-code").status_code == 404


def test_history_lists_every_report_for_a_card(client):
    publish(client, telemetry(gpu_component(uuid="GPU-hist")))
    publish(client, telemetry(gpu_component(uuid="GPU-hist")))
    h = client.get("/api/v1/history/gpu:GPU-hist").json()
    assert len(h["reports"]) == 2
