"""Symbol universes. The preset is data, not a new strategy."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from hedge_fund.fund.spec import normalize_universe

_PRESET = Path(__file__).resolve().parent / "data" / "us_swing_ndx_soxx.json"
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
HARD_CAP = 80


@lru_cache(maxsize=1)
def swing_preset() -> dict:
    data = json.loads(_PRESET.read_text())
    ndx = list(data["nasdaq_100"])
    extra = list(data["soxx_extra"])
    combined = normalize_universe([*ndx, *extra])
    return {
        "id": data["id"],
        "name": data["name"],
        "as_of": data["as_of"],
        "source": data["source"],
        "survivorship_warning": data["survivorship_warning"],
        "note": data["note"],
        "nasdaq_100_count": len(ndx),
        "soxx_extra_count": len(extra),
        "tickers": combined,
        "count": len(combined),
    }


def parse_universe(tickers: list[str] | None, *, preset: str | None, max_symbols: int) -> tuple[list[str], str | None]:
    if preset and preset != "us-swing-ndx-soxx":
        raise ValueError(f"unknown universe preset {preset!r}")
    chosen: list[str] = []
    if preset:
        chosen.extend(swing_preset()["tickers"])
    if tickers:
        chosen.extend(tickers)
    universe = normalize_universe(chosen)
    bad = [t for t in universe if not _TICKER.fullmatch(t)]
    if bad:
        raise ValueError(f"unsafe symbols: {', '.join(bad)}")
    if not universe:
        raise ValueError("universe is empty")
    if len(universe) > HARD_CAP:
        raise ValueError(f"universe has {len(universe)} symbols; the office hard cap is {HARD_CAP}")
    if len(universe) > max_symbols:
        raise ValueError(
            f"universe has {len(universe)} symbols and the data budget allows {max_symbols}. "
            "Narrow the list or raise max_symbols."
        )
    return universe, preset
