# Deployment notes

This repository was not deployed. Do not expose the office to the public internet. It is a single-user local process.

## What a private host would run

1. `poetry install -E office` and `npm run build` inside `web/`, as in [RUNBOOK.md](RUNBOOK.md).
2. Bind `OFFICE_HOST=127.0.0.1` and reach it through an SSH tunnel or an equivalent private proxy. Do not terminate TLS inside this app; there is no auth layer.
3. Put `OFFICE_HOME` on a disk with mode `0700`. The SQLite file holds research text. It does not hold brokerage credentials in plaintext.
4. Set `OFFICE_MASTER_KEY` only in the process environment if you want the settings screen to store a key. The key is derived with PBKDF2 (200,000 iterations, SHA-256) and the credential is AES-GCM. There is no baked-in key. If the variable is absent, the office refuses to store one.
5. Keep `FINANCIAL_DATASETS_API_KEY` and model keys in the environment or `~/.hedge-fund/.env` (mode `0600`, written by the existing TUI helper). Do not commit them.
6. Leave `OFFICE_ALLOW_FIXTURES` unset on any machine where a result might be mistaken for a market run.

## What this app will not do

- No live broker plugin is wired. Requests that try to name another broker are rejected.
- Paper sessions require an approval whose hash still matches the plan. Halt is `Ledger.halt`. The unattended minute runner (`aihf paper run`) is not started by the office.
- No paid signup, no credit purchase, no automatic order.

## Upgrade

The office database is schema version 1, created on startup. The engine ledger format is unchanged. Take a copy of `OFFICE_HOME` and `~/.hedge-fund/paper` before replacing the code.
