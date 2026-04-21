"""Tests for Vault Helm template rendering."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_vault_template_exists() -> None:
    path = Path("deploy/helm/stronghold/templates/vault-deployment.yaml")
    assert path.exists()


def test_vault_template_conditional() -> None:
    """Vault template only renders when vault.enabled is true and guards against
    a nil `.Values.vault` map (regression: #1033).

    The original guard `{{- if .Values.vault.enabled }}` panicked with
    'nil pointer evaluating interface {}.enabled' whenever `vault` was missing
    or set to null in a values file. The `and` guard forces short-circuit on
    the outer presence check.
    """
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "{{- if (and .Values.vault .Values.vault.enabled) }}" in content
    assert "{{- end }}" in content


def test_vault_template_namespace_configurable() -> None:
    """Vault namespace is not hardcoded."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert '.Values.vault.namespace | default "stronghold-system"' in content


def test_vault_template_uses_openbao_image() -> None:
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "openbao/openbao" in content


def test_vault_template_nonroot() -> None:
    """Vault pod runs as non-root."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "runAsNonRoot: true" in content


def test_vault_template_ipc_lock() -> None:
    """Vault needs IPC_LOCK capability for mlock."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "IPC_LOCK" in content


def test_vault_template_network_policy() -> None:
    """Vault has NetworkPolicy restricting ingress to stronghold-api only."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "NetworkPolicy" in content
    assert "stronghold-api" in content


def test_vault_template_health_probes() -> None:
    """Vault has readiness and liveness probes."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "readinessProbe" in content
    assert "livenessProbe" in content
    assert "/v1/sys/health" in content


# ---------------------------------------------------------------------------
# Regression: helm template must not panic when .Values.vault is missing /
# null. Before #1033's fix, `--set vault=null` produced:
#   nil pointer evaluating interface {}.enabled
# ---------------------------------------------------------------------------


def _helm_template(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — controlled args, not user input
        ["helm", "template", "deploy/helm/stronghold/", *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm binary not installed")
def test_helm_template_default_values_renders() -> None:
    """Default values.yaml (vault.enabled=false) renders cleanly."""
    result = _helm_template()
    assert result.returncode == 0, f"stderr:\n{result.stderr}"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm binary not installed")
def test_helm_template_vault_null_does_not_panic() -> None:
    """Regression #1033: passing `--set vault=null` must NOT trigger a nil
    pointer dereference inside the vault-deployment.yaml guard."""
    result = _helm_template("--set", "vault=null")
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert "nil pointer" not in result.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm binary not installed")
def test_helm_template_vault_disabled_produces_no_vault_deployment() -> None:
    """When vault is disabled, no Vault Deployment manifest is rendered."""
    result = _helm_template()
    assert result.returncode == 0
    # The Vault StatefulSet/Deployment name is `vault` in its namespace.
    assert "name: vault\n  namespace: stronghold-system" not in result.stdout
