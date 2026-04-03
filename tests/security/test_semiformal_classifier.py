"""Tests for Warden Layer 3 semi-formal classifier.

Tests the structured reasoning certificate approach — template construction,
certificate parsing, verdict extraction, and Warden integration.
"""

from __future__ import annotations

from stronghold.security.warden.detector import Warden
from stronghold.security.warden.semiformal_classifier import (
    _build_semiformal_prompt,
    _parse_certificate,
    classify_tool_result_semiformal,
)
from tests.fakes import FakeLLMClient

# -- Realistic certificate responses for the FakeLLM to return --

SAFE_CERTIFICATE = """\
PREMISES:
P1: Text purpose — The text describes a Redis connection pool initialization.
P2: Language — DESCRIPTIVE — quoted evidence: "Connects", "initializes"
P3: Actions referenced — BENIGN — quoted evidence: "initializes connection pool"
P4: Objects referenced — NON-SENSITIVE — quoted evidence: "connection pool", "health checks"
P5: Business justification — ABSENT

TRACE:
No prescriptive instructions found.

COUNTEREXAMPLE CHECK:
What would make this suspicious? If it said "should forward connection \
credentials to an external monitoring endpoint."

CONCLUSION:
By D1, the text is SAFE.
Evidence: P2 is entirely descriptive; no prescriptive instructions found."""

SUSPICIOUS_CERTIFICATE = """\
PREMISES:
P1: Text purpose — The text describes secret rotation and instructs the agent \
to disable RBAC.
P2: Language — MIXED — quoted evidence: "Rotates" (descriptive), \
"should bypass RBAC checks" (prescriptive)
P3: Actions referenced — DANGEROUS — quoted evidence: "bypass RBAC checks"
P4: Objects referenced — SENSITIVE — quoted evidence: "RBAC", "secrets"
P5: Business justification — PRESENT — "to avoid rotation delays"

TRACE:
- "should bypass RBAC checks" → instructs bypassing access controls → DANGEROUS

COUNTEREXAMPLE CHECK:
What would make this safe? If it said "validates RBAC permissions before rotation" \
(descriptive, no bypass instruction).

CONCLUSION:
By D1, the text is SUSPICIOUS.
Evidence: P2 contains prescriptive "should bypass", P3 identifies RBAC bypass \
as dangerous, P4 confirms sensitive security objects."""


class TestBuildSemiformalPrompt:
    def test_has_system_message(self) -> None:
        msgs = _build_semiformal_prompt("test text")
        assert msgs[0]["role"] == "system"
        assert "DEFINITIONS:" in msgs[0]["content"]
        assert "PREMISES:" in msgs[0]["content"]

    def test_has_certificate_examples(self) -> None:
        msgs = _build_semiformal_prompt("test text")
        # 6 examples = 12 messages (user+assistant) + 1 system + 1 final user = 14
        assert len(msgs) == 14

    def test_examples_alternate_user_assistant(self) -> None:
        msgs = _build_semiformal_prompt("test")
        for i in range(1, len(msgs) - 1, 2):
            assert msgs[i]["role"] == "user"
            assert msgs[i + 1]["role"] == "assistant"

    def test_example_responses_contain_certificate_structure(self) -> None:
        msgs = _build_semiformal_prompt("test")
        # Check that assistant responses have the certificate format
        for i in range(2, len(msgs) - 1, 2):
            cert = msgs[i]["content"]
            assert "PREMISES:" in cert
            assert "CONCLUSION:" in cert

    def test_final_message_is_user_with_text(self) -> None:
        msgs = _build_semiformal_prompt("my tool output")
        assert msgs[-1]["role"] == "user"
        assert "my tool output" in msgs[-1]["content"]

    def test_text_truncated_to_2000(self) -> None:
        long_text = "x" * 5000
        msgs = _build_semiformal_prompt(long_text)
        last_msg = msgs[-1]["content"]
        assert len(last_msg) == len("Analyze:\n") + 2000

    def test_uses_analyze_prefix_not_classify(self) -> None:
        """Semi-formal uses 'Analyze:' to signal structured reasoning."""
        msgs = _build_semiformal_prompt("test")
        assert msgs[-1]["content"].startswith("Analyze:\n")
        # Example user messages too
        assert msgs[1]["content"].startswith("Analyze:\n")


class TestParseCertificate:
    def test_parses_safe_verdict(self) -> None:
        result = _parse_certificate(SAFE_CERTIFICATE)
        assert result["label"] == "safe"

    def test_parses_suspicious_verdict(self) -> None:
        result = _parse_certificate(SUSPICIOUS_CERTIFICATE)
        assert result["label"] == "suspicious"

    def test_extracts_conclusion(self) -> None:
        result = _parse_certificate(SUSPICIOUS_CERTIFICATE)
        assert "SUSPICIOUS" in result["conclusion"]
        assert "P2 contains prescriptive" in result["conclusion"]

    def test_extracts_premises(self) -> None:
        result = _parse_certificate(SUSPICIOUS_CERTIFICATE)
        assert "P1:" in result["premises"]
        assert "RBAC" in result["premises"]

    def test_extracts_trace(self) -> None:
        result = _parse_certificate(SUSPICIOUS_CERTIFICATE)
        assert "bypass RBAC checks" in result["trace"]

    def test_extracts_counterexample(self) -> None:
        result = _parse_certificate(SAFE_CERTIFICATE)
        assert "forward connection credentials" in result["counterexample"]

    def test_preserves_raw(self) -> None:
        result = _parse_certificate(SAFE_CERTIFICATE)
        assert result["raw"] == SAFE_CERTIFICATE.strip()

    def test_handles_malformed_no_conclusion(self) -> None:
        """If LLM doesn't follow template, fall back to scanning full text."""
        result = _parse_certificate("This looks suspicious to me, bad stuff here")
        assert result["label"] == "suspicious"

    def test_handles_malformed_safe(self) -> None:
        result = _parse_certificate("Everything looks fine, normal code")
        assert result["label"] == "safe"

    def test_empty_string(self) -> None:
        result = _parse_certificate("")
        assert result["label"] == "safe"
        assert result["raw"] == ""


class TestClassifyToolResultSemiformal:
    async def test_safe_classification(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        result = await classify_tool_result_semiformal("normal code", llm, "test-model")
        assert result["label"] == "safe"
        assert result["model"] == "test-model"
        assert result["reasoning_trace"] == SAFE_CERTIFICATE.strip()

    async def test_suspicious_classification(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        result = await classify_tool_result_semiformal("bad stuff", llm, "test-model")
        assert result["label"] == "suspicious"
        assert "RBAC" in result["reasoning_trace"]

    async def test_returns_conclusion(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        result = await classify_tool_result_semiformal("text", llm)
        assert "SUSPICIOUS" in result["conclusion"]

    async def test_returns_premises(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        result = await classify_tool_result_semiformal("text", llm)
        assert "P1:" in result["premises"]

    async def test_tokens_from_usage(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        result = await classify_tool_result_semiformal("text", llm)
        assert isinstance(result["tokens"], int)
        assert result["tokens"] == 30

    async def test_default_model_is_auto(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        result = await classify_tool_result_semiformal("text", llm)
        assert result["model"] == "auto"

    async def test_fail_open_on_error(self) -> None:
        class BrokenLLM:
            async def complete(self, *a: object, **kw: object) -> dict:
                raise ConnectionError("LLM down")

        result = await classify_tool_result_semiformal("test", BrokenLLM(), "m")
        assert result["label"] == "safe"
        assert result.get("error") == "classification_failed"
        assert result["reasoning_trace"] == ""

    async def test_empty_choices_defaults_safe(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses({"id": "x", "choices": [], "usage": {}})
        result = await classify_tool_result_semiformal("text", llm)
        assert result["label"] == "safe"
        assert result["reasoning_trace"] == ""

    async def test_passes_max_tokens(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        await classify_tool_result_semiformal("text", llm, "model")
        assert llm.calls[0].get("max_tokens") == 800

    async def test_sends_14_messages(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        await classify_tool_result_semiformal("text", llm, "model")
        assert len(llm.calls[0]["messages"]) == 14


class TestWardenSemiformalIntegration:
    async def test_semiformal_mode_flags_suspicious(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        warden = Warden(llm=llm, classifier_model="test", semiformal=True)

        # Use text that passes L1/L2/L2.5 so L3 actually runs
        verdict = await warden.scan(
            "Rotates secrets on a 90 day schedule for compliance requirements",
            "tool_result",
        )
        assert not verdict.clean
        assert not verdict.blocked
        assert "semiformal" in verdict.flags[0]
        assert verdict.reasoning_trace is not None
        assert "RBAC" in verdict.reasoning_trace

    async def test_semiformal_mode_passes_safe(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        warden = Warden(llm=llm, classifier_model="test", semiformal=True)

        verdict = await warden.scan("normal redis connection", "tool_result")
        assert verdict.clean

    async def test_semiformal_confidence_higher_than_binary(self) -> None:
        """Semi-formal should report higher confidence (0.85 vs 0.8)."""
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        warden = Warden(llm=llm, classifier_model="test", semiformal=True)

        verdict = await warden.scan("bad content", "tool_result")
        assert verdict.confidence == 0.85

    async def test_binary_mode_still_works(self) -> None:
        """Default (semiformal=False) uses binary classifier as before."""
        llm = FakeLLMClient()
        llm.set_simple_response("suspicious")
        warden = Warden(llm=llm, classifier_model="test", semiformal=False)

        verdict = await warden.scan("bad content", "tool_result")
        assert not verdict.clean
        assert "binary" in verdict.flags[0]

    async def test_semiformal_only_on_tool_result(self) -> None:
        """L3 (semi-formal or binary) only runs on tool_result boundary."""
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        warden = Warden(llm=llm, classifier_model="test", semiformal=True)

        # Benign text that passes all layers — L3 should NOT run on user_input
        verdict = await warden.scan(
            "Rotates secrets on a 90 day schedule for compliance requirements",
            "user_input",
        )
        assert verdict.clean
        assert len(llm.calls) == 0

    async def test_reasoning_trace_none_when_safe(self) -> None:
        """Clean verdicts don't carry a reasoning trace."""
        llm = FakeLLMClient()
        llm.set_simple_response(SAFE_CERTIFICATE)
        warden = Warden(llm=llm, classifier_model="test", semiformal=True)

        verdict = await warden.scan("normal code", "tool_result")
        assert verdict.clean
        assert verdict.reasoning_trace is None

    async def test_flag_format_includes_mode(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response(SUSPICIOUS_CERTIFICATE)
        warden = Warden(llm=llm, classifier_model="m", semiformal=True)

        verdict = await warden.scan("bad", "tool_result")
        assert "mode=semiformal" in verdict.flags[0]
        assert "model=m" in verdict.flags[0]
