"""Build a native Fund and a DataClient for an office run.

Live mode uses FDClient and make_llm. Fixture mode injects FixtureLLM into
the real persona classes. The CLI's Fund(spec) path is not modified.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from hedge_fund.data import CachedDataClient, FDClient
from hedge_fund.data.client import has_data_credential
from hedge_fund.fund import Fund, FundSpec
from hedge_fund.llm import DEFAULT_MODEL, PromptCache, env_var_for, is_supported, make_llm, provider_for
from hedge_fund.signals import ALPHA_MODEL_REGISTRY, LLMAgent

from office.config import Config
from office.fixtures import FixtureDataClient, FixtureDisabled, FixtureLLM


class ConfigurationRequired(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("configuration required: " + ", ".join(missing))


def default_model(config: Config) -> str:
    from office.db import get_setting
    return get_setting(config, "default_model") or os.environ.get("HEDGE_FUND_LLM_MODEL") or DEFAULT_MODEL


def llm_parameters(config: Config) -> dict:
    """The knobs make_llm actually accepts. Temperature is not one of them."""
    from office.db import get_setting
    try:
        timeout = float(get_setting(config, "llm_timeout") or 60)
    except ValueError:
        timeout = 60.0
    try:
        max_tokens = int(get_setting(config, "llm_max_tokens") or 4096)
    except ValueError:
        max_tokens = 4096
    timeout = min(120.0, max(5.0, timeout))
    max_tokens = min(8192, max(256, max_tokens))
    return {"timeout": timeout, "max_tokens": max_tokens}


def agent_model(config: Config, agent: str) -> str | None:
    from office.db import get_setting
    return get_setting(config, f"agent_model:{agent}")


def missing_for_model(model_id: str) -> str | None:
    provider = provider_for(model_id) or "Anthropic"
    if not is_supported(provider):
        return f"unsupported provider for {model_id}"
    env_name = env_var_for(provider)
    if not env_name or not os.environ.get(env_name):
        return env_name or provider
    return None


def spec_needs_llm(spec: FundSpec) -> bool:
    for strategy in spec.strategies:
        for model in strategy.models:
            if issubclass(ALPHA_MODEL_REGISTRY[model.name], LLMAgent):
                return True
    return False


def live_blockers(config: Config, spec: FundSpec) -> list[str]:
    missing = []
    if not has_data_credential():
        missing.append("FINANCIAL_DATASETS_API_KEY or X402_WALLET_PRIVATE_KEY")
    if spec_needs_llm(spec):
        seen = set()
        for strategy in spec.strategies:
            for model in strategy.models:
                if not issubclass(ALPHA_MODEL_REGISTRY[model.name], LLMAgent):
                    continue
                model_id = agent_model(config, model.name) or default_model(config)
                gap = missing_for_model(model_id)
                if gap and gap not in seen:
                    seen.add(gap)
                    missing.append(gap)
    return missing


def build_fund(config: Config, spec: FundSpec, *, mode: str, blind: bool) -> Fund:
    if mode == "live":
        blockers = live_blockers(config, spec)
        if blockers:
            raise ConfigurationRequired(blockers)
        models: dict = {}
        for strategy in spec.strategies:
            staff = []
            for model in strategy.models:
                cls = ALPHA_MODEL_REGISTRY[model.name]
                override = agent_model(config, model.name)
                if issubclass(cls, LLMAgent):
                    chosen = override or default_model(config)
                    params = {**model.params, "llm": make_llm(chosen, **llm_parameters(config))}
                    if blind:
                        params["blind"] = True
                    staff.append(cls(**params))
                else:
                    staff.append(cls(**model.params))
            models[strategy.name] = staff
        # Explicit clients so an office model id is honored. The CLI still calls Fund(spec).
        return Fund(spec, models=models)
    if mode == "fixture":
        if not config.allow_fixtures:
            raise FixtureDisabled(
                "Fixture mode is off. Set OFFICE_ALLOW_FIXTURES=1 to run the engine on fixture data. "
                "That data is not a market or a model provider."
            )
        models = {}
        cache = PromptCache(config.home / "fixture-llm-cache")
        for strategy in spec.strategies:
            staff = []
            for model in strategy.models:
                cls = ALPHA_MODEL_REGISTRY[model.name]
                if issubclass(cls, LLMAgent):
                    staff.append(cls(**{**model.params, "llm": FixtureLLM(), "cache": cache, "blind": blind}))
                else:
                    staff.append(cls(**model.params))
            models[strategy.name] = staff
        return Fund(spec, models=models)
    raise ValueError(f"unknown execution mode {mode!r}")


@contextmanager
def data_client(config: Config, mode: str, *, live_quotes: bool = False) -> Iterator:
    if mode == "fixture":
        if not config.allow_fixtures:
            raise FixtureDisabled("Fixture mode is off.")
        yield FixtureDataClient()
        return
    if mode != "live":
        raise ValueError(f"unknown execution mode {mode!r}")
    if not has_data_credential():
        raise ConfigurationRequired(["FINANCIAL_DATASETS_API_KEY or X402_WALLET_PRIVATE_KEY"])
    with FDClient() as raw:
        yield CachedDataClient(raw, live=live_quotes)
