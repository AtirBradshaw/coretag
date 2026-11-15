"""Storage.

Runs on SQLite on your own PC (a single file, nothing to install) and on
Postgres in production. Which one is decided by the DATABASE_URL setting:

    not set                    -> sqlite file  coretag.db  next to where you start the server
    postgres://... or
    postgresql://...           -> hosted Postgres (Neon, Supabase, Render...)

Every timestamp is stored as UTC without a timezone marker, so the two
databases behave identically.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table,
                        Text, create_engine, insert, select, update)
from sqlalchemy import text as sql
from sqlalchemy.exc import IntegrityError
from . import ids

metadata = MetaData()

sessions = Table(
    "sessions", metadata,
    Column("nonce", String(64), primary_key=True),
    Column("issued_at", DateTime, nullable=False),
    Column("used_at", DateTime, nullable=True),
)

reports = Table(
    "reports", metadata,
    Column("id", String(32), primary_key=True),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("session_issued_at", DateTime, nullable=False),
    Column("agent_version", String(32)),
    Column("verdict", String(16), nullable=False),
    Column("flag_count", Integer, nullable=False, default=0),
    Column("subject", String(200)),
    Column("telemetry", Text, nullable=False),   # exactly what the agent sent
    Column("result", Text, nullable=False),      # what the server concluded
)

# One row per physical component per report: lets us list every report
# ever filed for one card, and spot a card whose identity changes.
hardware = Table(
    "hardware", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("hardware_id", String(160), nullable=False, index=True),
    Column("report_id", String(32), nullable=False, index=True),
    Column("kind", String(16), nullable=False),
    Column("label", String(200)),
    Column("created_at", DateTime, nullable=False),
    Column("snapshot", Text),                    # key facts, for cross-checks
)

# A short, public code for each physical part (its "VIN"), assigned the first
# time Coretag sees that part's factory ID. The code is only ever looked up
# BY the factory ID, so it can't be moved to a different card.
parts = Table(
    "parts", metadata,
    Column("code", String(32), primary_key=True),
    Column("hardware_id", String(160), nullable=False, unique=True),
    Column("kind", String(16), nullable=False),
    Column("first_seen", DateTime, nullable=False),
)

comparisons = Table(
    "comparisons", metadata,
    Column("pair_id", String(32), primary_key=True),
    Column("seller_report_id", String(32), nullable=False, index=True),
    Column("buyer_report_id", String(32), nullable=False, index=True),
    Column("verdict", String(24), nullable=False),
    Column("result", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

engine = None


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///./coretag.db"
    # hosted providers hand out postgres:// URLs; SQLAlchemy wants the driver named
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def init(url: str | None = None):
    global engine
    url = url or database_url()
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    metadata.create_all(engine)
    _upgrade(engine)
    return engine


# Columns that hold a Coretag code. The first live tables were created when
# codes were 6 characters (VARCHAR(12)); word codes like "lavender-butterfly"
# need more room. create_all() never changes existing tables, so widen them
# here. Safe to run on every start: it only acts on columns still too narrow.
# (SQLite ignores VARCHAR lengths, so this only matters on Postgres.)
CODE_COLUMNS = [("reports", "id"), ("hardware", "report_id"),
                ("parts", "code"), ("comparisons", "pair_id"),
                ("comparisons", "seller_report_id"),
                ("comparisons", "buyer_report_id")]


def _upgrade(eng):
    if eng.dialect.name != "postgresql":
        return
    with eng.begin() as c:
        for table, column in CODE_COLUMNS:
            size = c.execute(sql(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"),
                {"t": table, "c": column}).scalar()
            if size is not None and size < 32:
                c.execute(sql(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE VARCHAR(32)'))


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------------
# nonces
# ----------------------------------------------------------------------

def issue_nonce() -> tuple[str, datetime]:
    import secrets
    nonce = secrets.token_urlsafe(32)
    now = utcnow()
    with engine.begin() as c:
        c.execute(insert(sessions).values(nonce=nonce, issued_at=now))
    return nonce, now


def consume_nonce(nonce: str, ttl: timedelta) -> datetime | None:
    """Mark a nonce used. Returns when it was issued, or None if it was
    unknown, expired or already used. A single UPDATE does the check and
    the marking together, so two simultaneous uploads can't both win."""
    if not isinstance(nonce, str) or not (8 <= len(nonce) <= 64):
        return None
    now = utcnow()
    with engine.begin() as c:
        res = c.execute(
            update(sessions)
            .where(sessions.c.nonce == nonce)
            .where(sessions.c.used_at.is_(None))
            .where(sessions.c.issued_at > now - ttl)
            .values(used_at=now))
        if res.rowcount != 1:
            return None
        row = c.execute(select(sessions.c.issued_at)
                        .where(sessions.c.nonce == nonce)).first()
    return row.issued_at if row else None


# ----------------------------------------------------------------------
# reports
# ----------------------------------------------------------------------

def _code_taken(conn, code: str) -> bool:
    """Codes are unique across reports, comparisons AND parts, so the one
    lookup box can always tell which a code belongs to."""
    for col in (reports.c.id, comparisons.c.pair_id, parts.c.code):
        if conn.execute(select(col).where(col == code)).first() is not None:
            return True
    return False


def _insert_with_fresh_id(conn, table, id_col, values):
    """Pick a random code that isn't taken yet. Two words first; if those
    keep colliding (the space is getting crowded), add a number, then a
    longer one, so a code can always be issued. (The primary key would still
    reject a duplicate if two uploads raced for the same one.)"""
    for digits in (0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4):
        new = ids.new_id(digits)
        if not _code_taken(conn, new):
            conn.execute(insert(table).values(**{id_col: new}, **values))
            return new
    raise RuntimeError("could not allocate a code")


def store_report(*, telemetry: dict, result: dict, session_issued_at: datetime) -> tuple[str, datetime]:
    now = utcnow()
    with engine.begin() as c:
        rid = _insert_with_fresh_id(c, reports, "id", dict(
            created_at=now,
            session_issued_at=session_issued_at,
            agent_version=str(telemetry.get("agent_version") or "")[:32],
            verdict=result["verdict"],
            flag_count=len(result.get("flags") or []),
            subject=(result.get("subject") or "")[:200],
            telemetry=json.dumps(telemetry, separators=(",", ":")),
            result=json.dumps(result, separators=(",", ":")),
        ))
        for comp in result.get("components") or []:
            if comp.get("hardware_id"):
                c.execute(insert(hardware).values(
                    hardware_id=comp["hardware_id"], report_id=rid,
                    kind=comp["kind"], label=comp.get("label"),
                    created_at=now,
                    snapshot=json.dumps(comp.get("snapshot") or {})))
    return rid, now


def get_report(report_id: str) -> dict | None:
    with engine.connect() as c:
        row = c.execute(select(reports).where(reports.c.id == report_id)).first()
    if not row:
        return None
    return {
        "id": row.id,
        "created_at": row.created_at,
        "session_issued_at": row.session_issued_at,
        "verdict": row.verdict,
        "subject": row.subject,
        "telemetry": json.loads(row.telemetry),
        "result": json.loads(row.result),
    }


def history(hardware_id: str, limit: int = 50) -> list[dict]:
    """Every report filed for one physical component, oldest first."""
    with engine.connect() as c:
        rows = c.execute(
            select(hardware.c.report_id, hardware.c.label, hardware.c.created_at,
                   hardware.c.snapshot, reports.c.verdict)
            .join(reports, reports.c.id == hardware.c.report_id)
            .where(hardware.c.hardware_id == hardware_id)
            .order_by(hardware.c.created_at)
            .limit(limit)).all()
    return [{"report_id": r.report_id, "label": r.label, "created_at": r.created_at,
             "verdict": r.verdict, "snapshot": json.loads(r.snapshot or "{}")}
            for r in rows]


# ----------------------------------------------------------------------
# parts (one public history page per physical component)
# ----------------------------------------------------------------------

def part_code(hardware_id: str, kind: str) -> str:
    """The part's public code, created the first time we see it."""
    with engine.connect() as c:
        row = c.execute(select(parts.c.code).where(parts.c.hardware_id == hardware_id)).first()
    if row:
        return row.code
    try:
        with engine.begin() as c:
            return _insert_with_fresh_id(c, parts, "code", dict(
                hardware_id=hardware_id, kind=kind, first_seen=utcnow()))
    except IntegrityError:
        # another upload registered the same part at the same moment
        with engine.connect() as c:
            return c.execute(select(parts.c.code)
                             .where(parts.c.hardware_id == hardware_id)).first().code


def get_part(code: str) -> dict | None:
    with engine.connect() as c:
        row = c.execute(select(parts).where(parts.c.code == code)).first()
    return dict(row._mapping) if row else None


# ----------------------------------------------------------------------
# comparisons
# ----------------------------------------------------------------------

def store_comparison(*, seller_report_id: str, buyer_report_id: str, result: dict) -> str:
    with engine.begin() as c:
        return _insert_with_fresh_id(c, comparisons, "pair_id", dict(
            seller_report_id=seller_report_id,
            buyer_report_id=buyer_report_id,
            verdict=result["verdict"],
            result=json.dumps(result, separators=(",", ":")),
            created_at=utcnow()))


def get_comparison(pair_id: str) -> dict | None:
    with engine.connect() as c:
        row = c.execute(select(comparisons).where(comparisons.c.pair_id == pair_id)).first()
    if not row:
        return None
    return {"pair_id": row.pair_id, "seller_report_id": row.seller_report_id,
            "buyer_report_id": row.buyer_report_id, "verdict": row.verdict,
            "created_at": row.created_at, "result": json.loads(row.result)}


def comparisons_for(*report_ids: str) -> list[dict]:
    """Every comparison that involves any of these reports, oldest first."""
    if not report_ids:
        return []
    with engine.connect() as c:
        rows = c.execute(
            select(comparisons.c.pair_id, comparisons.c.verdict, comparisons.c.created_at,
                   comparisons.c.seller_report_id, comparisons.c.buyer_report_id,
                   comparisons.c.result)
            .where(comparisons.c.seller_report_id.in_(report_ids)
                   | comparisons.c.buyer_report_id.in_(report_ids))
            .order_by(comparisons.c.created_at)).all()
    out = []
    for r in rows:
        d = dict(r._mapping)
        d["mode"] = json.loads(d.pop("result")).get("mode", "arrival")
        out.append(d)
    return out
