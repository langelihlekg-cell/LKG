"""
SQLite-backed persistence for the dev/reference server. Same entities as
migrations/001_init.sql (orgs, api_keys, jobs, qc_reports, batches) — this
is a same-contract stand-in for local/sandbox use, not a production
datastore. Swap for the real Postgres models (api/models.py) when you have
network access to actually install psycopg2/sqlalchemy and run Postgres.
"""
import sqlite3
import json
import uuid
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "devserver.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    webhook_secret TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    job_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    batch_id TEXT,
    kind TEXT NOT NULL DEFAULT 'generate',
    release_id TEXT,
    artist_id TEXT,
    cover_art_url TEXT,
    tier TEXT,
    duration_seconds REAL,
    style_preset TEXT,
    callback_url TEXT,
    metadata TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    price_usd REAL,
    square_asset_url TEXT,
    vertical_asset_url TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS qc_reports (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    checks TEXT NOT NULL,
    apple_ready INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(fresh: bool = False):
    if fresh and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        for ext in ("-wal", "-shm"):
            p = DB_PATH + ext
            if os.path.exists(p):
                os.remove(p)
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now() -> str:
    return datetime.datetime.utcnow().isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def create_org(name: str) -> dict:
    conn = get_conn()
    org_id = new_id()
    secret = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO orgs (id, name, webhook_secret, created_at) VALUES (?, ?, ?, ?)",
        (org_id, name, secret, now()),
    )
    conn.commit()
    conn.close()
    return {"id": org_id, "name": name, "webhook_secret": secret}


def create_api_key(org_id: str, key_hash: str, label: str = "dev") -> str:
    conn = get_conn()
    key_id = new_id()
    conn.execute(
        "INSERT INTO api_keys (id, org_id, key_hash, label, created_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, org_id, key_hash, label, now()),
    )
    conn.commit()
    conn.close()
    return key_id


def get_org_by_key_hash(key_hash: str):
    conn = get_conn()
    row = conn.execute(
        """SELECT orgs.* FROM orgs JOIN api_keys ON api_keys.org_id = orgs.id
           WHERE api_keys.key_hash = ? AND api_keys.revoked_at IS NULL""",
        (key_hash,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_job(**fields) -> str:
    job_id = new_id()
    ts = now()
    conn = get_conn()
    conn.execute(
        """INSERT INTO jobs (id, org_id, batch_id, kind, release_id, artist_id,
           cover_art_url, tier, duration_seconds, style_preset, callback_url,
           metadata, status, price_usd, square_asset_url, vertical_asset_url,
           created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, fields.get("org_id"), fields.get("batch_id"), fields.get("kind", "generate"),
            fields.get("release_id"), fields.get("artist_id"), fields.get("cover_art_url"),
            fields.get("tier"), fields.get("duration_seconds"), fields.get("style_preset"),
            fields.get("callback_url"), json.dumps(fields.get("metadata") or {}),
            fields.get("status", "queued"), fields.get("price_usd"),
            fields.get("square_asset_url"), fields.get("vertical_asset_url"), ts, ts,
        ),
    )
    conn.commit()
    conn.close()
    return job_id


def update_job(job_id: str, **fields):
    if not fields:
        return
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    conn = get_conn()
    conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_job(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_qc_report(job_id: str, passed: bool, checks: dict, apple_ready: bool):
    conn = get_conn()
    conn.execute(
        "INSERT INTO qc_reports (id, job_id, passed, checks, apple_ready, created_at) VALUES (?,?,?,?,?,?)",
        (new_id(), job_id, int(passed), json.dumps(checks), int(apple_ready), now()),
    )
    conn.commit()
    conn.close()


def get_latest_qc_report(job_id: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM qc_reports WHERE job_id = ? ORDER BY created_at DESC LIMIT 1", (job_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["checks"] = json.loads(d["checks"])
    d["passed"] = bool(d["passed"])
    d["apple_ready"] = bool(d["apple_ready"])
    return d


def create_batch(org_id: str, job_count: int) -> str:
    batch_id = new_id()
    conn = get_conn()
    conn.execute(
        "INSERT INTO batches (id, org_id, job_count, created_at) VALUES (?,?,?,?)",
        (batch_id, org_id, job_count, now()),
    )
    conn.commit()
    conn.close()
    return batch_id
