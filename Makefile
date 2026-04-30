# Stronghold — local CI-gate parity.
#
# Targets follow ARCHITECTURE.md §16.7.4. Each gate has two:
#   make baseline-<gate>  — regenerate the baseline file (write side).
#   make gate-<gate>      — run the gate as CI runs it (read side).
#
# CI invokes the gate-* targets via .github/workflows/ci.yml. Devs
# invoke baseline-<gate> after refactoring an offender, then commit
# the smaller baseline file as part of their PR.

PYTHON ?= python3
SRC := src/stronghold

.PHONY: help
help:
	@echo "Stronghold gate targets (ARCHITECTURE.md §16.7.4):"
	@echo "  make baseline-xenon     — refresh .xenon-baseline.json from current offenders"
	@echo "  make gate-xenon         — run G-1 (xenon + baseline filter) as CI does"
	@echo "  make gates-all          — run every implemented gate (currently: G-1)"

# ── G-1: Cyclomatic complexity (xenon) ──────────────────────────────────────

XENON_THRESHOLDS := --max-absolute C --max-modules C --max-average C

.PHONY: baseline-xenon
baseline-xenon:
	@$(PYTHON) scripts/regen_xenon_baseline.py $(SRC)
	@echo "Wrote .xenon-baseline.json. Review the diff before committing."

.PHONY: gate-xenon
gate-xenon:
	@$(PYTHON) scripts/xenon_with_baseline.py \
		--baseline .xenon-baseline.json \
		$(XENON_THRESHOLDS) \
		$(SRC)

# ── G-2: Vulture whitelist shrink-only ─────────────────────────────────────

# Defaults to comparing against origin/integration; override via VULTURE_BASE
# for stacked PRs (e.g. `make gate-vulture-whitelist VULTURE_BASE=origin/foo`).
VULTURE_BASE ?= origin/integration

.PHONY: gate-vulture-whitelist
gate-vulture-whitelist:
	@$(PYTHON) scripts/check_vulture_whitelist.py --base $(VULTURE_BASE)

# ── G-3: jscpd duplication ─────────────────────────────────────────────────

.PHONY: baseline-jscpd
baseline-jscpd:
	@$(PYTHON) scripts/regen_jscpd_baseline.py $(SRC)
	@echo "Wrote .jscpd-baseline.json. Review the diff before committing."

.PHONY: gate-jscpd
gate-jscpd:
	@$(PYTHON) scripts/check_jscpd_baseline.py \
		--baseline .jscpd-baseline.json \
		$(SRC)

# ── Aggregate ──────────────────────────────────────────────────────────────

.PHONY: gates-all
gates-all: gate-xenon gate-vulture-whitelist gate-jscpd
	@echo "All implemented gates passed."
