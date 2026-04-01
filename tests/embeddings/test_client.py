"""Tests for InMemoryEmbeddingClient and LiteLLMEmbeddingClient.

InMemoryEmbeddingClient: deterministic hash-based 384-dim vectors.
LiteLLMEmbeddingClient: proxies to LiteLLM /embeddings endpoint (uses respx for HTTP).
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response as HttpxResponse

from stronghold.embeddings.client import InMemoryEmbeddingClient, LiteLLMEmbeddingClient
from stronghold.protocols.embeddings import EmbeddingClient


# ── InMemoryEmbeddingClient ─────────────────────────────────────────


class TestInMemoryProtocolConformance:
    """InMemoryEmbeddingClient implements EmbeddingClient protocol."""

    def test_is_embedding_client(self) -> None:
        client = InMemoryEmbeddingClient()
        assert isinstance(client, EmbeddingClient)

    def test_dimension_is_384(self) -> None:
        client = InMemoryEmbeddingClient()
        assert client.dimension == 384


class TestInMemoryEmbed:
    """embed() returns deterministic 384-dim vectors."""

    async def test_returns_384_floats(self) -> None:
        client = InMemoryEmbeddingClient()
        vec = await client.embed("hello world")
        assert len(vec) == 384
        assert all(isinstance(v, float) for v in vec)

    async def test_values_in_range(self) -> None:
        client = InMemoryEmbeddingClient()
        vec = await client.embed("test input")
        assert all(-1.0 <= v <= 1.0 for v in vec)

    async def test_deterministic(self) -> None:
        client = InMemoryEmbeddingClient()
        v1 = await client.embed("same text")
        v2 = await client.embed("same text")
        assert v1 == v2

    async def test_different_inputs_different_vectors(self) -> None:
        client = InMemoryEmbeddingClient()
        v1 = await client.embed("hello")
        v2 = await client.embed("goodbye")
        assert v1 != v2


class TestInMemoryEmbedBatch:
    """embed_batch() returns a list of vectors, one per input."""

    async def test_batch_returns_correct_count(self) -> None:
        client = InMemoryEmbeddingClient()
        texts = ["alpha", "bravo", "charlie"]
        result = await client.embed_batch(texts)
        assert len(result) == 3
        assert all(len(v) == 384 for v in result)

    async def test_batch_matches_individual(self) -> None:
        client = InMemoryEmbeddingClient()
        texts = ["one", "two"]
        batch = await client.embed_batch(texts)
        individual = [await client.embed(t) for t in texts]
        assert batch == individual

    async def test_empty_batch(self) -> None:
        client = InMemoryEmbeddingClient()
        result = await client.embed_batch([])
        assert result == []


# ── LiteLLMEmbeddingClient ──────────────────────────────────────────


class TestLiteLLMProtocolConformance:
    """LiteLLMEmbeddingClient implements EmbeddingClient protocol."""

    def test_is_embedding_client(self) -> None:
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
        )
        assert isinstance(client, EmbeddingClient)

    def test_dimension_default(self) -> None:
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
        )
        assert client.dimension == 384

    def test_dimension_custom(self) -> None:
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
            dim=1536,
        )
        assert client.dimension == 1536


class TestLiteLLMEmbed:
    """embed() calls LiteLLM and returns the vector."""

    @respx.mock
    async def test_embed_single(self) -> None:
        respx.post("http://fake:4000/v1/embeddings").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "object": "list",
                    "data": [{"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0}],
                    "model": "text-embedding-3-small",
                    "usage": {"prompt_tokens": 2, "total_tokens": 2},
                },
            )
        )
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
        )
        vec = await client.embed("hello")
        assert vec == [0.1, 0.2, 0.3]

    @respx.mock
    async def test_embed_sends_auth_header(self) -> None:
        route = respx.post("http://fake:4000/v1/embeddings").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "object": "list",
                    "data": [{"object": "embedding", "embedding": [0.5], "index": 0}],
                    "model": "m",
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        )
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-secret-key",
        )
        await client.embed("test")
        assert route.called
        req = route.calls[0].request
        assert req.headers["authorization"] == "Bearer sk-secret-key"


class TestLiteLLMEmbedBatch:
    """embed_batch() sends a list and returns vectors in order."""

    @respx.mock
    async def test_batch_returns_ordered(self) -> None:
        # Return out-of-order to verify sorting
        respx.post("http://fake:4000/v1/embeddings").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"object": "embedding", "embedding": [0.2], "index": 1},
                        {"object": "embedding", "embedding": [0.1], "index": 0},
                    ],
                    "model": "text-embedding-3-small",
                    "usage": {"prompt_tokens": 4, "total_tokens": 4},
                },
            )
        )
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
        )
        result = await client.embed_batch(["first", "second"])
        assert result == [[0.1], [0.2]]

    @respx.mock
    async def test_batch_empty_returns_empty(self) -> None:
        # Should not even make an HTTP call
        route = respx.post("http://fake:4000/v1/embeddings").mock(
            return_value=HttpxResponse(200, json={"data": []}),
        )
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
        )
        result = await client.embed_batch([])
        assert result == []
        assert not route.called


class TestLiteLLMErrorHandling:
    """LiteLLMEmbeddingClient raises on HTTP errors."""

    @respx.mock
    async def test_401_raises(self) -> None:
        respx.post("http://fake:4000/v1/embeddings").mock(
            return_value=HttpxResponse(401, json={"error": "unauthorized"}),
        )
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="bad-key",
        )
        with pytest.raises(Exception):  # noqa: B017
            await client.embed("test")

    @respx.mock
    async def test_500_raises(self) -> None:
        respx.post("http://fake:4000/v1/embeddings").mock(
            return_value=HttpxResponse(500, json={"error": "internal"}),
        )
        client = LiteLLMEmbeddingClient(
            base_url="http://fake:4000",
            api_key="sk-test",
        )
        with pytest.raises(Exception):  # noqa: B017
            await client.embed("test")
