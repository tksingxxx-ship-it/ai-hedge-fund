"""Process configuration. No default encryption key and no default API key."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from hedge_fund.paths import MANDATES_DIR, PAPER_DIR, RESEARCH_DIR, USER_DIR


def _path(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw).expanduser().resolve() if raw else Path(default)


def _flag(env: str) -> bool:
    return os.environ.get(env, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    home: Path
    db_path: Path
    secrets_path: Path
    paper_root: Path
    research_dir: Path
    mandates_dir: Path
    allow_fixtures: bool
    eager: bool
    dev_cors: bool
    host: str
    port: int
    max_backtest_sessions: int
    allow_remote: bool
    api_token: str
    fixture_only: bool

    @classmethod
    def from_env(cls) -> Config:
        fixture_only = _flag("OFFICE_FIXTURE_ONLY")
        if fixture_only:
            # Preview data stays out of a real ~/.hedge-fund book unless overridden.
            home = _path("OFFICE_HOME", Path.home() / ".hedge-fund-office-preview")
            paper = _path("OFFICE_PAPER_ROOT", home / "paper")
            research = _path("OFFICE_RESEARCH_DIR", home / "research")
            mandates = _path("OFFICE_MANDATES_DIR", home / "mandates")
            allow_fixtures = True
        else:
            home = _path("OFFICE_HOME", USER_DIR / "office")
            paper = _path("OFFICE_PAPER_ROOT", PAPER_DIR)
            research = _path("OFFICE_RESEARCH_DIR", RESEARCH_DIR)
            mandates = _path("OFFICE_MANDATES_DIR", MANDATES_DIR)
            allow_fixtures = _flag("OFFICE_ALLOW_FIXTURES")
        return cls(
            home=home,
            db_path=_path("OFFICE_DB", home / "office.sqlite3"),
            secrets_path=_path("OFFICE_SECRETS", home / "secrets.json"),
            paper_root=paper,
            research_dir=research,
            mandates_dir=mandates,
            allow_fixtures=allow_fixtures,
            eager=_flag("OFFICE_EAGER"),
            dev_cors=_flag("OFFICE_DEV_CORS"),
            host=os.environ.get("OFFICE_HOST", "127.0.0.1"),
            port=int(os.environ.get("OFFICE_PORT", "8765")),
            max_backtest_sessions=int(os.environ.get("OFFICE_MAX_BACKTEST_SESSIONS", "800")),
            allow_remote=_flag("OFFICE_ALLOW_REMOTE"),
            api_token=os.environ.get("OFFICE_API_TOKEN", ""),
            fixture_only=fixture_only,
        )

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        for path in (self.paper_root, self.research_dir, self.mandates_dir, self.db_path.parent):
            path.mkdir(parents=True, exist_ok=True)
