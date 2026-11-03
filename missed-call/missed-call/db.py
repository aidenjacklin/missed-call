"""SQLite storage: clients, calls, inbound messages, opt-outs."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    twilio_number TEXT UNIQUE NOT NULL,   -- E.164, e.g. +15095550100
    business_name TEXT NOT NULL,
    owner_cell    TEXT NOT NULL,
    text_template TEXT NOT NULL,
    voice_message TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER NOT NULL REFERENCES clients(id),
    caller      TEXT NOT NULL,
    call_sid    TEXT,
    texted      INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT,            -- duplicate / blocked_caller_id / opted_out / send_failed
    message_sid TEXT,
    sms_status  TEXT,            -- updated by Twilio status callback
    sms_error   TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER NOT NULL REFERENCES clients(id),
    sender     TEXT NOT NULL,
    body       TEXT NOT NULL,
    forwarded  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opt_outs (
    client_id  INTEGER NOT NULL REFERENCES clients(id),
    phone      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (client_id, phone)
);
CREATE INDEX IF NOT EXISTS idx_calls_lookup ON calls(client_id, caller, created_at);
CREATE INDEX IF NOT EXISTS idx_msgs_lookup ON messages(client_id, created_at);
"""

DEFAULT_TEXT = (
    "Hi, this is {business}. Sorry we missed your call! What can we help you with? "
    "Msg & data rates may apply. Reply STOP to opt out, HELP for help."
)
DEFAULT_VOICE = (
    "Thanks for calling {business}. Sorry we missed your call. We will send you one text message "
    "at this number so we can help you. Message and data rates may apply. Reply STOP to opt out."
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def db_path() -> str:
    return os.environ.get("DATABASE_PATH", "missedcall.db")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


# ---------- clients ----------

def add_client(twilio_number, business_name, owner_cell,
               text_template=DEFAULT_TEXT, voice_message=DEFAULT_VOICE) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO clients (twilio_number, business_name, owner_cell, "
            "text_template, voice_message, active, created_at) VALUES (?,?,?,?,?,1,?)",
            (twilio_number, business_name, owner_cell, text_template, voice_message, iso(now())),
        )
        return cur.lastrowid


def get_client_by_number(twilio_number):
    with connect() as c:
        return c.execute(
            "SELECT * FROM clients WHERE twilio_number = ? AND active = 1", (twilio_number,)
        ).fetchone()


def list_clients(include_inactive=False):
    q = "SELECT * FROM clients" + ("" if include_inactive else " WHERE active = 1")
    with connect() as c:
        return c.execute(q + " ORDER BY id").fetchall()


def set_active(client_id: int, active: bool) -> None:
    with connect() as c:
        c.execute("UPDATE clients SET active = ? WHERE id = ?", (int(active), client_id))


# ---------- calls ----------

def recently_texted(client_id, caller, minutes=30) -> bool:
    since = iso(now() - timedelta(minutes=minutes))
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM calls WHERE client_id=? AND caller=? AND texted=1 AND created_at>=? LIMIT 1",
            (client_id, caller, since),
        ).fetchone()
    return row is not None


def log_call(client_id, caller, call_sid, texted, skip_reason=None, message_sid=None) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO calls (client_id, caller, call_sid, texted, skip_reason, message_sid, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (client_id, caller, call_sid, int(texted), skip_reason, message_sid, iso(now())),
        )
        return cur.lastrowid


def update_sms_status(message_sid, status, error_code=None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE calls SET sms_status=?, sms_error=? WHERE message_sid=?",
            (status, error_code, message_sid),
        )


# ---------- messages / opt-outs ----------

def log_message(client_id, sender, body, forwarded) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO messages (client_id, sender, body, forwarded, created_at) VALUES (?,?,?,?,?)",
            (client_id, sender, body, int(forwarded), iso(now())),
        )


def is_opted_out(client_id, phone) -> bool:
    with connect() as c:
        return c.execute(
            "SELECT 1 FROM opt_outs WHERE client_id=? AND phone=?", (client_id, phone)
        ).fetchone() is not None


def opt_out(client_id, phone) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO opt_outs (client_id, phone, created_at) VALUES (?,?,?)",
            (client_id, phone, iso(now())),
        )


def opt_in(client_id, phone) -> None:
    with connect() as c:
        c.execute("DELETE FROM opt_outs WHERE client_id=? AND phone=?", (client_id, phone))


# ---------- reporting ----------

def weekly_stats(client_id, days=7) -> dict:
    since = iso(now() - timedelta(days=days))
    with connect() as c:
        caught = c.execute(
            "SELECT COUNT(*) FROM calls WHERE client_id=? AND texted=1 AND created_at>=?",
            (client_id, since),
        ).fetchone()[0]
        replied = c.execute(
            "SELECT COUNT(DISTINCT sender) FROM messages WHERE client_id=? AND forwarded=1 AND created_at>=?",
            (client_id, since),
        ).fetchone()[0]
    return {"caught": caught, "replied": replied}
