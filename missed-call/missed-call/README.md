# Missed-Call Text-Back

When a client misses a call, the caller gets a text within seconds. Replies forward to the owner's cell. Owners get a weekly report every Monday.

## How it works

```
Customer calls business line ──(no answer / busy)──> conditional forward
   └─> client's Twilio number ──POST /voice──> app
          app: plays "Sorry we missed you...", hangs up, texts the caller
Customer replies ──POST /sms──> app ──> forwards to owner's cell
Twilio delivery status ──POST /sms/status──> app (logs landlines/undelivered)
Cron, Mondays ──> python manage.py weekly-summary ──> texts each owner
```

Built in: duplicate guard (30 min), blocked/anonymous caller skip, STOP/START handling, landline failures logged instead of crashing, Twilio signature verification on every webhook.

## Files

| File | What it does |
| --- | --- |
| `app.py` | Webhooks: `/voice`, `/sms`, `/sms/status`, `/health` |
| `db.py` | SQLite tables: clients, calls, messages, opt_outs |
| `sms.py` | Twilio send wrapper (`DRY_RUN=1` logs instead of sending) |
| `manage.py` | Admin CLI: add/list/activate/deactivate clients, stats, weekly summary |
| `tests/` | 16 tests covering every case above |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in Twilio keys
pytest -q                     # should show 16 passed
python app.py                 # http://localhost:5000/health
```

To hit it from a real phone while developing, expose it with `ngrok http 5000`, set `PUBLIC_BASE_URL` to the ngrok URL, and point your demo number's webhooks there.

## Deploy (Railway)

1. Push this folder to a private GitHub repo.
2. Railway → New Project → Deploy from GitHub repo. It picks up the `Procfile`.
3. Add a **Volume** mounted at `/data`. Without it, SQLite is wiped on every deploy.
4. Set variables: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `PUBLIC_BASE_URL` (Railway's public domain), `DATABASE_PATH=/data/missedcall.db`.
5. Add a cron service with the same repo and volume: schedule `0 16 * * 1` (UTC = Monday 9am Pacific in PDT; 8am in PST), command `python manage.py weekly-summary`.
6. Visit `<your URL>/health` → `{"ok": true}`.

Run admin commands with `railway run python manage.py list` (or Railway's shell).

## Onboarding runbook: new client in under 30 minutes

**Collect on the sales call:** legal business name, EIN, business address, website, owner's cell, business phone carrier (AT&T, Verizon, T-Mobile, Comcast, etc.), and any custom wording for the text.

1. **Buy a number (2 min).** Twilio console → Phone Numbers → Buy → area code 509, SMS + Voice capable.
2. **Register for A2P 10DLC (10 min, then wait).** Twilio → Messaging → Regulatory Compliance. Create the client's brand (low-volume standard), then a campaign with use case "Customer Care". Use sample message: "Hi, this is {Business}. Sorry we missed your call! What can we help you with? Reply STOP to opt out." Opt-in description: "Customers call the business; the business texts back only callers it missed." Add the number to the campaign. Approval can take up to ~2 weeks. Texts to customers will not deliver until approved.
3. **Point the number at the app (2 min).** On the number's config page:
   - A call comes in → Webhook → `https://<your-app>/voice` (HTTP POST)
   - A message comes in → Webhook → `https://<your-app>/sms` (HTTP POST)
4. **Add the client (1 min).**
   ```bash
   python manage.py add-client --number +15095550100 --name "Kittitas Valley Heating" --owner +15095551234
   ```
   Optional: `--text "Hi from {business}! ..."` and `--voice "..."`. Check the preview it prints.
5. **Set conditional forwarding with the owner (10 min, on the phone together).** Forward on *no answer* and *busy* (not all calls) to the Twilio number. Codes vary by carrier and plan. On most wireless carriers it's `*71` + number (AT&T/Verizon) or `**61*1509...#` / `**67*1509...#` (T-Mobile/GSM). VoIP lines (RingCentral, Comcast Business, etc.) set it in the web portal. Look up the exact steps for their carrier before the call. Set ring time to about 20–25 seconds so the owner still gets a chance to pick up.
6. **Test together (5 min).** Once 10DLC is approved: call the business line from your phone, don't answer, confirm the text arrives, reply, and confirm the owner gets the forward. Check `python manage.py stats`.
7. **Follow up.** Text the owner a week later. Ask for a testimonial after their first Monday report.

**Pausing or cancelling a client:** `python manage.py deactivate <id>`, and have the owner turn off forwarding. Release the Twilio number after they cancel.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Webhook returns 403 | `PUBLIC_BASE_URL` doesn't exactly match the URL in Twilio, or wrong auth token |
| Text never arrives, status `undelivered` 30034 | Number isn't on an approved 10DLC campaign yet |
| `send_failed:21614` in calls table | Caller is a landline; expected |
| `send_failed:21610` | Caller replied STOP at the carrier level before |
| Calls ring the owner forever, never forward | Forwarding set to "unreachable" only, or ring time too long |
