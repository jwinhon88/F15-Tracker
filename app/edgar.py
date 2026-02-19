import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Filing, Fund, Holding
from app.notify import send_telegram

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
FORMS = {"13F-HR", "13F-HR/A"}


@dataclass
class IngestionResult:
    funds_checked: int = 0
    new_filings: int = 0
    parsed_filings: int = 0
    failed_filings: int = 0


def _require_user_agent() -> str:
    ua = os.getenv("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("SEC_USER_AGENT is required for SEC requests")
    return ua


def _client() -> httpx.Client:
    ua = _require_user_agent()
    return httpx.Client(headers={"User-Agent": ua, "Accept": "application/json,text/html,application/xml"}, timeout=30)


def _request_with_retry(client: httpx.Client, url: str) -> httpx.Response:
    delay = 0.5
    for attempt in range(5):
        try:
            resp = client.get(url)
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            resp.raise_for_status()
            time.sleep(random.uniform(0.2, 0.5))
            return resp
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            if attempt == 4:
                raise
            logger.warning("SEC request failed (%s), retrying in %.1fs: %s", exc.__class__.__name__, delay, url)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def normalize_cik(cik: str) -> str:
    digits = re.sub(r"\D", "", cik or "")
    if not digits:
        raise ValueError("CIK must contain digits")
    return digits.zfill(10)


def parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_filed_datetime(s: str) -> datetime:
    dt = datetime.strptime(s, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def fetch_submissions(client: httpx.Client, cik: str) -> dict[str, Any]:
    url = f"{SEC_BASE}/submissions/CIK{cik}.json"
    return _request_with_retry(client, url).json()


def _iter_recent_13f(submissions: dict[str, Any]) -> list[dict[str, str | None]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    rows: list[dict[str, str | None]] = []
    for i, form in enumerate(forms):
        if form not in FORMS:
            continue
        rows.append(
            {
                "form": form,
                "accession": accessions[i],
                "filing_date": filing_dates[i],
                "report_date": report_dates[i] if i < len(report_dates) else None,
                "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
            }
        )
    return rows


def accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


def filing_index_url(cik: str, accession: str) -> str:
    cik_no_zero = str(int(cik))
    accession_clean = accession_no_dashes(accession)
    return f"{ARCHIVES_BASE}/{cik_no_zero}/{accession_clean}/index.json"


def find_information_table_file(client: httpx.Client, cik: str, accession: str) -> str | None:
    idx_url = filing_index_url(cik, accession)
    resp = _request_with_retry(client, idx_url)
    data = resp.json()
    items = data.get("directory", {}).get("item", [])

    preferred = None
    for item in items:
        name = item.get("name", "")
        lower = name.lower()
        if lower.endswith(".xml") and ("informationtable" in lower or "infotable" in lower):
            preferred = name
            break
    if not preferred:
        for item in items:
            name = item.get("name", "")
            lower = name.lower()
            if lower.endswith(".xml"):
                preferred = name
                break
    if preferred:
        base = idx_url.rsplit("/", 1)[0] + "/"
        return urljoin(base, preferred)

    for item in items:
        name = item.get("name", "")
        lower = name.lower()
        if lower.endswith((".txt", ".html", ".htm")) and ("informationtable" in lower or "infotable" in lower):
            base = idx_url.rsplit("/", 1)[0] + "/"
            return urljoin(base, name)
    return None


def _text(node: ET.Element | None, path: str) -> str | None:
    if node is None:
        return None
    # handles namespaces by checking local-name
    for child in node.iter():
        if child.tag.split("}")[-1] == path:
            return (child.text or "").strip() or None
    return None


def _to_int(v: str | None) -> int | None:
    if not v:
        return None
    cleaned = re.sub(r"[^0-9-]", "", v)
    if cleaned in {"", "-"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_information_table_xml(content: str) -> list[dict[str, Any]]:
    root = ET.fromstring(content)
    holdings: list[dict[str, Any]] = []

    for info in [e for e in root.iter() if e.tag.split("}")[-1] == "infoTable"]:
        voting = next((e for e in info if e.tag.split("}")[-1] == "votingAuthority"), None)
        ssh = next((e for e in info if e.tag.split("}")[-1] == "shrsOrPrnAmt"), None)
        row = {
            "issuer": _text(info, "nameOfIssuer"),
            "class_title": _text(info, "titleOfClass"),
            "cusip": _text(info, "cusip"),
            "value_usd_000": _to_int(_text(info, "value")),
            "shares": _to_int(_text(ssh, "sshPrnamt")),
            "shares_type": _text(ssh, "sshPrnamtType"),
            "put_call": _text(info, "putCall"),
            "discretion": _text(info, "investmentDiscretion"),
            "voting_sole": _to_int(_text(voting, "Sole")),
            "voting_shared": _to_int(_text(voting, "Shared")),
            "voting_none": _to_int(_text(voting, "None")),
        }
        holdings.append(row)

    return holdings


def parse_information_table_text(content: str) -> list[dict[str, Any]]:
    rows = []
    for line in content.splitlines():
        if "<S>" in line or not line.strip():
            continue
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) < 5:
            continue
        rows.append(
            {
                "issuer": cols[0],
                "class_title": cols[1] if len(cols) > 1 else None,
                "cusip": cols[2] if len(cols) > 2 else None,
                "value_usd_000": _to_int(cols[3] if len(cols) > 3 else None),
                "shares": _to_int(cols[4] if len(cols) > 4 else None),
                "shares_type": None,
                "put_call": None,
                "discretion": None,
                "voting_sole": None,
                "voting_shared": None,
                "voting_none": None,
            }
        )
    return rows


def latest_filing_for_period(db: Session, fund_id: int, period: date) -> Filing | None:
    stmt: Select[Filing] = (
        select(Filing)
        .where(Filing.fund_id == fund_id, Filing.report_period == period)
        .order_by(Filing.filed_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def latest_periods(db: Session, fund_id: int) -> list[date]:
    stmt = (
        select(Filing.report_period)
        .where(Filing.fund_id == fund_id, Filing.report_period.is_not(None))
        .group_by(Filing.report_period)
        .order_by(Filing.report_period.desc())
    )
    return [r for r in db.scalars(stmt).all() if r is not None]


def ingest_fund(db: Session, client: httpx.Client, fund: Fund) -> IngestionResult:
    result = IngestionResult(funds_checked=1)
    submissions = fetch_submissions(client, fund.cik)
    rows = _iter_recent_13f(submissions)

    for row in rows:
        accession = row["accession"]
        if not accession:
            continue
        exists = db.scalar(select(Filing.id).where(Filing.fund_id == fund.id, Filing.accession == accession))
        if exists:
            continue

        report_period = parse_iso_date(row.get("report_date"))
        filed_at = parse_filed_datetime(row["filing_date"])
        source_url = filing_index_url(fund.cik, accession)
        filing = Filing(
            fund_id=fund.id,
            accession=accession,
            form_type=row["form"] or "13F-HR",
            filed_at=filed_at,
            report_period=report_period,
            is_amendment=(row["form"] or "").endswith("/A"),
            source_url=source_url,
            holdings_parse_status="pending",
        )
        db.add(filing)
        db.flush()
        result.new_filings += 1

        holdings_url = None
        holdings = []
        try:
            holdings_url = find_information_table_file(client, fund.cik, accession)
            if holdings_url:
                raw = _request_with_retry(client, holdings_url).text
                if holdings_url.lower().endswith(".xml"):
                    holdings = parse_information_table_xml(raw)
                else:
                    holdings = parse_information_table_text(raw)
        except Exception:
            logger.exception("Failed parsing holdings for %s %s", fund.name, accession)

        if holdings:
            for h in holdings:
                db.add(Holding(filing_id=filing.id, **h))
            filing.holdings_parse_status = "parsed"
            result.parsed_filings += 1
        else:
            filing.holdings_parse_status = "failed"
            result.failed_filings += 1

        send_telegram(
            f"📄 New 13F filing\nFund: {fund.name}\nForm: {filing.form_type}\nReport period: {filing.report_period}\nFiled: {filing.filed_at.date()}\nURL: {filing.source_url}"
        )

        from app.diff import compute_period_diff, summary_counts

        periods = latest_periods(db, fund.id)
        if filing.report_period and len(periods) > 1:
            diff = compute_period_diff(db, fund.id, filing.report_period)
            counts = summary_counts(diff["rows"])
            new_top = [r for r in diff["rows"] if r["status"] == "NEW"][:5]
            sold_top = [r for r in diff["rows"] if r["status"] == "SOLD"][:5]
            details = [
                f"NEW: {counts['NEW']} ADD: {counts['ADD']} TRIM: {counts['TRIM']} SOLD: {counts['SOLD']}",
                "Top NEW:",
            ]
            details.extend([f"- {r['issuer']} ({r['value_usd_000'] or 0})" for r in new_top] or ["- none"])
            details.append("Top SOLD:")
            details.extend([f"- {r['issuer']} ({r['prev_value_usd_000'] or 0})" for r in sold_top] or ["- none"])
            send_telegram("\n".join([f"📊 QoQ changes for {fund.name} ({filing.report_period})"] + details))

    return result


def ingest_active_funds(db: Session) -> IngestionResult:
    final = IngestionResult()
    funds = db.scalars(select(Fund).where(Fund.active.is_(True)).order_by(Fund.name)).all()
    with _client() as client:
        for fund in funds:
            fund_result = ingest_fund(db, client, fund)
            final.funds_checked += fund_result.funds_checked
            final.new_filings += fund_result.new_filings
            final.parsed_filings += fund_result.parsed_filings
            final.failed_filings += fund_result.failed_filings
            db.commit()
    return final


def preload_funds(db: Session) -> None:
    defaults = [
        ("Berkshire Hathaway Inc", "0001067983"),
        ("Bridgewater Associates, LP", "0001350694"),
        ("Duquesne Family Office LLC", "0001536411"),
        ("Coatue Management LLC", "0001135730"),
        ("Point72 Asset Management, L.P.", "0001603466"),
        ("SCGE Management, L.P.", "0001537530"),
    ]
    for name, cik in defaults:
        norm = normalize_cik(cik)
        existing = db.scalar(select(Fund).where(Fund.cik == norm))
        if not existing:
            db.add(Fund(name=name, cik=norm, active=True))
    db.commit()
