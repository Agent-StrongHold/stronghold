# Changelog

All notable changes to Stronghold are documented here.

## Unreleased

- Added canary-token Warden layer for prompt-injection exfiltration detection (S1.1).
- Added `SessionCheckpoint` type, `CheckpointStore` protocol, `InMemoryCheckpointStore`, and admin read endpoints at `/v1/stronghold/admin/checkpoints[/{id}]` (S1.3). Schema is byte-compatible with the client-side `/checkpoint-save` skill for forward ingestion.
- Added `PreToolCallHook` protocol for pre-dispatch tool-call interception; `ToolDispatcher` now runs a configurable hook chain with Allow/Deny/Repair verdicts, per-hook timeout, and audit entries (S1.2).
