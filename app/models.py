from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Fund(Base):
    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cik: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    filings: Mapped[list["Filing"]] = relationship("Filing", back_populates="fund", cascade="all, delete-orphan")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("fund_id", "accession", name="uq_fund_accession"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_id: Mapped[int] = mapped_column(Integer, ForeignKey("funds.id"), index=True)
    accession: Mapped[str] = mapped_column(String(32), nullable=False)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    report_period: Mapped[datetime.date | None] = mapped_column(Date, nullable=True, index=True)
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    holdings_parse_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    fund: Mapped[Fund] = relationship("Fund", back_populates="filings")
    holdings: Mapped[list["Holding"]] = relationship("Holding", back_populates="filing", cascade="all, delete-orphan")


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(Integer, ForeignKey("filings.id"), index=True)
    cusip: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    class_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_usd_000: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    put_call: Mapped[str | None] = mapped_column(String(10), nullable=True)
    discretion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    voting_sole: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voting_shared: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voting_none: Mapped[int | None] = mapped_column(Integer, nullable=True)

    filing: Mapped[Filing] = relationship("Filing", back_populates="holdings")
