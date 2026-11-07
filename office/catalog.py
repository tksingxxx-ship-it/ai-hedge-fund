"""Native analyst directory, read from the engine registry.

Profiles come from the class docstring, declared approach, horizon, and the
persona system prompt. The office does not invent a second roster.
"""

from __future__ import annotations

import os
from pathlib import Path

from hedge_fund.fund.spec import load_strategy
from hedge_fund.llm import DEFAULT_MODEL, env_var_for, is_supported, load_api_models, provider_for
from hedge_fund.signals import ALPHA_MODEL_REGISTRY, LLMAgent, get_horizon_days, get_investment_approach
from hedge_fund.signals.llm_agent import LLMAgent as _LLMAgent
from hedge_fund.tui.shared import DISPLAY_NAMES, STRATEGY_DIR


class _SilentLLM:
    model = "unconfigured"

    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("model credentials are not configured")


def strategy_library() -> list[dict]:
    rows = []
    for path in sorted(Path(STRATEGY_DIR).glob("*.yaml")):
        spec = load_strategy(path)
        header = []
        for line in path.read_text().splitlines():
            if line.startswith("#"):
                header.append(line[1:].strip())
            elif line.strip():
                break
        rows.append({
            "name": spec.name,
            "display_name": spec.title,
            "path": str(path),
            "description": " ".join(header),
            "weight": spec.weight,
            "blend": spec.blend.model_dump(),
            "models": [m.model_dump() for m in spec.models],
            "layer": "native",
        })
    return rows


def _staffing() -> dict[str, list[str]]:
    staffed: dict[str, list[str]] = {name: [] for name in ALPHA_MODEL_REGISTRY}
    for row in strategy_library():
        for model in row["models"]:
            staffed.setdefault(model["name"], []).append(row["name"])
    return staffed


def _prompt(name: str) -> str | None:
    cls = ALPHA_MODEL_REGISTRY[name]
    if not issubclass(cls, LLMAgent):
        return None
    agent = cls(llm=_SilentLLM())
    return agent.get_system_prompt()


def analyst_catalog() -> list[dict]:
    staffed = _staffing()
    rows = []
    for name in ALPHA_MODEL_REGISTRY:
        cls = ALPHA_MODEL_REGISTRY[name]
        kind = "llm" if issubclass(cls, _LLMAgent) else "quant"
        doc = (cls.__doc__ or "").strip()
        rows.append({
            "name": name,
            "display_name": DISPLAY_NAMES.get(name, name),
            "kind": kind,
            "layer": "native",
            "disclaimer": (
                "Stylized approximation of a published investment approach. "
                "Not the person and not an endorsement."
                if kind == "llm" else
                "Deterministic quant model. It does not call a language model."
            ),
            "investment_approach": get_investment_approach(name),
            "horizon_days": get_horizon_days(name),
            "summary": doc,
            "system_prompt": _prompt(name),
            "strategies": staffed.get(name, []),
            "department": "Systematic" if kind == "quant" else "Discretionary",
        })
    return rows


def provider_catalog() -> dict:
    models = []
    for display, model_id, provider in load_api_models():
        env_name = env_var_for(provider)
        models.append({
            "display_name": display,
            "model_id": model_id,
            "provider": provider,
            "env_var": env_name,
            "supported": is_supported(provider),
            "configured": bool(env_name and os.environ.get(env_name)),
        })
    return {
        "default_model": DEFAULT_MODEL,
        "native_assignment": "One model for every LLM agent, via make_llm. Per-agent overrides exist only for office-built funds.",
        "models": models,
    }


def provider_for_model(model_id: str) -> str | None:
    return provider_for(model_id)
