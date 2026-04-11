"""Evidence-based tests for PodDisruptionBudget rendering.

Captures v0.9 plan item 5: `podDisruptionBudgets.enabled=true` is set
in values.yaml but no PDBs appear in the rendered chart. These tests
shell out to `helm template` and parse the YAML so the evidence is
end-to-end and invariant to helm unittest plugins.

Two bugs were diagnosed:

Bug 1 — replicas gate. The templates used
``(gt (int .Values.X.replicas) 1)`` which blocked PDB rendering at the
default ``replicas: 1``. A PDB with ``maxUnavailable: 0`` is still
valid and meaningful at single-replica — it blocks voluntary eviction
during node drains until something bumps the replica count, which is
exactly what we want for P0/P1 workloads during a cluster upgrade.

Bug 2 — latent chart crash. The template `vault-deployment.yaml:1:14`
references ``.Values.vault.enabled`` but ``values.yaml`` had no
``vault:`` key at all. ``helm template`` crashed with
``<.Values.vault.enabled>: nil pointer`` before any PDB could appear.
The ``test_chart_renders_at_all_on_defaults`` test holds this honest.

These tests currently FAIL on the unfixed chart and PASS after the
PDB template + values.yaml fix.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - dev env without PyYAML
    yaml = None  # type: ignore[assignment]

CHART_PATH = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "stronghold"

pytestmark = [
    pytest.mark.skipif(shutil.which("helm") is None, reason="helm binary not on PATH"),
    pytest.mark.skipif(yaml is None, reason="PyYAML not installed"),
    pytest.mark.skipif(not CHART_PATH.is_dir(), reason=f"chart missing: {CHART_PATH}"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _helm_template(*, with_defaults: bool = False, **overrides: object) -> list[dict]:
    """Render the chart with --set overrides and return parsed YAML docs.

    Unless ``with_defaults=True``, the helper injects
    ``--set vault.enabled=false`` so unrelated latent template crashes
    (like the vault nil-pointer bug) don't mask PDB assertions. Tests
    that specifically want to exercise the default-values render path
    pass ``with_defaults=True``.
    """
    sets: list[str] = []
    if not with_defaults:
        sets.extend(["--set", "vault.enabled=false"])
    for key, value in overrides.items():
        sets.extend(["--set", f"{key}={value}"])
    cmd = ["helm", "template", "stronghold", str(CHART_PATH), *sets]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        msg = (
            f"helm template failed (exit {proc.returncode}):\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {proc.stderr}"
        )
        raise AssertionError(msg)
    return [d for d in yaml.safe_load_all(proc.stdout) if d]


def _pdbs(docs: list[dict]) -> list[dict]:
    return [d for d in docs if d.get("kind") == "PodDisruptionBudget"]


def _pdb_by_component(docs: list[dict], component: str) -> dict:
    """Fetch the PDB whose selector matches a component label, or fail."""
    for pdb in _pdbs(docs):
        sel = pdb.get("spec", {}).get("selector", {}).get("matchLabels", {})
        if sel.get("app.kubernetes.io/component") == component:
            return pdb
    msg = f"no PDB found with selector component={component!r}"
    raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Bug 2 — chart render must not crash on defaults
# ---------------------------------------------------------------------------


class TestChartBaseline:
    def test_chart_renders_at_all_on_defaults(self) -> None:
        """Baseline: the default chart must render end-to-end.

        Currently FAILS with `vault.enabled: nil pointer` until
        values.yaml gains a `vault:` stanza. This test exists so the
        latent crash does not stay hidden behind PDB-only assertions.
        """
        docs = _helm_template(with_defaults=True)
        kinds = {d.get("kind") for d in docs}
        # Baseline set — if the render is sane, these must all be there.
        assert "Deployment" in kinds
        assert "Service" in kinds


# ---------------------------------------------------------------------------
# Bug 1 — single-replica PDB rendering
# ---------------------------------------------------------------------------


class TestPdbSingleReplica:
    @pytest.fixture(scope="class")
    def docs(self) -> list[dict]:
        return _helm_template(
            **{
                "strongholdApi.replicas": 1,
                "litellmProxy.replicas": 1,
                "podDisruptionBudgets.enabled": "true",
            }
        )

    def test_exactly_two_pdbs_render(self, docs: list[dict]) -> None:
        """One PDB per protected workload (stronghold-api, litellm)."""
        pdbs = _pdbs(docs)
        assert len(pdbs) == 2, f"expected 2 PDBs at replicas=1, got {len(pdbs)}"

    def test_api_pdb_has_max_unavailable_zero(self, docs: list[dict]) -> None:
        pdb = _pdb_by_component(docs, "stronghold-api")
        spec = pdb["spec"]
        assert spec.get("maxUnavailable") == 0
        assert "minAvailable" not in spec, (
            "single-replica PDB must not use minAvailable (would block all pods)"
        )

    def test_litellm_pdb_has_max_unavailable_zero(self, docs: list[dict]) -> None:
        pdb = _pdb_by_component(docs, "litellm")
        spec = pdb["spec"]
        assert spec.get("maxUnavailable") == 0
        assert "minAvailable" not in spec

    def test_pdbs_live_in_release_namespace(self, docs: list[dict]) -> None:
        for pdb in _pdbs(docs):
            ns = pdb["metadata"].get("namespace")
            assert ns, f"PDB {pdb['metadata']['name']} missing namespace"
            # Helm's default release namespace is "default" in template mode.
            assert ns == "default", ns

    def test_pdb_has_stronghold_part_of_label(self, docs: list[dict]) -> None:
        """Shared labels from the helper template must be applied."""
        for pdb in _pdbs(docs):
            labels = pdb["metadata"].get("labels", {})
            assert labels.get("app.kubernetes.io/part-of") == "stronghold" or \
                labels.get("app.kubernetes.io/name") == "stronghold", (
                    f"{pdb['metadata']['name']} missing shared stronghold labels"
                )


# ---------------------------------------------------------------------------
# Bug 1 — multi-replica PDB rendering (regression guard for the opposite edge)
# ---------------------------------------------------------------------------


class TestPdbMultiReplica:
    @pytest.fixture(scope="class")
    def docs(self) -> list[dict]:
        return _helm_template(
            **{
                "strongholdApi.replicas": 3,
                "litellmProxy.replicas": 3,
                "podDisruptionBudgets.enabled": "true",
            }
        )

    def test_both_pdbs_use_min_available(self, docs: list[dict]) -> None:
        for pdb in _pdbs(docs):
            spec = pdb["spec"]
            assert spec.get("minAvailable") == 1, (
                f"{pdb['metadata']['name']}: expected minAvailable: 1 at "
                f"multi-replica, got {spec}"
            )
            assert "maxUnavailable" not in spec, (
                f"{pdb['metadata']['name']}: must not mix min/max at multi-replica"
            )

    def test_asymmetric_replicas_still_produces_two_pdbs(self) -> None:
        """api=3, litellm=1 should produce both PDBs with different specs."""
        docs = _helm_template(
            **{
                "strongholdApi.replicas": 3,
                "litellmProxy.replicas": 1,
                "podDisruptionBudgets.enabled": "true",
            }
        )
        api = _pdb_by_component(docs, "stronghold-api")
        lite = _pdb_by_component(docs, "litellm")
        assert api["spec"].get("minAvailable") == 1
        assert lite["spec"].get("maxUnavailable") == 0


# ---------------------------------------------------------------------------
# Disabled / regression guards
# ---------------------------------------------------------------------------


class TestPdbDisabled:
    def test_explicit_disable_renders_zero(self) -> None:
        docs = _helm_template(
            **{
                "strongholdApi.replicas": 3,
                "litellmProxy.replicas": 3,
                "podDisruptionBudgets.enabled": "false",
            }
        )
        assert _pdbs(docs) == []

    def test_disable_with_single_replica_also_renders_zero(self) -> None:
        """Regression: the 'enabled' knob is authoritative regardless of replicas."""
        docs = _helm_template(
            **{
                "strongholdApi.replicas": 1,
                "litellmProxy.replicas": 1,
                "podDisruptionBudgets.enabled": "false",
            }
        )
        assert _pdbs(docs) == []


# ---------------------------------------------------------------------------
# Selector integrity — a PDB that selects nothing is silently useless
# ---------------------------------------------------------------------------


class TestSelectorIntegrity:
    def test_selectors_match_deployment_component_labels(self) -> None:
        """The PDB selector must target a component that the chart
        actually produces a Deployment for. This catches the classic
        'PDB with wrong selector protects zero pods' bug."""
        docs = _helm_template(
            **{
                "strongholdApi.replicas": 1,
                "litellmProxy.replicas": 1,
                "podDisruptionBudgets.enabled": "true",
            }
        )
        deployment_components: set[str] = set()
        for d in docs:
            if d.get("kind") != "Deployment":
                continue
            labels = (
                d.get("spec", {})
                .get("template", {})
                .get("metadata", {})
                .get("labels", {})
            )
            c = labels.get("app.kubernetes.io/component")
            if c:
                deployment_components.add(c)

        pdb_components = {
            pdb["spec"]["selector"]["matchLabels"].get(
                "app.kubernetes.io/component"
            )
            for pdb in _pdbs(docs)
        }
        # Every PDB selector must target an actual deployment component.
        orphans = pdb_components - deployment_components
        assert not orphans, (
            f"PDB selectors {orphans} do not match any Deployment; "
            f"available components: {sorted(deployment_components)}"
        )

    def test_expected_components_covered(self) -> None:
        """The two P0/P1 workloads (stronghold-api + litellm) must both
        have a PDB. This is the acceptance criterion from the v0.9 plan."""
        docs = _helm_template(
            **{
                "strongholdApi.replicas": 1,
                "litellmProxy.replicas": 1,
                "podDisruptionBudgets.enabled": "true",
            }
        )
        components = {
            pdb["spec"]["selector"]["matchLabels"].get(
                "app.kubernetes.io/component"
            )
            for pdb in _pdbs(docs)
        }
        assert components == {"stronghold-api", "litellm"}, components
