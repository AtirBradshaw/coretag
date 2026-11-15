"""Per-part history pages, the any-code lookup, and the seller's return check."""

from conftest import gpu_component, gpu_samples, publish, telemetry


# ----------------------------------------------------------------------
# return check: the seller tests an item that came back
# ----------------------------------------------------------------------

def test_return_with_a_swapped_card(client):
    shipped = publish(client, telemetry(gpu_component(uuid="GPU-shipped", samples=gpu_samples(seed=30))))
    back = publish(client, telemetry(gpu_component(uuid="GPU-someone-elses", samples=gpu_samples(seed=31))),
                   claim=shipped["id"], claim_mode="return")
    assert back["comparison"]["verdict"] == "DIFFERENT_CARD"
    page = client.get(f"/c/{back['comparison']['id']}").text
    assert "A different card came back" in page
    assert "Shipped vs. returned" in page
    assert ">Returned<" in page and ">Shipped<" in page


def test_return_of_the_same_card(client):
    shipped = publish(client, telemetry(gpu_component(uuid="GPU-roundtrip", samples=gpu_samples(seed=32))))
    back = publish(client, telemetry(gpu_component(uuid="GPU-roundtrip", samples=gpu_samples(seed=33))),
                   claim=shipped["id"], claim_mode="return")
    assert back["comparison"]["verdict"] == "MATCH"
    assert "Same card came back" in client.get(f"/c/{back['comparison']['id']}").text


def test_arrival_wording_is_default(client):
    seller = publish(client, telemetry(gpu_component(uuid="GPU-arr", samples=gpu_samples(seed=34))))
    buyer = publish(client, telemetry(gpu_component(uuid="GPU-arr", samples=gpu_samples(seed=35))),
                    claim=seller["id"])
    page = client.get(f"/c/{buyer['comparison']['id']}").text
    assert "Before shipping vs. on arrival" in page
    assert ">Buyer<" in page


def test_unknown_mode_falls_back_to_arrival(client):
    seller = publish(client, telemetry(gpu_component(uuid="GPU-mode", samples=gpu_samples(seed=36))))
    buyer = publish(client, telemetry(gpu_component(uuid="GPU-mode", samples=gpu_samples(seed=37))),
                    claim=seller["id"], claim_mode="<b>nonsense</b>")
    page = client.get(f"/c/{buyer['comparison']['id']}").text
    assert "Before shipping vs. on arrival" in page


# ----------------------------------------------------------------------
# part pages
# ----------------------------------------------------------------------

def test_part_code_is_stable_across_reports(client):
    a = publish(client, telemetry(gpu_component(uuid="GPU-vin", samples=gpu_samples(seed=40))))
    b = publish(client, telemetry(gpu_component(uuid="GPU-vin")))
    assert a["parts"][0]["code"] == b["parts"][0]["code"]


def test_different_cards_get_different_part_codes(client):
    a = publish(client, telemetry(gpu_component(uuid="GPU-one")))
    b = publish(client, telemetry(gpu_component(uuid="GPU-two")))
    assert a["parts"][0]["code"] != b["parts"][0]["code"]


def test_part_page_lists_every_report_and_comparison(client):
    a = publish(client, telemetry(gpu_component(uuid="GPU-life", samples=gpu_samples(seed=41))))
    b = publish(client, telemetry(gpu_component(uuid="GPU-life", samples=gpu_samples(seed=42))),
                claim=a["id"])
    code = a["parts"][0]["code"]
    page = client.get(f"/p/{code}")
    assert page.status_code == 200
    assert a["id"] in page.text and b["id"] in page.text
    assert b["comparison"]["id"] in page.text
    assert "°C peak under load" in page.text
    # the report page links to its part page
    assert f"/p/{code}" in client.get(f"/r/{a['id']}").text


def test_part_page_warns_when_model_name_changes(client):
    a = publish(client, telemetry(gpu_component(uuid="GPU-shifty")))
    publish(client, telemetry(gpu_component(uuid="GPU-shifty", name="NVIDIA GeForce RTX 3090", vram=24576)))
    page = client.get(f"/p/{a['parts'][0]['code']}").text
    assert "Reported under more than one model name" in page


def test_drive_serial_is_not_shown_on_part_page(client):
    from conftest import drive_component
    a = publish(client, telemetry(drive_component(serial_hash="secret-serial-hash")))
    page = client.get(f"/p/{a['parts'][0]['code']}").text
    assert "secret-serial-hash" not in page


def test_check_later_section_is_hidden_by_default(client):
    rep = publish(client, telemetry(gpu_component(uuid="GPU-hidden")))
    page = client.get(f"/r/{rep['id']}").text
    assert "Checking this item later?" not in page


def test_check_later_section_can_be_switched_back_on(client):
    from server.app.main import templates
    rep = publish(client, telemetry(gpu_component(uuid="GPU-shown")))
    templates.env.globals["show_check_later"] = True
    try:
        page = client.get(f"/r/{rep['id']}").text
    finally:
        templates.env.globals["show_check_later"] = False
    assert "Checking this item later?" in page
    assert "A part I sold came back" in page
    assert rep["id"] in page


def test_go_resolves_every_kind_of_code(client):
    a = publish(client, telemetry(gpu_component(uuid="GPU-go", samples=gpu_samples(seed=43))))
    b = publish(client, telemetry(gpu_component(uuid="GPU-go", samples=gpu_samples(seed=44))),
                claim=a["id"])
    for code, prefix in ((a["id"], "/r/"), (b["comparison"]["id"], "/c/"),
                         (a["parts"][0]["code"], "/p/")):
        r = client.get(f"/go/{code.lower()}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == prefix + code
    assert client.get("/go/AAAAAA").status_code == 404
    assert client.get("/p/AAAAAA").status_code == 404
