"""Symbol universes. Only a verified publisher snapshot can be selected."""

from __future__ import annotations

import re
from pathlib import Path

from hedge_fund.fund.spec import normalize_universe

from office.universe_sources import PRESET_ID, UniverseUnverified, load_shipped

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
HARD_CAP = 160


def swing_preset(override: Path | None = None) -> dict | None:
    """A validated snapshot. An office-home file wins over the shipped one.

    An invalid file is ignored. It is never repaired into a guessed list.
    """
    if override is not None and override.is_file():
        try:
            import json
            from office.universe_sources import validate_preset
            return validate_preset(json.loads(override.read_text()))
        except (OSError, json.JSONDecodeError, UniverseUnverified):
            pass
    try:
        return load_shipped()
    except UniverseUnverified:
        return None


def parse_universe(tickers: list[str] | None, *, preset: str | None, max_symbols: int) -> tuple[list[str], str | None]:
    chosen: list[str] = []
    if preset:
        if preset != PRESET_ID:
            raise ValueError(f"unknown universe preset {preset!r}")
        snapshot = swing_preset()
        if snapshot is None:
            raise ValueError(
                "The US swing preset is not available. It is only enabled when the "
                "shipped file still matches the Nasdaq list and the iShares SOXX equity file. "
                "Import symbols explicitly, or run the universe refresh."
            )
        chosen.extend(snapshot["tickers"])
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
            "Narrow the list or raise max_symbols. The preset is not applied silently in part."
        )
    return universe, preset
