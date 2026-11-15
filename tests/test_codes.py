"""Two-word codes: the word lists stay clean, typing variations work, old
six-character links keep working, and a crowded code space never fails."""

import re

import pytest

from conftest import gpu_component, gpu_samples, publish, telemetry
from server.app import ids
from server.app.words import ADJECTIVES, NOUNS

# Words that must never appear on their own, whatever someone adds later.
NEVER = {
    # verdict-like, alarming or negative
    "dead", "broken", "bad", "hot", "cold", "cool", "warm", "cozy", "fast",
    "slow", "swift", "fake", "scam", "burnt", "burn", "fire", "lemon", "brick",
    "toast", "potato", "dud", "junk", "trash", "scrap", "rust", "rusty",
    "fail", "error", "crash", "lag", "glitch", "bug", "virus", "worm", "ghost",
    "zombie", "skull", "bomb", "gun", "knife", "kill", "death", "mint",
    "perfect", "new", "used", "old", "vintage", "certified", "verified",
    "honest", "trusty", "safe", "tested", "cheetah", "cactus", "bronze",
    "silver", "humming", "whistling", "skipping", "drifting", "fiddle",
    "frost", "ember", "smoke", "storm", "thunder", "patchwork", "snail",
    # crude or slang-suggestive
    "ass", "beaver", "booby", "shag", "tit", "butt", "crab", "tart",
    "crumpet", "fudge", "chick", "filly", "colt", "turkey", "mule",
    "swallow", "thrush", "shrew", "rape", "nig", "anal", "sex",
    # brands
    "apple", "jaguar", "falcon", "titan", "camel", "lotus", "corsair",
    "mustang", "puma", "cobra", "viper", "phoenix", "azure",
}
# Fragments that must not appear even inside a longer word.
NEVER_INSIDE = ("fuck", "shit", "piss", "cunt", "slut", "whore", "bitch",
                "nazi", "porn", "kkk", "cock", "dick")


# ----------------------------------------------------------------------
# the word lists themselves
# ----------------------------------------------------------------------

def test_words_are_short_lowercase_and_unique():
    for w in ADJECTIVES + NOUNS:
        assert re.fullmatch(r"[a-z]{3,9}", w), w
    assert len(set(ADJECTIVES)) == len(ADJECTIVES)
    assert len(set(NOUNS)) == len(NOUNS)
    assert not set(ADJECTIVES) & set(NOUNS)


def test_no_banned_words():
    words = set(ADJECTIVES) | set(NOUNS)
    assert not words & NEVER, sorted(words & NEVER)
    inside = [w for w in words for frag in NEVER_INSIDE if frag in w]
    assert not inside, inside


def test_enough_combinations():
    assert len(ADJECTIVES) * len(NOUNS) >= 80_000


# ----------------------------------------------------------------------
# generating and reading codes
# ----------------------------------------------------------------------

def test_new_codes_are_two_words():
    for _ in range(200):
        adj, noun = ids.new_id().split("-")
        assert adj in ADJECTIVES and noun in NOUNS


def test_crowded_space_adds_a_number():
    code = ids.new_id(2)
    adj, noun, num = code.split("-")
    assert adj in ADJECTIVES and noun in NOUNS and re.fullmatch(r"\d\d", num)


@pytest.mark.parametrize("typed", [
    "amber-otter", "Amber-Otter", "AMBER OTTER", "  amber   otter ",
    "amber_otter", "amberotter", "amber.otter", "amber--otter",
])
def test_typing_variations(typed):
    assert ids.normalize(typed) == "amber-otter"


@pytest.mark.parametrize("typed,expected", [
    ("amber-otter-42", "amber-otter-42"),
    ("Amber Otter 42", "amber-otter-42"),
    ("amberotter42", "amber-otter-42"),
])
def test_typing_variations_with_number(typed, expected):
    assert ids.normalize(typed) == expected


@pytest.mark.parametrize("typed", [
    "otter-amber",          # wrong order
    "amber-pizza",          # not in the list
    "amber",                # one word
    "amber-otter-12345",    # number too long
    "not-a-code", "", "   ", None, 42,
])
def test_rejects_non_codes(typed):
    assert ids.normalize(typed) is None


def test_old_six_character_codes_still_read():
    assert ids.normalize("u9pnuk") == "U9PNUK"
    assert ids.normalize("U9P-NUK") == "U9PNUK"
    assert ids.normalize("U9PNUO") is None    # O was never in old codes


# ----------------------------------------------------------------------
# through the website
# ----------------------------------------------------------------------

def test_reports_get_word_codes(client):
    rep = publish(client, telemetry(gpu_component(uuid="GPU-words")))
    assert ids.normalize(rep["id"]) == rep["id"]
    assert "-" in rep["id"] and rep["url"].endswith("/r/" + rep["id"])
    assert "-" in rep["parts"][0]["code"]


def test_lookup_accepts_how_people_type(client):
    rep = publish(client, telemetry(gpu_component(uuid="GPU-typing")))
    spoken = rep["id"].replace("-", " ").upper()           # "AMBER OTTER"
    r = client.get(f"/go/{spoken}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/r/{rep['id']}"
    assert client.get(f"/r/{rep['id'].upper()}").status_code == 200


def test_claim_code_typed_loosely_still_pairs(client):
    seller = publish(client, telemetry(gpu_component(uuid="GPU-loose", samples=gpu_samples(seed=50))))
    loose = seller["id"].replace("-", " ").title()          # "Amber Otter"
    assert client.get(f"/api/v1/claim/{loose}").json()["report_id"] == seller["id"]
    buyer = publish(client, telemetry(gpu_component(uuid="GPU-loose", samples=gpu_samples(seed=51))),
                    claim=loose)
    assert buyer["comparison"]["verdict"] == "MATCH"


def test_old_style_report_links_keep_working(client, monkeypatch):
    # the next code issued is an old-style one (as if made before word codes);
    # everything after that is a normal word code
    real_new_id, first = ids.new_id, iter(["C3DFGH"])
    monkeypatch.setattr(ids, "new_id", lambda digits=0: next(first, None) or real_new_id(digits))
    old = publish(client, telemetry(gpu_component(uuid="GPU-legacy")))
    monkeypatch.undo()
    assert old["id"] == "C3DFGH"
    assert client.get("/r/c3d-fgh").status_code == 200
    assert client.get("/go/C3DFGH", follow_redirects=False).headers["location"] == "/r/C3DFGH"


def test_codes_never_collide_and_grow_a_number_when_crowded(client, monkeypatch):
    # shrink the word lists to a single word each: the first code takes the
    # only two-word combination, so the next must fall back to a number
    monkeypatch.setattr(ids, "ADJECTIVES", ("amber",))
    monkeypatch.setattr(ids, "NOUNS", ("otter",))
    first = publish(client, telemetry(gpu_component(uuid="GPU-crowd-1")))
    second = publish(client, telemetry(gpu_component(uuid="GPU-crowd-2")))
    codes = {first["id"], second["id"], first["parts"][0]["code"], second["parts"][0]["code"]}
    assert len(codes) == 4                       # unique across reports AND parts
    assert all(c.startswith("amber-otter") for c in codes)
    assert any(re.fullmatch(r"amber-otter-\d{2,4}", c) for c in codes)
    for c in codes:
        assert client.get(f"/go/{c}", follow_redirects=False).status_code == 303
