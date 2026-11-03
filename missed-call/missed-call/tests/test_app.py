import os
import sys
from datetime import timedelta

import pytest
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_PATH", ":memory:")  # replaced per-test below

import app as app_module  # noqa: E402
import db  # noqa: E402
import manage  # noqa: E402
import sms  # noqa: E402

TW = "+15095550100"     # client's Twilio number
OWNER = "+15095559999"
CALLER = "+15095551234"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("VALIDATE_TWILIO", "0")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    db.init_db()
    cid = db.add_client(TW, "Kittitas HVAC", OWNER)
    sent = []

    def fake_send(frm, to, body, status_callback=None):
        sent.append({"from": frm, "to": to, "body": body})
        return f"SM{len(sent)}"

    monkeypatch.setattr(sms, "send_sms", fake_send)
    return {"client": app_module.app.test_client(), "sent": sent, "cid": cid}


def call(c, caller=CALLER, to=TW):
    return c.post("/voice", data={"To": to, "From": caller, "CallSid": "CA1"})


def text(c, body, sender=CALLER, to=TW):
    return c.post("/sms", data={"To": to, "From": sender, "Body": body})


def test_missed_call_texts_caller_and_hangs_up(env):
    r = call(env["client"])
    xml = r.data.decode()
    assert r.status_code == 200 and "<Say>" in xml and "<Hangup" in xml
    assert len(env["sent"]) == 1
    msg = env["sent"][0]
    assert msg["to"] == CALLER and msg["from"] == TW
    assert "Kittitas HVAC" in msg["body"] and "STOP" in msg["body"]


def test_duplicate_guard(env):
    call(env["client"]); call(env["client"])
    assert len(env["sent"]) == 1


def test_duplicate_window_expires(env, monkeypatch):
    call(env["client"])
    later = db.now() + timedelta(minutes=31)
    monkeypatch.setattr(db, "now", lambda: later)
    call(env["client"])
    assert len(env["sent"]) == 2


@pytest.mark.parametrize("caller", ["+266696687", "anonymous", "", "+447700900123"])
def test_blocked_or_non_us_caller_not_texted(env, caller):
    r = call(env["client"], caller=caller)
    assert r.status_code == 200 and env["sent"] == []


def test_unknown_number(env):
    r = call(env["client"], to="+15090000000")
    assert "not in service" in r.data.decode() and env["sent"] == []


def test_inactive_client(env):
    db.set_active(env["cid"], False)
    call(env["client"])
    assert env["sent"] == []


def test_landline_send_failure_is_logged_not_crashed(env, monkeypatch):
    def boom(*a, **k):
        raise TwilioRestException(400, "uri", msg="not SMS capable", code=21614)
    monkeypatch.setattr(sms, "send_sms", boom)
    r = call(env["client"])
    assert r.status_code == 200
    with db.connect() as c:
        row = c.execute("SELECT texted, skip_reason FROM calls").fetchone()
    assert row["texted"] == 0 and row["skip_reason"] == "send_failed:21614"


def test_reply_forwarded_to_owner(env):
    call(env["client"])
    text(env["client"], "Furnace won't turn on, can someone come today?")
    fwd = env["sent"][-1]
    assert fwd["to"] == OWNER and "(509) 555-1234" in fwd["body"] and "Furnace" in fwd["body"]


def test_stop_then_start(env):
    text(env["client"], "stop")
    assert env["sent"] == []                      # not forwarded, no extra reply
    call(env["client"])
    assert env["sent"] == []                      # opted out -> no text
    text(env["client"], "START")
    call(env["client"])
    assert len(env["sent"]) == 1


def test_owner_texting_line_gets_help_not_loop(env):
    r = text(env["client"], "hello?", sender=OWNER)
    assert "missed-call line" in r.data.decode() and env["sent"] == []


def test_weekly_stats_and_summary(env):
    call(env["client"])
    call(env["client"], caller="+15095552222")
    text(env["client"], "need a quote")
    s = db.weekly_stats(env["cid"])
    assert s == {"caught": 2, "replied": 1}
    assert manage.summary_text("Kittitas HVAC", 2, 1) == \
        "Kittitas HVAC weekly report: 2 missed calls caught and texted, 1 customer replied."
    env["sent"].clear()
    manage.main(["weekly-summary"])
    assert env["sent"][0]["to"] == OWNER and "2 missed calls" in env["sent"][0]["body"]


def test_status_callback_records_failure(env):
    call(env["client"])
    env["client"].post("/sms/status", data={"MessageSid": "SM1", "MessageStatus": "undelivered",
                                            "ErrorCode": "30006"})
    with db.connect() as c:
        row = c.execute("SELECT sms_status, sms_error FROM calls").fetchone()
    assert row["sms_status"] == "undelivered" and row["sms_error"] == "30006"


def test_signature_required(env, monkeypatch):
    monkeypatch.setenv("VALIDATE_TWILIO", "1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.up.railway.app")
    data = {"To": TW, "From": CALLER, "CallSid": "CA1"}
    assert env["client"].post("/voice", data=data).status_code == 403
    sig = RequestValidator("secret").compute_signature("https://example.up.railway.app/voice", data)
    r = env["client"].post("/voice", data=data, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200 and len(env["sent"]) == 1
