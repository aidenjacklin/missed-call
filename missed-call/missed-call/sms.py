"""Thin wrapper around Twilio's REST client so the app (and tests) can swap it out."""
import logging
import os

log = logging.getLogger(__name__)

_client = None


def get_client():
    """Real Twilio client, or None in DRY_RUN mode (prints instead of sending)."""
    global _client
    if os.environ.get("DRY_RUN") == "1":
        return None
    if _client is None:
        from twilio.rest import Client
        _client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    return _client


def send_sms(from_number: str, to_number: str, body: str, status_callback: str | None = None) -> str:
    """Send one text. Returns the message SID. Raises on Twilio errors."""
    client = get_client()
    if client is None:
        log.info("[DRY_RUN] %s -> %s: %s", from_number, to_number, body)
        return "DRYRUN"
    kwargs = {"from_": from_number, "to": to_number, "body": body}
    if status_callback:
        kwargs["status_callback"] = status_callback
    msg = client.messages.create(**kwargs)
    return msg.sid
