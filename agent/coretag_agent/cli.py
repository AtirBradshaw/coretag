"""What the user sees.

Double-click (no options): guided mode. Asks "selling or receiving?",
runs the 5-minute test, publishes, opens the report in the browser.

Options for testing / advanced use:
    --quick           sensors only, no load test
    --minutes N       load test length (default 5)
    --claim CODE      buyer mode: compare against the seller's report CODE
    --server URL      use a different Coretag server
    --save            also save the raw data to a .json file
    --yes             don't ask questions (for scripts)
"""

import argparse
import json
import os
import sys
import time
import webbrowser
from datetime import datetime, timezone

from . import SCHEMA, VERSION, client
from .collectors import collect_all
from .collectors.system import collect_system

DEFAULT_SERVER = "http://127.0.0.1:8000"   # changed to the public address once deployed
CLAIM_ALPHABET = set("ACDEFGHJKMNPQRTUVWXY34679")

LINE = "=" * 58


def say(msg=""):
    print(msg, flush=True)


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return ""


def normalize_code(code):
    c = (code or "").strip().upper().replace("-", "").replace(" ", "")
    return c if len(c) == 6 and set(c) <= CLAIM_ALPHABET else None


def guided_intro():
    say(LINE)
    say("  CORETAG  -  measured health report for PC parts")
    say(LINE)
    say()
    say("  Coretag reads your hardware's own sensors and publishes")
    say("  the results at a link you can share.")
    say()
    say("  It is READ-ONLY: nothing on your PC is changed.")
    say()
    say("  Which describes you?")
    say("    1) I'm SELLING this part (create a report for my listing)")
    say("    2) I just RECEIVED this part (compare it with the seller's report)")
    say("    3) A part I SOLD CAME BACK (check it's the one I shipped)")
    say()
    while True:
        choice = ask("  Type 1, 2 or 3 and press ENTER: ").strip()
        if choice in ("1", "2", "3"):
            return {"1": None, "2": "arrival", "3": "return"}[choice]
        say("  Please type 1, 2 or 3.")


def ask_claim_code(server, mode):
    say()
    if mode == "return":
        say("  Enter the 6-character code of the report you made")
        say("  BEFORE you shipped this item.")
    else:
        say("  Enter the 6-character code from the seller's report")
        say("  (it's on the report page, and should have come with the item).")
    while True:
        code = normalize_code(ask("  Code: "))
        if not code:
            say("  That doesn't look like a Coretag code (6 letters/numbers).")
            continue
        try:
            info = client.check_claim(server, code)
        except client.ServerError as e:
            say(f"  Couldn't check the code: {e}")
            return None
        if info.get("valid"):
            say(f"  Found: {info.get('subject')} (report {code})")
            return code
        say("  No report with that code. Check it and try again.")


def build_telemetry(components):
    return {
        "schema": SCHEMA,
        "agent_version": VERSION,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "system": collect_system(),
        "components": components,
    }


def main(argv=None):
    p = argparse.ArgumentParser(prog="coretag", add_help=True)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--minutes", type=float, default=5)
    p.add_argument("--claim")
    p.add_argument("--return", dest="is_return", action="store_true",
                   help="with --claim: you're the seller checking an item that came back")
    p.add_argument("--server", default=os.environ.get("CORETAG_SERVER", DEFAULT_SERVER))
    p.add_argument("--save", action="store_true")
    p.add_argument("--yes", action="store_true")
    args = p.parse_args(argv)

    interactive = sys.stdin.isatty() and not args.yes
    server = args.server
    claim = normalize_code(args.claim) if args.claim else None
    if args.claim and not claim:
        say("That claim code isn't valid (6 letters/numbers).")
        return 2

    mode = "return" if args.is_return else "arrival"
    if interactive and not args.claim and not args.quick:
        chosen = guided_intro()
        if chosen:
            mode = chosen
            claim = ask_claim_code(server, mode)
            if not claim:
                return 1

    # 1) one-time code from the server BEFORE collecting anything, so the
    #    server can tell how long the run really took
    say()
    say("Contacting the Coretag server...")
    try:
        nonce = client.start_session(server)
    except client.ServerError as e:
        say(f"  {e}")
        say("  Check your internet connection and try again.")
        return 1

    # 2) read the hardware
    say("Reading your hardware (read-only)...")
    components, problems = collect_all()
    for c in components:
        name = (c.get("identity") or {}).get("name") or (c.get("identity") or {}).get("model")
        say(f"  found {c['kind']:<5} {name}")
    for msg in problems:
        say(f"  note: {msg}")

    gpus = [c for c in components if c["kind"] == "gpu"]

    # 3) load test
    if gpus and not args.quick and args.minutes > 0:
        mins = args.minutes
        say()
        say(LINE)
        say(f"  LOAD TEST: about {mins:g} minute(s)")
        say("  Coretag is working your graphics card hard. Leave the PC")
        say("  plugged in and don't start games or other heavy programs.")
        say("  Your screen won't change; that's normal.")
        say(LINE)
        from .loadtest import run_load_test
        live = (os.path.join(os.getcwd(), f"coretag_live_{int(time.time())}.jsonl")
                if args.save else None)
        if live:
            say(f"  Live readings are written to {live}")
        try:
            recs = run_load_test(duration_s=mins * 60, progress=say, live_log=live)
        except Exception as e:
            recs = {}
            say(f"  Load test failed: {type(e).__name__}: {e}")
        for g in gpus:
            rec = recs.get(g["identity"].get("uuid"))
            if rec:
                g["load_test"] = rec

    telemetry = build_telemetry(components)

    if args.save:
        path = os.path.join(os.getcwd(), f"coretag_run_{int(time.time())}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(telemetry, f, indent=1)
        say(f"Raw data saved to {path}")

    # 4) send raw readings; the server scores them
    say()
    say("Sending measurements to the server for scoring...")
    try:
        result = client.submit(server, nonce, telemetry, claim, mode if claim else None)
    except client.ServerError as e:
        say(f"  {e}")
        return 1

    say()
    say(LINE)
    say("  YOUR REPORT IS LIVE")
    say(LINE)
    say(f"  {result['subject']}: {result['verdict'].upper()}")
    say()
    say(f"  {result['url']}")
    say()
    say(f"  Report code: {result['id']}")
    for f in result.get("flags") or []:
        say(f"  ! integrity check: {f}")
    open_url = result["url"]

    if claim:
        cmp = result.get("comparison")
        if cmp:
            whose = "YOUR PRE-SHIPPING REPORT" if mode == "return" else "SELLER'S REPORT"
            say()
            say(f"  COMPARISON WITH {whose} {claim}: {cmp['verdict'].replace('_', ' ')}")
            say(f"  {cmp['url']}")
            open_url = cmp["url"]
        else:
            say(f"  Couldn't compare with {claim}: {result.get('claim_error')}")
    else:
        say("  Paste the link into your listing, and include the report")
        say("  code with the item so the buyer can compare on arrival.")
    say()

    if interactive:
        webbrowser.open(open_url)
    return 0


def run():
    """Entry point that never just vanishes: the window stays open on Windows."""
    code = 1
    try:
        code = main()
    except KeyboardInterrupt:
        say("\nCancelled.")
    except Exception as e:
        import traceback
        say(f"\nSomething went wrong: {type(e).__name__}: {e}")
        traceback.print_exc()
    if os.name == "nt" and sys.stdin.isatty() and "--yes" not in sys.argv:
        ask("\nPress ENTER to close this window.")
    return code
