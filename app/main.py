import logging
from datetime import date

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine, get_db
from app.diff import compute_period_diff, summary_counts
from app.edgar import ingest_active_funds, latest_filing_for_period, latest_periods, normalize_cik, preload_funds
from app.models import Filing, Fund, Holding
from app.security import require_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="13F Tracker")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        preload_funds(db)
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    funds = db.scalars(select(Fund).where(Fund.active.is_(True)).order_by(Fund.name)).all()
    cards = []
    for fund in funds:
        latest = db.scalar(
            select(Filing)
            .where(Filing.fund_id == fund.id)
            .order_by(Filing.filed_at.desc())
            .limit(1)
        )
        cards.append(
            {
                "fund": fund,
                "latest_filed_at": latest.filed_at.date() if latest else None,
                "latest_report_period": latest.report_period if latest else None,
            }
        )
    return templates.TemplateResponse("dashboard.html", {"request": request, "cards": cards})


def _fund_period_page(request: Request, db: Session, fund_id: int, period: date | None) -> HTMLResponse:
    fund = db.get(Fund, fund_id)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    periods = latest_periods(db, fund_id)
    selected_period = period or (periods[0] if periods else None)

    diff_data = None
    counts = {}
    top_holdings = []
    selected_filing = latest_filing_for_period(db, fund_id, selected_period) if selected_period else None
    if selected_period and selected_filing:
        diff_data = compute_period_diff(db, fund_id, selected_period)
        counts = summary_counts(diff_data["rows"])
        top_holdings = db.scalars(
            select(Holding)
            .where(Holding.filing_id == selected_filing.id)
            .order_by(Holding.value_usd_000.desc().nullslast())
            .limit(20)
        ).all()

    return templates.TemplateResponse(
        "fund.html",
        {
            "request": request,
            "fund": fund,
            "periods": periods,
            "selected_period": selected_period,
            "filing": selected_filing,
            "top_holdings": top_holdings,
            "diff": diff_data,
            "counts": counts,
        },
    )


@app.get("/funds/{fund_id}", response_class=HTMLResponse)
def fund_page(request: Request, fund_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    return _fund_period_page(request, db, fund_id, None)


@app.get("/funds/{fund_id}/period/{period}", response_class=HTMLResponse)
def fund_period_page(request: Request, fund_id: int, period: str, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        parsed = date.fromisoformat(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid period") from exc
    return _fund_period_page(request, db, fund_id, parsed)


@app.get("/admin/funds", response_class=HTMLResponse)
def admin_funds(request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> HTMLResponse:
    funds = db.scalars(select(Fund).order_by(Fund.created_at.desc())).all()
    return templates.TemplateResponse("admin_funds.html", {"request": request, "funds": funds})


@app.post("/admin/funds")
def add_fund(
    name: str = Form(...),
    cik: str = Form(...),
    active: bool = Form(default=True),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    norm = normalize_cik(cik)
    exists = db.scalar(select(Fund).where(Fund.cik == norm))
    if not exists:
        db.add(Fund(name=name.strip(), cik=norm, active=active))
        db.commit()
    return RedirectResponse("/admin/funds", status_code=303)


@app.post("/admin/funds/{fund_id}/toggle")
def toggle_fund(fund_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> RedirectResponse:
    fund = db.get(Fund, fund_id)
    if fund:
        fund.active = not fund.active
        db.commit()
    return RedirectResponse("/admin/funds", status_code=303)


@app.post("/admin/funds/{fund_id}/delete")
def delete_fund(fund_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> RedirectResponse:
    fund = db.get(Fund, fund_id)
    if fund:
        db.delete(fund)
        db.commit()
    return RedirectResponse("/admin/funds", status_code=303)


@app.post("/admin/update-now", response_class=HTMLResponse)
def update_now(request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)) -> HTMLResponse:
    result = ingest_active_funds(db)
    funds = db.scalars(select(Fund).order_by(Fund.created_at.desc())).all()
    return templates.TemplateResponse(
        "admin_funds.html",
        {
            "request": request,
            "funds": funds,
            "message": (
                f"Update finished. checked={result.funds_checked} new={result.new_filings} "
                f"parsed={result.parsed_filings} failed={result.failed_filings}"
            ),
        },
    )
