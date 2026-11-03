"""Missed-call text-back: Flask webhooks for Twilio.

Flow: client's business line forwards unanswered/busy calls to a Twilio number we own
for them -> Twilio POSTs /voice -> we play a short message, hang up, and text the caller.
Customer replies hit /sms and are forwarded to the owner's cell.
"""
import logging
import os
import re
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, Response, abort, request
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse

import db
import sms

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("missedcall")

app = Flask(__name__)

DUPLICATE_WINDOW_MIN = int(os.environ.get("DUPLICATE_WINDOW_MIN", "30"))
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "OPTOUT", "REVOKE"}
START_WORDS = {"START", "YES", "UNSTOP"}
US_NUMBER = re.compile(r"^\+1\d{10}$")


def twiml(resp) -> Response:
    return Response(str(resp), mimetype="text/xml")


def public_url() -> str:
    """The URL Twilio actually called (needed for signature checks behind a proxy)."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        return request.url
    qs = request.query_string.decode()
    return f"{base}{request.path}" + (f"?{qs}" if qs else "")


def twilio_only(f):
    """Reject requests that aren't signed by Twilio. Set VALIDATE_TWILIO=0 only for local testing."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if os.environ.get("VALIDATE_TWILIO", "1") != "0":
            validator = RequestValidator(os.environ.get("TWILIO_AUTH_TOKEN", ""))
            sig = request.headers.get("X-Twilio-Signature", "")
            if not validator.validate(public_url(), request.form, sig):
                log.warning("Rejected unsigned request to %s", request.path)
                abort(403)
        return f(*args, **kwargs)
    return wrapper


def pretty(phone: str) -> str:
    """+15095551234 -> (509) 555-1234"""
    if US_NUMBER.match(phone):
        d = phone[2:]
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return phone


def status_callback_url():
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/sms/status" if base else None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/voice")
@twilio_only
def voice():
    to_number = request.form.get("To", "")
    caller = request.form.get("From", "")
    call_sid = request.form.get("CallSid")

    client = db.get_client_by_number(to_number)
    resp = VoiceResponse()
    if client is None:
        log.warning("Call to unknown/inactive number %s", to_number)
        resp.say("Sorry, this number is not in service.")
        resp.hangup()
        return twiml(resp)

    resp.say(client["voice_message"])
    resp.hangup()

    # Decide whether to text.
    skip = None
    if not US_NUMBER.match(caller):
        skip = "blocked_caller_id"          # anonymous/restricted/unknown or non-US
    elif db.is_opted_out(client["id"], caller):
        skip = "opted_out"
    elif db.recently_texted(client["id"], caller, DUPLICATE_WINDOW_MIN):
        skip = "duplicate"

    if skip:
        db.log_call(client["id"], caller, call_sid, texted=False, skip_reason=skip)
        log.info("Call %s -> %s not texted (%s)", caller, client["business_name"], skip)
        return twiml(resp)

    body = client["text_template"].format(business=client["business_name"])
    try:
        sid = sms.send_sms(client["twilio_number"], caller, body, status_callback_url())
        db.log_call(client["id"], caller, call_sid, texted=True, message_sid=sid)
        log.info("Texted %s for %s", caller, client["business_name"])
    except TwilioRestException as e:
        # e.g. 21614 (landline / not SMS-capable), 21610 (carrier-level opt-out)
        db.log_call(client["id"], caller, call_sid, texted=False, skip_reason=f"send_failed:{e.code}")
        log.warning("Text to %s failed: %s %s", caller, e.code, e.msg)
    return twiml(resp)


@app.post("/sms")
@twilio_only
def inbound_sms():
    to_number = request.form.get("To", "")
    sender = request.form.get("From", "")
    body = (request.form.get("Body") or "").strip()
    resp = MessagingResponse()

    client = db.get_client_by_number(to_number)
    if client is None:
        return twiml(resp)

    keyword = body.upper()

    # Owner texting their own system number: send a short help note, don't loop.
    if sender == client["owner_cell"]:
        resp.message("This is your missed-call line. Customer replies are forwarded to you here. "
                     "Call or text customers back from your own phone.")
        return twiml(resp)

    # Opt-out / opt-in. Twilio also auto-replies to these, so we stay silent.
    if keyword in STOP_WORDS:
        db.opt_out(client["id"], sender)
        db.log_message(client["id"], sender, body, forwarded=False)
        return twiml(resp)
    if keyword in START_WORDS:
        db.opt_in(client["id"], sender)
        db.log_message(client["id"], sender, body, forwarded=False)
        return twiml(resp)

    forward = f"New text from {pretty(sender)} (missed call):\n\"{body}\"\nCall or text them back directly."
    try:
        sms.send_sms(client["twilio_number"], client["owner_cell"], forward)
        db.log_message(client["id"], sender, body, forwarded=True)
    except TwilioRestException as e:
        db.log_message(client["id"], sender, body, forwarded=False)
        log.error("Forward to owner failed for %s: %s %s", client["business_name"], e.code, e.msg)
    return twiml(resp)


@app.post("/sms/status")
@twilio_only
def sms_status():
    """Twilio delivery callbacks: catches landlines/undeliverable numbers after send."""
    db.update_sms_status(
        request.form.get("MessageSid", ""),
        request.form.get("MessageStatus", ""),
        request.form.get("ErrorCode"),
    )
    return ("", 204)


db.init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
