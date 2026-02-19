#!/usr/bin/env python3
import logging

from app.db import Base, engine, session_scope
from app.edgar import ingest_active_funds, preload_funds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    try:
        Base.metadata.create_all(bind=engine)
        with session_scope() as db:
            preload_funds(db)
            result = ingest_active_funds(db)
            print(
                f"Ingestion complete: checked={result.funds_checked} new={result.new_filings} "
                f"parsed={result.parsed_filings} failed={result.failed_filings}"
            )
        return 0
    except Exception:
        logging.exception("Update failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
