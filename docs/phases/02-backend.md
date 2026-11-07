# Phase 2 — backend and database

Status: complete.

`office/` is a FastAPI process over the engine. SQLite (`office/db.py`, schema version 1) stores missions, tasks, events, messages, approvals, jobs, and settings. It does not store a second cash or position book.

Covered by `office/tests/test_office.py`: health, native agent catalog, secret redaction, encrypted credential file mode `0600`, and restart of the same database file.
