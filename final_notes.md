Final note:
- Builders runtime and tests are complete and passing; runtime invokes Frank, Mason, Auditor stage handlers via `src/stronghold/builders`.
- Legacy `/v1/stronghold/request` route in `src/stronghold/api/routes/agents.py` still exists; live dashboard routing is not yet rebuilt around Builders.
- Workspace/tooling patches allow tests to run without `/workspace`, and FastAPI startup omits the reactor under pytest.
- `tests/builders/` covers contracts, core, runtime, services, integration, resilience, evidence, and e2e slices. Focus next on routing live delivery through Builders, deleting obsolete agent code, and re-running the repo suite to confirm no legacy regressions.
