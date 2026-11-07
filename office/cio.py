"""Office CIO.

This is not an alpha model and it is not in ALPHA_MODEL_REGISTRY. It queues
native analysts, compares the signals they actually returned, and writes a
proposal with blend_signals and apply_limits. It does not call build_orders
or tick.

Follow-up work is one extra native predict per conflicting symbol, and only
when the mission budget still has a call. A follow-up cannot enqueue another.
"""

from __future__ import annotations

from hedge_fund.models import Signal
from hedge_fund.portfolio.construction import blend_signals
from hedge_fund.risk.limits import RiskLimits, apply_limits
from hedge_fund.signals import get_investment_approach

CONFLICT_BAND = 0.15


def conflicting(signals: list[Signal]) -> bool:
    sides = set()
    for signal in signals:
        if signal.metadata.get("abstained"):
            continue
        if signal.value >= CONFLICT_BAND:
            sides.add(1)
        elif signal.value <= -CONFLICT_BAND:
            sides.add(-1)
    return sides == {1, -1}


def propose(strategies: list[dict], signals_by_strategy: dict[str, list[Signal]], risk: RiskLimits) -> dict:
    """Net stored views the way assess_fund nets a cycle, without re-running analysts."""
    slices = {s["name"]: float(s.get("weight") or 1.0) for s in strategies}
    total = sum(slices.values()) or 1.0
    netted: dict[str, float] = {}
    sleeves = []
    for strategy in strategies:
        name = strategy["name"]
        raw = signals_by_strategy.get(name, [])
        if not raw:
            sleeves.append({"name": name, "signals": 0, "flat_reason": "no signals stored"})
            continue
        weights = {m["name"]: float(m.get("weight") or 1.0) for m in strategy["models"]}
        approaches = {m["name"]: get_investment_approach(m["name"]) for m in strategy["models"]}
        blend = blend_signals(
            raw, weights, float(strategy["blend"]["gross_target"]),
            mode=strategy["blend"]["mode"], investment_approaches=approaches,
        )
        portion = slices[name] / total
        for ticker, weight in blend.weights.items():
            netted[ticker] = netted.get(ticker, 0.0) + portion * weight
        sleeves.append({
            "name": name,
            "slice": portion,
            "convictions": blend.convictions,
            "weights": blend.weights,
            "flat_reason": blend.flat_reason,
            "signals": [
                {"agent": s.model_name, "ticker": s.ticker, "value": s.value,
                 "reasoning": s.reasoning, "abstained": bool(s.metadata.get("abstained")),
                 "metadata": s.metadata}
                for s in raw
            ],
        })
    preserve = any(s["blend"]["mode"] == "dollar_neutral" for s in strategies)
    # Factor caps need an exposure model fitted on prices. The proposal uses
    # the position and gross clamps, which do not. A mandate that sets a
    # factor cap is clamped without that cap here and the omission is labelled.
    factor_limits = [name for name in ("max_beta", "max_sector_pct", "max_volatility") if getattr(risk, name)]
    applied = risk.model_copy(update={name: None for name in factor_limits}) if factor_limits else risk
    result = apply_limits(netted, applied, preserve_proportions=preserve)
    return {
        "kind": "allocation_proposal",
        "orders_placed": False,
        "note": "Proposal only. blend_signals and apply_limits ran on stored signals. advance was not called.",
        "factor_limits_not_applied": factor_limits,
        "sleeves": sleeves,
        "target_weights": netted,
        "final_weights": result.weights,
        "clamps": [c.model_dump() for c in result.clamps],
    }
