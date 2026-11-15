"""Coretag server.

Start it on your own PC with:
    uvicorn server.app.main:app --reload

Routes
    POST /api/v1/session          issue a one-time nonce (30-minute lifetime)
    POST /api/v1/report           validate nonce, score raw telemetry, store, return link
    GET  /api/v1/claim/{code}     does this claim code exist? (agent checks before testing)
    GET  /api/v1/report/{id}      the raw telemetry and the server's result, for auditing
    GET  /api/v1/history/{hw_id}  every report ever filed for one physical part
    GET  /r/{id}                  the public report page
    GET  /c/{pair_id}             the public comparison page (arrival or return)
    GET  /p/{code}                one physical part's full history (its "VIN" page)
    GET  /go/{code}               opens whatever a code belongs to
    GET  /                        landing page
"""

import json
import os
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import compare, db, ids
from .render import thermal_trace
from .scoring import VERDICT_COPY, score_report

HERE = Path(__file__).parent
MAX_BODY_BYTES = 2_000_000
NONCE_TTL = timedelta(minutes=30)

db.init()

app = FastAPI(title="Coretag", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")  # autoescapes everything
templates.env.globals["thermal_trace"] = thermal_trace


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


def public_base(request: Request) -> str:
    """The address people should use to open links. Render tells us its
    public address; on your own PC we use whatever address was requested."""
    base = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    return (base or str(request.base_url)).rstrip("/")


def error(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


# ----------------------------------------------------------------------
# API used by the agent
# ----------------------------------------------------------------------

@app.post("/api/v1/session")
def new_session():
    nonce, issued = db.issue_nonce()
    return {"nonce": nonce, "expires_in_s": int(NONCE_TTL.total_seconds()),
            "server_time": issued.isoformat() + "Z"}


@app.get("/api/v1/claim/{code}")
def check_claim(code: str):
    rid = ids.normalize(code)
    rep = db.get_report(rid) if rid else None
    if not rep:
        return {"valid": False}
    return {"valid": True, "report_id": rep["id"], "subject": rep["subject"],
            "created_at": rep["created_at"].isoformat() + "Z"}


@app.post("/api/v1/report")
async def submit_report(request: Request):
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        error(413, "report too large")
    try:
        data = json.loads(body)
    except ValueError:
        error(400, "body is not valid JSON")
    if not isinstance(data, dict):
        error(400, "body must be a JSON object")

    telemetry = data.get("telemetry")
    if not isinstance(telemetry, dict):
        error(400, "missing telemetry")

    issued_at = db.consume_nonce(data.get("nonce"), NONCE_TTL)
    if issued_at is None:
        error(409, "this run's one-time code is invalid, expired or already used. "
                   "Please run Coretag again.")

    elapsed = (db.utcnow() - issued_at).total_seconds()
    result = score_report(telemetry, session_elapsed_s=elapsed, history_lookup=db.history)
    report_id, created_at = db.store_report(telemetry=telemetry, result=result,
                                            session_issued_at=issued_at)
    base = public_base(request)
    parts = []
    for comp in result["components"]:
        if comp.get("hardware_id"):
            code = db.part_code(comp["hardware_id"], comp["kind"])
            parts.append({"code": code, "label": comp["label"], "url": f"{base}/p/{code}"})
    resp = {
        "id": report_id,
        "url": f"{base}/r/{report_id}",
        "verdict": result["verdict"],
        "subject": result["subject"],
        "flags": [f["title"] for f in result["flags"]],
        "parts": parts,
    }

    # --- comparison: pair this fresh run with an earlier report.
    # "arrival" = buyer checking what they received; "return" = seller
    # checking an item that came back.
    claim = data.get("claim_code")
    mode = data.get("claim_mode") if data.get("claim_mode") in compare.MODES else "arrival"
    if claim:
        seller_id = ids.normalize(claim)
        seller = db.get_report(seller_id) if seller_id else None
        if not seller:
            resp["claim_error"] = "claim code not found"
        elif seller["id"] == report_id or seller["created_at"] >= created_at:
            resp["claim_error"] = "claim code must refer to an earlier report"
        else:
            buyer = db.get_report(report_id)
            cmp = compare.compare(seller, buyer, mode=mode)
            pair_id = db.store_comparison(seller_report_id=seller["id"],
                                          buyer_report_id=report_id, result=cmp)
            resp["comparison"] = {"id": pair_id, "url": f"{base}/c/{pair_id}",
                                  "verdict": cmp["verdict"]}
    return resp


@app.get("/api/v1/report/{report_id}")
def report_json(report_id: str):
    rid = ids.normalize(report_id)
    rep = db.get_report(rid) if rid else None
    if not rep:
        error(404, "no such report")
    return JSONResponse({
        "id": rep["id"], "created_at": rep["created_at"].isoformat() + "Z",
        "result": rep["result"], "telemetry": rep["telemetry"]})


@app.get("/api/v1/history/{hardware_id}")
def hardware_history(hardware_id: str):
    rows = db.history(hardware_id[:160])
    return {"hardware_id": hardware_id,
            "reports": [{"report_id": r["report_id"], "label": r["label"],
                         "verdict": r["verdict"],
                         "created_at": r["created_at"].isoformat() + "Z"} for r in rows]}


@app.get("/healthz")
def health():
    # which kind of database is in use ("postgresql" in production; "sqlite"
    # there would mean DATABASE_URL is missing and reports won't survive a restart)
    return {"ok": True, "database": db.engine.dialect.name}


# ----------------------------------------------------------------------
# pages
# ----------------------------------------------------------------------

def not_found(request, what):
    return templates.TemplateResponse(request, "not_found.html", {"what": what},
                                      status_code=404)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/r/{report_id}", response_class=HTMLResponse)
def report_page(request: Request, report_id: str):
    rid = ids.normalize(report_id)
    rep = db.get_report(rid) if rid else None
    if not rep:
        return not_found(request, "report")
    res = rep["result"]
    part_links = []
    for comp in res["components"]:
        if comp.get("hardware_id"):
            part_links.append({
                "label": comp["label"], "kind": comp["kind"],
                "code": db.part_code(comp["hardware_id"], comp["kind"]),
                "count": len(db.history(comp["hardware_id"], limit=500))})
    counts = {k: sum(1 for f in res["findings"] if f["severity"] == k)
              for k in ("fail", "caution", "pass")}
    title_text, sub_text = VERDICT_COPY[res["verdict"]]
    return templates.TemplateResponse(request, "report.html", {
        "rep": rep, "res": res, "counts": counts, "part_links": part_links,
        "title_text": title_text, "sub_text": sub_text,
        "comparisons": db.comparisons_for(rep["id"]),
        "base": public_base(request)})


@app.get("/p/{code}", response_class=HTMLResponse)
def part_page(request: Request, code: str):
    """Every report ever filed for one physical part, like a vehicle history report."""
    pc = ids.normalize(code)
    part = db.get_part(pc) if pc else None
    if not part:
        return not_found(request, "part")
    rows = db.history(part["hardware_id"], limit=500)
    cmps = db.comparisons_for(*[r["report_id"] for r in rows])
    names = []
    for r in rows:
        if r["label"] and r["label"] not in names:
            names.append(r["label"])
    return templates.TemplateResponse(request, "part.html", {
        "part": part, "rows": rows, "comparisons": cmps, "names": names,
        "label": rows[-1]["label"] if rows else part["kind"].upper()})


@app.get("/go/{code}")
def lookup(request: Request, code: str):
    """One box for any code: report, comparison or part."""
    c = ids.normalize(code)
    if c and db.get_report(c):
        return RedirectResponse(f"/r/{c}", status_code=303)
    if c and db.get_comparison(c):
        return RedirectResponse(f"/c/{c}", status_code=303)
    if c and db.get_part(c):
        return RedirectResponse(f"/p/{c}", status_code=303)
    return not_found(request, "report, comparison or part")


@app.get("/c/{pair_id}", response_class=HTMLResponse)
def comparison_page(request: Request, pair_id: str):
    pid = ids.normalize(pair_id)
    cmp = db.get_comparison(pid) if pid else None
    if not cmp:
        return not_found(request, "comparison")
    seller = db.get_report(cmp["seller_report_id"])
    buyer = db.get_report(cmp["buyer_report_id"])
    labels = cmp["result"].get("labels") or list(compare.LABELS["arrival"])
    return templates.TemplateResponse(request, "compare.html", {
        "cmp": cmp, "res": cmp["result"], "seller": seller, "buyer": buyer,
        "labels": labels})
