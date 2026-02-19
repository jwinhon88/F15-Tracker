# Railway deployment notes

1. Create a new Railway project from this repo.
2. Set start command:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Add environment variables:
   - `SEC_USER_AGENT` (required)
   - `ADMIN_USER`, `ADMIN_PASS`
   - optional: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
4. Add a scheduled job (Cron) command:
   `python scripts/update.py`
5. Suggested schedule: every 30 minutes.
