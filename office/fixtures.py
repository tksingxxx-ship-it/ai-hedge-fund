"""Deterministic stand-ins for market data and LLM text.

Used only when the office is started with OFFICE_ALLOW_FIXTURES=1 and the
caller sets execution_mode to fixture. Responses are labelled fixture.
They are not market prices and not provider output.

The objects implement the engine's DataClient and LLMClient shapes so the
real agent classes, backtest_fund, and tick run unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from hedge_fund.data.models import (
    CompanyFacts,
    EarningsData,
    EarningsRecord,
    FinancialMetrics,
    Price,
)
from hedge_fund.data.sessions import completed_through

# Personas are recognized by the real system prompt text, not by a parallel team.
_PERSONA = (
    ("Warren Buffett", "bullish", 72, "Fixture response for the Buffett persona. Not a live model."),
    ("Charlie Munger", "bullish", 55, "Fixture response for the Munger persona. Not a live model."),
    ("Benjamin Graham", "bullish", 40, "Fixture response for the Graham persona. Not a live model."),
    ("Peter Lynch", "neutral", 30, "Fixture response for the Lynch persona. Not a live model."),
    ("Stanley Druckenmiller", "bearish", 65, "Fixture response for the Druckenmiller persona. Not a live model."),
)


class FixtureDisabled(RuntimeError):
    pass


class FixtureLLM:
    """Canned JSON in the shape LLMAgent._parse requires."""

    model = "fixture-llm"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        for needle, signal, confidence, reasoning in _PERSONA:
            if needle in system:
                return json.dumps({"signal": signal, "confidence": confidence, "reasoning": reasoning})
        return json.dumps({
            "signal": "neutral",
            "confidence": 10,
            "reasoning": "Fixture response. The system prompt did not match a native persona.",
        })


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)


def business_days(start: date, end: date) -> list[str]:
    days = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


class FixtureDataClient:
    """Weekday bars from 2023-01-03 through the last completed New York session.

    Prices are a seeded function of the symbol. Filings are dated before the
    session that may see them. get_financial_metrics drops rows filed after
    end_date, matching the engine's point-in-time contract.
    """

    source = "fixture"

    def __init__(self, *, clock_end: str | None = None) -> None:
        self._end = clock_end or completed_through()
        self._days = business_days(date(2023, 1, 3), date.fromisoformat(self._end))
        self._index = {day: i for i, day in enumerate(self._days)}

    def get_prices(self, ticker, start_date, end_date, **kwargs):
        bars = []
        for day in self._days:
            if start_date <= day <= end_date:
                close = self._close(ticker, day)
                bars.append(Price(
                    open=close, close=close, high=close, low=close,
                    volume=2_000_000, time=f"{day}T00:00:00Z",
                ))
        return bars

    def get_snapshot(self, ticker):
        return None

    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=10):
        rows = []
        for offset, quarter in enumerate(("2024-12-31", "2024-09-30", "2024-06-30", "2024-03-31",
                                          "2023-12-31", "2023-09-30", "2023-06-30", "2023-03-31")):
            filed = _shift(quarter, 40)
            if filed > end_date[:10]:
                continue
            base = 0.12 + (_seed(ticker) % 17) / 100
            rows.append(FinancialMetrics(
                ticker=ticker, report_period=quarter, period="ttm", filing_date=filed,
                market_cap=50e9 + (_seed(ticker) % 500) * 1e8,
                price_to_earnings_ratio=18 + (_seed(ticker) % 12),
                return_on_equity=base,
                gross_margin=0.45,
                operating_margin=0.22,
                net_margin=0.16,
                debt_to_equity=0.4,
                current_ratio=1.8,
                revenue_growth=0.08,
                earnings_per_share=4 + offset * 0.1,
                book_value_per_share=20 + offset,
                free_cash_flow_per_share=3.5,
            ))
            if len(rows) >= limit:
                break
        return rows

    def get_news(self, ticker, end_date, start_date=None, limit=1000):
        return []

    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        return []

    def get_company_facts(self, ticker):
        return CompanyFacts(ticker=ticker, name=f"{ticker} (fixture)", sector="Technology", industry="Fixture")

    def get_earnings(self, ticker):
        return None

    def get_earnings_history(self, ticker, limit=12):
        surprise = "BEAT" if _seed(ticker) % 2 == 0 else "MISS"
        records = []
        # One 8-K a quarter, filed 20 days after the period so PEAD's
        # retrospective cutoff (45 days) keeps it, and only the sessions
        # inside the model's 4-day window will fire.
        for quarter in ("2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
                        "2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"):
            filed = _shift(quarter, 20)
            records.append(EarningsRecord(
                ticker=ticker, report_period=quarter, source_type="8-K", filing_date=filed,
                quarterly=EarningsData(eps_surprise=surprise, earnings_per_share=1.0),
            ))
        # A recent filing so a research date near the last completed session
        # can observe a fresh surprise without looking ahead of that session.
        recent = self._end
        records.append(EarningsRecord(
            ticker=ticker, report_period=_shift(recent, -20), source_type="8-K", filing_date=recent,
            quarterly=EarningsData(eps_surprise=surprise, earnings_per_share=1.2),
        ))
        return records[:limit]

    def get_market_cap(self, ticker, end_date):
        metrics = self.get_financial_metrics(ticker, end_date, limit=1)
        return metrics[0].market_cap if metrics else None

    def _close(self, ticker: str, day: str) -> float:
        i = self._index[day]
        base = 40 + (_seed(ticker) % 360)
        return round(base * (1 + 0.0004 * i), 2)


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day[:10]) + timedelta(days=days)).isoformat()
