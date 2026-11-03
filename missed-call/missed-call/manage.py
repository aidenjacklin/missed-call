"""Admin CLI.

  python manage.py add-client --number +15095550100 --name "Kittitas HVAC" --owner +15095551234
  python manage.py list
  python manage.py deactivate 3
  python manage.py activate 3
  python manage.py stats
  python manage.py weekly-summary            # run every Monday via cron
  python manage.py weekly-summary --dry-run  # preview without sending
"""
import argparse
import logging
import re
import sys

from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException

load_dotenv()

import db   # noqa: E402
import sms  # noqa: E402

E164 = re.compile(r"^\+1\d{10}$")


def e164(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        digits = "1" + digits
    out = "+" + digits
    if not E164.match(out):
        raise argparse.ArgumentTypeError(f"not a US phone number: {value}")
    return out


def summary_text(name: str, caught: int, replied: int) -> str:
    if caught == 0:
        return f"{name} weekly report: no missed calls needed a text-back last week. Nice work picking up!"
    return (f"{name} weekly report: {caught} missed call{'s' if caught != 1 else ''} caught "
            f"and texted, {replied} customer{'s' if replied != 1 else ''} replied.")


def cmd_add(a):
    template = a.text or db.DEFAULT_TEXT
    if "{business}" not in template and a.text:
        print("Note: template has no {business} placeholder; sending it as-is.")
    cid = db.add_client(a.number, a.name, a.owner, template, a.voice or db.DEFAULT_VOICE)
    print(f"Added client #{cid}: {a.name} on {a.number} -> owner {a.owner}")
    print("Preview text:", template.format(business=a.name))


def cmd_list(a):
    for c in db.list_clients(include_inactive=True):
        flag = "active" if c["active"] else "INACTIVE"
        print(f"#{c['id']:<3} {c['business_name']:<30} {c['twilio_number']}  owner {c['owner_cell']}  {flag}")


def cmd_stats(a):
    for c in db.list_clients():
        s = db.weekly_stats(c["id"])
        print(f"{c['business_name']:<30} caught {s['caught']:>3}  replied {s['replied']:>3}")


def cmd_weekly(a):
    failures = 0
    for c in db.list_clients():
        s = db.weekly_stats(c["id"])
        text = summary_text(c["business_name"], s["caught"], s["replied"])
        if a.dry_run:
            print(f"[dry-run] to {c['owner_cell']}: {text}")
            continue
        try:
            sms.send_sms(c["twilio_number"], c["owner_cell"], text)
            print(f"Sent to {c['business_name']}")
        except TwilioRestException as e:
            failures += 1
            print(f"FAILED {c['business_name']}: {e.code} {e.msg}", file=sys.stderr)
    return 1 if failures else 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    p = argparse.ArgumentParser(description="Missed-call text-back admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add-client")
    s.add_argument("--number", required=True, type=e164, help="Twilio number bought for this client")
    s.add_argument("--name", required=True, help="Business name as customers know it")
    s.add_argument("--owner", required=True, type=e164, help="Owner's cell for forwarded replies")
    s.add_argument("--text", help="Custom text; use {business} for the name")
    s.add_argument("--voice", help="Custom spoken message")
    s.set_defaults(fn=cmd_add)

    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)

    for name, active in (("deactivate", False), ("activate", True)):
        s = sub.add_parser(name)
        s.add_argument("client_id", type=int)
        s.set_defaults(fn=lambda a, active=active: (db.set_active(a.client_id, active),
                                                    print(f"Client #{a.client_id} active={active}")))

    s = sub.add_parser("weekly-summary")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_weekly)

    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
