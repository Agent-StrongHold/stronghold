# Changelog

All notable changes to Stronghold are documented here.

## Unreleased

- Added `PreToolCallHook` protocol for pre-dispatch tool-call interception; `ToolDispatcher` now runs a configurable hook chain with Allow/Deny/Repair verdicts, per-hook timeout, and audit entries (S1.2).
