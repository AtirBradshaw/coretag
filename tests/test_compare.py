"""Seller report vs buyer report: every verdict."""

from conftest import (drive_component, gpu_component, gpu_samples, publish,
                      telemetry)


def seller_and_buyer(client, seller_tel, buyer_tel):
    seller = publish(client, seller_tel)
    buyer = publish(client, buyer_tel, claim=seller["id"])
    assert "comparison" in buyer, buyer
    page = client.get(f"/c/{buyer['comparison']['id']}")
    assert page.status_code == 200
    return buyer["comparison"]["verdict"], page.text


def test_match_protects_the_seller(client):
    v, page = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-m", samples=gpu_samples(seed=10))),
        telemetry(gpu_component(uuid="GPU-m", samples=gpu_samples(seed=11, peak=73))))
    assert v == "MATCH"
    assert "Same card, same condition" in page


def test_degraded_when_card_now_throttles(client):
    v, page = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-d", samples=gpu_samples(seed=12))),
        telemetry(gpu_component(uuid="GPU-d", samples=gpu_samples(seed=13, peak=91,
                                                                   throttle_mask=4 | 64))))
    assert v == "DEGRADED"
    assert "Peak temperature rose" in page


def test_different_card(client):
    v, _ = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-orig", samples=gpu_samples(seed=14))),
        telemetry(gpu_component(uuid="GPU-swap", samples=gpu_samples(seed=15))))
    assert v == "DIFFERENT_CARD"


def test_tampered_when_firmware_changes(client):
    v, page = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-t", samples=gpu_samples(seed=16))),
        telemetry(gpu_component(uuid="GPU-t", vbios="94.06.FF.FF.FF", samples=gpu_samples(seed=17))))
    assert v == "TAMPERED"
    assert "VBIOS" in page


def test_inconclusive_when_buyer_skips_load_test(client):
    v, _ = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-i", samples=gpu_samples(seed=18))),
        telemetry(gpu_component(uuid="GPU-i")))
    assert v == "INCONCLUSIVE"


def test_inconclusive_when_a_report_is_flagged(client):
    flat = gpu_samples(seed=19)
    for s in flat:
        s["temp_c"] = 60
    v, _ = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-f", samples=gpu_samples(seed=20))),
        telemetry(gpu_component(uuid="GPU-f", samples=flat)))
    assert v == "INCONCLUSIVE"


def test_drive_errors_increasing_is_degraded(client):
    v, _ = seller_and_buyer(
        client,
        telemetry(gpu_component(uuid="GPU-dr", samples=gpu_samples(seed=21)),
                  drive_component(serial_hash="d1", realloc=0)),
        telemetry(gpu_component(uuid="GPU-dr", samples=gpu_samples(seed=22)),
                  drive_component(serial_hash="d1", realloc=40)))
    assert v == "DEGRADED"


def test_bad_claim_code_still_publishes_buyer_report(client):
    res = publish(client, telemetry(gpu_component(uuid="GPU-x")), claim="AAAAAA")
    assert res["claim_error"]
    assert "comparison" not in res


def test_claim_lookup(client):
    seller = publish(client, telemetry(gpu_component(uuid="GPU-claim")))
    assert client.get(f"/api/v1/claim/{seller['id'].lower()}").json()["valid"] is True
    assert client.get("/api/v1/claim/AAAAAA").json()["valid"] is False


def test_seller_report_links_to_comparison(client):
    seller = publish(client, telemetry(gpu_component(uuid="GPU-link", samples=gpu_samples(seed=23))))
    buyer = publish(client, telemetry(gpu_component(uuid="GPU-link", samples=gpu_samples(seed=24))),
                    claim=seller["id"])
    page = client.get(f"/r/{seller['id']}").text
    assert buyer["comparison"]["id"] in page
