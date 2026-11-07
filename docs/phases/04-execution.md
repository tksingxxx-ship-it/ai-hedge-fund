# Phase 4 — execution

Status: complete for the fixture path. Live provider execution is implemented and refused without credentials.

`office/research.py` runs `AlphaModel.predict` on the registry classes. Task rows move `queued → working → completed|failed`. The CIO in `office/cio.py` is not registered as an analyst. Follow-up analysis is capped at one extra native call per conflicting symbol and cannot spawn further work.

`test_fixture_research_runs_native_agents_and_persists` checks Buffett `working` and `completed` events and a conflict escalation.
