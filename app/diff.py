from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.edgar import latest_filing_for_period, latest_periods
from app.models import Holding


def holding_key(h: Holding | dict) -> tuple:
    if isinstance(h, dict):
        return ((h.get("cusip") or "").strip(), (h.get("class_title") or "").strip(), (h.get("put_call") or "").strip())
    return ((h.cusip or "").strip(), (h.class_title or "").strip(), (h.put_call or "").strip())


def classify_change(prev_shares: int | None, curr_shares: int | None) -> str:
    p = prev_shares or 0
    c = curr_shares or 0
    if p == 0 and c > 0:
        return "NEW"
    if p > 0 and c == 0:
        return "SOLD"
    if c > p:
        return "ADD"
    if c < p:
        return "TRIM"
    return "UNCHANGED"


def compute_period_diff(db: Session, fund_id: int, period: date) -> dict:
    periods = latest_periods(db, fund_id)
    if period not in periods:
        return {"period": period, "prior_period": None, "rows": []}

    idx = periods.index(period)
    prior_period = periods[idx + 1] if idx + 1 < len(periods) else None

    current_filing = latest_filing_for_period(db, fund_id, period)
    prior_filing = latest_filing_for_period(db, fund_id, prior_period) if prior_period else None

    curr_holdings = db.scalars(select(Holding).where(Holding.filing_id == current_filing.id)).all() if current_filing else []
    prev_holdings = db.scalars(select(Holding).where(Holding.filing_id == prior_filing.id)).all() if prior_filing else []

    curr_map = {holding_key(h): h for h in curr_holdings}
    prev_map = {holding_key(h): h for h in prev_holdings}

    keys = set(curr_map.keys()) | set(prev_map.keys())
    rows = []
    for key in keys:
        c = curr_map.get(key)
        p = prev_map.get(key)
        c_shares = c.shares if c else 0
        p_shares = p.shares if p else 0
        c_val = c.value_usd_000 if c else 0
        p_val = p.value_usd_000 if p else 0
        rows.append(
            {
                "key": key,
                "cusip": key[0],
                "class_title": key[1],
                "put_call": key[2],
                "issuer": (c.issuer if c else p.issuer) if (c or p) else None,
                "shares": c_shares,
                "prev_shares": p_shares,
                "value_usd_000": c_val,
                "prev_value_usd_000": p_val,
                "delta_shares": (c_shares or 0) - (p_shares or 0),
                "delta_value_usd_000": (c_val or 0) - (p_val or 0),
                "status": classify_change(p_shares, c_shares),
            }
        )

    top_movers = sorted(rows, key=lambda r: abs(r["delta_value_usd_000"] or 0), reverse=True)[:20]
    top_new = sorted([r for r in rows if r["status"] == "NEW"], key=lambda r: r["value_usd_000"] or 0, reverse=True)[:10]
    top_sold = sorted([r for r in rows if r["status"] == "SOLD"], key=lambda r: r["prev_value_usd_000"] or 0, reverse=True)[:10]

    rows_sorted = sorted(rows, key=lambda r: abs(r["delta_value_usd_000"] or 0), reverse=True)

    return {
        "period": period,
        "prior_period": prior_period,
        "rows": rows_sorted,
        "top_movers": top_movers,
        "top_new": top_new,
        "top_sold": top_sold,
    }


def summary_counts(rows: list[dict]) -> dict[str, int]:
    counts = Counter(r["status"] for r in rows)
    return {k: counts.get(k, 0) for k in ["NEW", "ADD", "TRIM", "SOLD", "UNCHANGED"]}
