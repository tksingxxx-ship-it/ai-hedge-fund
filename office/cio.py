"""Office CIO.

This is not an alpha model and it is not in ALPHA_MODEL_REGISTRY. It queues
native analysts, compares the signals they actually returned, and writes a
proposal with blend_signals and apply_limits. It does not call build_orders
or tick.

Follow-up work is one extra native predict per conflicting symbol, and only
when the mission budget still has a call. A follow-up cannot enqueue another.
"""

from __future__ import annotations

from hedge_fund.llm import extract_json
from hedge_fund.models import Signal
from hedge_fund.portfolio.construction import blend_signals
from hedge_fund.risk.limits import RiskLimits, apply_limits
from hedge_fund.signals import get_investment_approach

CONFLICT_BAND = 0.15
# At most one language-model reply from each side of a disagreement.
_CHALLENGE_SIDES = 2


def sides(signals: list[Signal]) -> tuple[list[Signal], list[Signal]]:
    """Non-abstained views outside the band, split into bullish and bearish."""
    bulls, bears = [], []
    for signal in signals:
        if signal.metadata.get("abstained"):
            continue
        if signal.value >= CONFLICT_BAND:
            bulls.append(signal)
        elif signal.value <= -CONFLICT_BAND:
            bears.append(signal)
    bulls.sort(key=lambda s: s.value, reverse=True)
    bears.sort(key=lambda s: s.value)
    return bulls, bears


def representatives(signals: list[Signal]) -> list[Signal]:
    """The strongest view on each side, at most two. A third analyst is not asked."""
    bulls, bears = sides(signals)
    chosen = []
    if bulls:
        chosen.append(bulls[0])
    if bears:
        chosen.append(bears[0])
    return chosen[:_CHALLENGE_SIDES]


def conflicting(signals: list[Signal]) -> bool:
    bulls, bears = sides(signals)
    return bool(bulls) and bool(bears)


def challenge_view(model, ticker: str, own: Signal, others: list[Signal]) -> dict:
    """Ask the analyst's own language client to answer the other side.

    Quant models have no client. Their stored signal is the challenge record.
    A failed or unparseable reply is stored as a failure of the challenge,
    and the original signal is left as it was. This does not call predict
    again and does not place an order.
    """
    others_payload = [
        {"agent": s.model_name, "value": s.value, "reasoning": s.reasoning}
        for s in others if s.model_name != own.model_name
    ]
    llm = getattr(model, "_llm", None)
    if llm is None or not hasattr(model, "get_system_prompt"):
        return {
            "agent": own.model_name,
            "ticker": ticker,
            "own_value": own.value,
            "llm_called": False,
            "maintain": True,
            "response": own.reasoning or "Quant model. The stored signal is the record. No language client was called.",
            "counterparties": others_payload,
        }
    user = (
        "CHALLENGE\n"
        f"Your stored view on {ticker} is {own.value:+.2f}. Reasoning: {own.reasoning or '(none)'}\n"
        "A conflicting view from another analyst on the same desk:\n"
        + "\n".join(
            f"- {row['agent']} {row['value']:+.2f}: {row['reasoning'] or '(none)'}"
            for row in others_payload
        )
        + "\nReply with one JSON object {\"maintain\": true or false, \"response\": \"short text\"}. "
        "maintain true means you keep your stored view. This message does not place an order."
    )
    try:
        raw = llm.complete(model.get_system_prompt(), user)
        parsed = extract_json(raw)
        maintain = parsed.get("maintain")
        if not isinstance(maintain, bool):
            raise ValueError("maintain must be true or false")
        return {
            "agent": own.model_name,
            "ticker": ticker,
            "own_value": own.value,
            "llm_called": True,
            "model": getattr(llm, "model", None),
            "maintain": maintain,
            "response": str(parsed.get("response") or ""),
            "counterparties": others_payload,
        }
    except Exception as exc:
        return {
            "agent": own.model_name,
            "ticker": ticker,
            "own_value": own.value,
            "llm_called": True,
            "maintain": None,
            "error": f"{type(exc).__name__}: {exc}",
            "counterparties": others_payload,
        }


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


def opportunities(signals: list[Signal]) -> list[dict]:
    """Names the analysts actually flagged. No technical screen is applied first."""
    rows = []
    for signal in signals:
        if signal.metadata.get("abstained") or abs(signal.value) < CONFLICT_BAND:
            continue
        rows.append({
            "ticker": signal.ticker,
            "agent": signal.model_name,
            "value": signal.value,
            "reasoning": signal.reasoning,
        })
    return rows
