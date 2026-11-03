"""Public Privacy Policy and Terms pages required for A2P 10DLC campaign registration."""
import os
from html import escape

from flask import Blueprint, Response

legal = Blueprint("legal", __name__)


def _brand() -> str:
    return escape(os.environ.get("BRAND_NAME", "Missed Call Text Back Central WA"))


def _contact() -> str:
    return escape(os.environ.get("CONTACT_EMAIL", "aidenjacklin@gmail.com"))


def _page(title: str, body: str) -> Response:
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | {_brand()}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:40px auto;
padding:0 16px;line-height:1.6;color:#1a1a1a;background:#fff}}
h1{{font-size:28px}} h2{{font-size:19px;margin-top:28px}} blockquote{{margin:0;padding:8px 14px;
border-left:3px solid #999;background:#f5f5f5}} footer{{margin-top:40px;font-size:14px;color:#555}}
</style></head><body>
<h1>{title}</h1>
{body}
<footer>{_brand()} &middot; <a href="/privacy">Privacy Policy</a> &middot; <a href="/terms">Terms &amp; Conditions</a></footer>
</body></html>"""
    return Response(html, mimetype="text/html")


VOICE_SCRIPT = ("Thanks for calling. Sorry we missed your call. We will send you one text message "
                "at this number so we can help you. Message and data rates may apply. "
                "Reply STOP to opt out.")


def _number() -> str:
    return escape(os.environ.get("DEMO_NUMBER", "(509) 383-2644"))


@legal.get("/")
def home():
    b, n = _brand(), _number()
    tel = "+1" + "".join(ch for ch in n if ch.isdigit())[-10:]
    return _page(b, f"""
<p>{b} helps local service businesses in Central Washington never lose a customer to a missed call.
When a call to the business goes unanswered, the caller gets one text so the business can follow up.</p>
<h2>Try it: call {n}</h2>
<p style="font-size:24px;margin:8px 0"><a href="tel:{tel}">{n}</a></p>
<p>Call this number and let it go unanswered. You will hear a short message and then receive one text
message from {b} at the number you called from.</p>
<p><strong>SMS disclosure:</strong> By calling {n}, you agree to receive one text message about your call
if it is not answered. Message frequency: one message per missed call. Message and data rates may apply.
Reply STOP to opt out, HELP for help. See our <a href="/privacy">Privacy Policy</a> and
<a href="/terms">Terms &amp; Conditions</a>.</p>
""")


@legal.get("/privacy")
def privacy():
    b, c = _brand(), _contact()
    return _page("Privacy Policy", f"""
<p>This Privacy Policy explains how {b} ("we", "us") collects and uses information through our
missed-call text-back service.</p>
<h2>Information we collect</h2>
<p>When you call a phone number that uses our service and the call is not answered, we collect your
phone number, the time of the call, and the content of any text messages you send in reply.</p>
<h2>How we use it</h2>
<p>We use this information only to send you one text message about your missed call, to forward your
replies to the business you called so they can follow up, and to keep basic call and message records
for that business. We do not send marketing messages.</p>
<h2>How you consent</h2>
<p>Before any text is sent, every caller whose call is not answered hears this automated message:</p>
<blockquote>"{escape(VOICE_SCRIPT)}"</blockquote>
<h2>Sharing</h2>
<p><strong>We do not sell or share your SMS opt-in data or personal information with third parties for
marketing purposes.</strong> Text messaging originator opt-in data and consent will not be shared with
any third parties. Your messages are shared only with the business you called, and with our messaging
provider as needed to deliver them.</p>
<h2>Opting out</h2>
<p>Reply STOP at any time to stop receiving texts. Reply HELP for help.</p>
<h2>Retention and security</h2>
<p>We keep call and message records only as long as needed to provide the service, and we protect them
with reasonable safeguards.</p>
<h2>Contact</h2>
<p>Questions? Email <a href="mailto:{c}">{c}</a>.</p>
""")


@legal.get("/terms")
def terms():
    b, c = _brand(), _contact()
    return _page("Terms &amp; Conditions", f"""
<p>These Terms &amp; Conditions apply to the missed-call text-back service operated by {b}.</p>
<h2>SMS Terms</h2>
<ul>
<li><strong>Program:</strong> {b} missed-call text-back. If you call a business that uses this service
and the call is not answered, you receive one text message so the business can help you. Your replies
are forwarded to that business.</li>
<li><strong>How you opt in:</strong> by calling the business's phone number. Before any text is sent, you
hear: "{escape(VOICE_SCRIPT)}"</li>
<li><strong>Message frequency:</strong> one automated message per missed call (at most one per 30 minutes),
plus replies to messages you send.</li>
<li><strong>Message and data rates may apply.</strong></li>
<li><strong>Opt out:</strong> reply STOP at any time. You will receive one confirmation and no further texts.
Reply START to resubscribe.</li>
<li><strong>Help:</strong> reply HELP or email <a href="mailto:{c}">{c}</a>.</li>
<li>Carriers are not liable for delayed or undelivered messages.</li>
</ul>
<h2>Privacy</h2>
<p>See our <a href="/privacy">Privacy Policy</a>.</p>
<h2>Changes</h2>
<p>We may update these terms. Continued use of the service means you accept the updated terms.</p>
""")
