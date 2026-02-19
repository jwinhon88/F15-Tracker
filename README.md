# 13F Tracker

Production-oriented MVP for monitoring SEC EDGAR 13F-HR / 13F-HR/A filings, storing holdings, computing QoQ changes, and sending Telegram alerts.

## Stack
- Python 3.11
- FastAPI + Jinja2 (server-rendered mobile-friendly UI)
- SQLAlchemy ORM
- SQLite default, PostgreSQL via `DATABASE_URL`
- httpx + BeautifulSoup4

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SEC_USER_AGENT="Your Name your-email@example.com"
export ADMIN_USER="admin"
export ADMIN_PASS="change-this"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:
- `/` dashboard
- `/admin/funds` (HTTP Basic auth)

## Environment variables
Required:
- `SEC_USER_AGENT`

Optional:
- `DATABASE_URL` (default `sqlite:///./tracker.db`)
- `ADMIN_USER` (default `admin`)
- `ADMIN_PASS` (default `changeme`)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

If Telegram vars are missing, alerts are skipped with warning logs.

## Scheduled ingestion job
Run once:
```bash
python scripts/update.py
```

Cron examples:
```cron
*/30 * * * * cd /app && /usr/bin/python scripts/update.py >> /var/log/13f_update.log 2>&1
0 */6 * * * cd /app && /usr/bin/python scripts/update.py >> /var/log/13f_update.log 2>&1
```

## SEC behavior
- Uses `SEC_USER_AGENT` on all SEC requests.
- Adds randomized delay `0.2s - 0.5s` between SEC requests.
- Retries transient failures (429/5xx) with exponential backoff.

## Data model
- `funds(id, name, cik, active, created_at)`
- `filings(id, fund_id, accession, form_type, filed_at, report_period, is_amendment, source_url, holdings_parse_status, created_at)`
  - unique `(fund_id, accession)`
- `holdings(id, filing_id, cusip, issuer, class_title, value_usd_000, shares, shares_type, put_call, discretion, voting_sole, voting_shared, voting_none)`

QoQ comparisons always use the latest filing for each report period.

## Deployment
### Render
- Use included `render.yaml`.
- Set secrets: `SEC_USER_AGENT`, `ADMIN_USER`, `ADMIN_PASS`, optional telegram vars.

### Railway
- Start command:
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
- Add a scheduled service/cron command:
```bash
python scripts/update.py
```
- Configure same environment variables.

## Tests
```bash
pytest
```
