# Coretag

**Measured health reports for used PC components.**

The used GPU market is a lemons market: buyers can't tell a mined-on card from a clean one, so they
discount everything, which taxes honest sellers. Coretag reads a component's own sensors and firmware,
puts it under load, and publishes the measurements at a permanent link a seller can paste into any listing.

When the item arrives, the buyer runs Coretag with the seller's report code. The server compares the
two runs (same card? same condition?) and publishes the comparison. A shipping dispute becomes a data diff.
The same check protects sellers against return fraud: if an item comes back, the seller runs Coretag
with their own pre-shipping code and learns whether the card they got back is the card they shipped.

## Identity: two kinds of code

| Code | Example | Identifies | Where it comes from |
|---|---|---|---|
| Hardware ID | `GPU-786b253b-…` | one physical part | built in at the factory (NVIDIA UUID, drive serial); Coretag reads it, never assigns it |
| Part code | `/p/K7MQ3D` | that part's public history page | assigned the first time Coretag sees the hardware ID, and only ever looked up *by* it |
| Report code | `/r/3YTFF6` | one test run | issued by the server per run; also the claim code a buyer or returning seller enters |
| Comparison code | `/c/9HXT4A` | one earlier-vs-later pairing | issued when a claim is made |

Drive serial numbers are stored only as a one-way fingerprint and never shown.

> Coretag is a record of measurements, **not** a certification or warranty. Every finding shows the
> raw value it came from, and every report states what it cannot see.

## How it works

```
 agent (seller's PC)                         server
 ───────────────────                         ──────
 1. ask for a one-time code   ─────────────▶ issue nonce (single use, 30-minute lifetime)
 2. read sensors + 5-min load test
 3. send RAW readings + code  ─────────────▶ check code, compute every statistic itself,
                                              run integrity checks, score, store
 4. show link                 ◀───────────── /r/A4F9KC
```

The agent never computes a score. A verdict calculated on the seller's machine is a verdict the
seller can edit.

## What's in this repository

| Folder | What it is |
|---|---|
| `agent/` | The program people run. `coretag.py` is the entry point. |
| `agent/coretag_agent/collectors/` | One file per kind of hardware: NVIDIA GPUs (NVML), drives (smartctl). |
| `server/app/` | The FastAPI website: API, scoring, integrity checks, comparison engine, pages. |
| `server/app/scoring/` | One scorer per kind of hardware, plus `integrity.py` (forgery checks). |
| `server/app/specs/` | Reference specs for desktop NVIDIA cards. |
| `tests/` | Automatic tests, including forged and tampered data. |

Adding a new kind of part = one collector in `agent/coretag_agent/collectors/`, one scorer in
`server/app/scoring/`, and registering both.

## Running it yourself

You need Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests
.venv\Scripts\python -m uvicorn server.app.main:app
```

Then in another window:

```bash
python agent\coretag.py --server http://127.0.0.1:8000
```

Without `--server`, the agent uses the live service at https://coretag.onrender.com.

Agent options: `--quick` (no load test), `--minutes N`, `--claim CODE` (buyer checking an
arrival), `--claim CODE --return` (seller checking a returned item), `--save` (keep the raw data,
written live during the load test so it survives a crash), `--server URL`.

The load test stops itself if the GPU reaches 93 °C or its hardware protection keeps engaging.

## Known limits

- NVIDIA on Windows only, for now. No AMD or Intel Arc yet.
- Consumer GeForce cards expose no serial number and no memory-error counters; the GPU UUID is the identity anchor.
- A modified agent can still send invented readings. No software-only tool can prevent that. The
  goal is making forgery harder than honesty and detectable afterwards, and every report's raw data is
  public at `/api/v1/report/{id}` for anyone to audit.

## Licence

Source-available, **not** open source. You may read and audit the code. See `LICENSE.txt`.
