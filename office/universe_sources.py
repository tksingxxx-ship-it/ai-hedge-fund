"""Verified universe files.

A preset is usable only when every ticker was parsed from a named public
document that states its own as-of date. Cash, collateral, and futures are
dropped. Nothing in this module invents a membership date or fills a gap
with a remembered ticker.

The shipped file is the output of ``refresh_file`` against:

- Nasdaq's public list endpoint, field ``data.date``
- iShares' official SOXX holdings CSV, the "Fund Holdings as of" line

It is a dated snapshot, not a live membership feed. Using it on any session
before that as-of date is survivorship bias: names that joined later are
present, and names that had already left are absent.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from hedge_fund.fund.spec import normalize_universe

NDX_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
SOXX_URL = "https://www.ishares.com/us/products/239705/ishares-semiconductor-etf/latest-holdings.csv"
PRESET_ID = "us-swing-ndx-soxx"
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_SHIPPED = Path(__file__).resolve().parent / "data" / "us_swing_ndx_soxx.json"

SURVIVORSHIP = (
    "These are the constituents and equity holdings published on the dates below, "
    "not the membership that existed on earlier sessions. A backtest that uses this "
    "list before those dates includes names that were not in the set then and drops "
    "names that had already left. That is survivorship bias. This file does not "
    "reconstruct historical index membership."
)


class UniverseUnverified(ValueError):
    pass


def _iso_from_prose(raw: str) -> str:
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", raw.strip())
    if not match:
        raise UniverseUnverified(f"no as-of date in {raw!r}")
    month = _MONTHS.get(match.group(1)[:3].lower())
    if month is None:
        raise UniverseUnverified(f"unrecognized month in {raw!r}")
    return datetime(int(match.group(3)), month, int(match.group(2))).date().isoformat()


def parse_ndx(payload: dict) -> dict:
    """Tickers from the Nasdaq list endpoint. The date is ``data.date`` only."""
    try:
        block = payload["data"]
        raw_date = block["date"]
        rows = block["data"]["rows"]
        reported = int(block["totalrecords"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UniverseUnverified(f"Nasdaq payload is not the list endpoint: {exc}") from exc
    if not isinstance(raw_date, str) or not raw_date.strip():
        raise UniverseUnverified("Nasdaq payload has no data.date")
    tickers = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not _TICKER.fullmatch(symbol):
            raise UniverseUnverified(f"Nasdaq row has an unsafe symbol {symbol!r}")
        tickers.append(symbol)
    tickers = normalize_universe(tickers)
    if len(tickers) != reported or len(tickers) != len(rows):
        raise UniverseUnverified(
            f"Nasdaq reported {reported} records, parsed {len(tickers)} from {len(rows)} rows"
        )
    return {
        "id": "nasdaq-100",
        "source_url": NDX_URL,
        "as_of": _iso_from_prose(raw_date),
        "as_of_raw": raw_date,
        "as_of_field": "data.date",
        "row_count": len(tickers),
        "tickers": tickers,
    }


def parse_soxx(text: str) -> dict:
    """Equity rows from the iShares holdings CSV. Cash and derivatives are excluded."""
    lines = text.splitlines()
    as_of_raw = None
    for line in lines[:8]:
        if line.lower().startswith("fund holdings as of"):
            parts = next(csv.reader([line]))
            if len(parts) < 2:
                break
            as_of_raw = parts[1].strip().strip('"')
            break
    if not as_of_raw:
        raise UniverseUnverified("SOXX CSV has no Fund Holdings as of line")
    header_at = next((i for i, line in enumerate(lines) if line.startswith("Ticker,")), None)
    if header_at is None:
        raise UniverseUnverified("SOXX CSV has no Ticker header")
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_at:])))
    tickers = []
    excluded: dict[str, list[str]] = {}
    for row in reader:
        symbol = (row.get("Ticker") or "").strip().upper()
        asset = (row.get("Asset Class") or "").strip()
        if not symbol:
            continue
        if asset != "Equity":
            excluded.setdefault(asset or "unknown", []).append(symbol)
            continue
        if not _TICKER.fullmatch(symbol):
            raise UniverseUnverified(f"SOXX equity row has an unsafe symbol {symbol!r}")
        tickers.append(symbol)
    tickers = normalize_universe(tickers)
    if not tickers:
        raise UniverseUnverified("SOXX CSV parsed no equity rows")
    return {
        "id": "soxx-equity",
        "source_url": SOXX_URL,
        "as_of": _iso_from_prose(as_of_raw),
        "as_of_raw": as_of_raw,
        "as_of_field": "Fund Holdings as of",
        "row_count": len(tickers),
        "tickers": tickers,
        "excluded_non_equity": {k: v for k, v in sorted(excluded.items())},
    }


def combine(ndx: dict, soxx: dict, *, fetched_at: str) -> dict:
    """Deduplicate. Order is the Nasdaq list, then SOXX names that were not on it."""
    tickers = normalize_universe([*ndx["tickers"], *soxx["tickers"]])
    return {
        "id": PRESET_ID,
        "verified": True,
        "current": False,
        "name": "US swing snapshot: Nasdaq-100 list plus SOXX equity holdings",
        "note": (
            "Dated publisher snapshots. Not a live membership feed. "
            f"Nasdaq list {ndx['as_of_raw']}. iShares equity holdings {soxx['as_of_raw']}. "
            "Cash, collateral, and futures from the SOXX file are excluded."
        ),
        "survivorship_warning": SURVIVORSHIP,
        "fetched_at": fetched_at,
        "components": [ndx, soxx],
        "tickers": tickers,
        "count": len(tickers),
    }


def validate_preset(data: dict) -> dict:
    """Reject a file that does not carry both publisher documents."""
    if not isinstance(data, dict) or data.get("id") != PRESET_ID or data.get("verified") is not True:
        raise UniverseUnverified("preset is not a verified universe file")
    components = data.get("components")
    if not isinstance(components, list) or len(components) != 2:
        raise UniverseUnverified("preset must contain the Nasdaq list and the SOXX equity list")
    by_id = {c.get("id"): c for c in components}
    for key, url in (("nasdaq-100", NDX_URL), ("soxx-equity", SOXX_URL)):
        component = by_id.get(key)
        if not component or component.get("source_url") != url:
            raise UniverseUnverified(f"missing publisher source for {key}")
        if not component.get("as_of") or not component.get("as_of_raw"):
            raise UniverseUnverified(f"{key} has no publisher as-of date")
        tickers = component.get("tickers")
        if not isinstance(tickers, list) or not tickers:
            raise UniverseUnverified(f"{key} has no tickers")
        if any(not _TICKER.fullmatch(t) for t in tickers):
            raise UniverseUnverified(f"{key} contains an unsafe symbol")
    soxx = by_id["soxx-equity"]
    banned = {"USD", "XTSLA", "WFFUT", "IXTZ6"}
    if banned & set(soxx["tickers"]):
        raise UniverseUnverified("SOXX equity list still contains a cash or derivative row")
    combined = normalize_universe([*by_id["nasdaq-100"]["tickers"], *soxx["tickers"]])
    if data.get("tickers") != combined:
        raise UniverseUnverified("combined ticker list does not match the two publisher lists")
    if data.get("current") is not False:
        raise UniverseUnverified("a dated snapshot must not be labelled current")
    return data


def load_shipped() -> dict:
    try:
        data = json.loads(_SHIPPED.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise UniverseUnverified(f"shipped universe file is unreadable: {exc}") from exc
    return validate_preset(data)


def refresh_file(dest: Path, *, timeout: float = 30.0) -> dict:
    """Download both publisher files and write a verified preset. Raises on any gap."""
    headers = {"User-Agent": "aihf-office", "Accept": "application/json,text/csv,*/*"}
    ndx_resp = requests.get(NDX_URL, headers=headers, timeout=timeout)
    ndx_resp.raise_for_status()
    soxx_resp = requests.get(SOXX_URL, headers=headers, timeout=timeout)
    soxx_resp.raise_for_status()
    preset = combine(
        parse_ndx(ndx_resp.json()),
        parse_soxx(soxx_resp.text),
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    validate_preset(preset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(preset, indent=2) + "\n")
    return preset
