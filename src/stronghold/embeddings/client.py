"""Embedding client implementations.

InMemoryEmbeddingClient — deterministic hash-based 384-dim vectors for testing.
LiteLLMEmbeddingClient — proxies to LiteLLM /embeddings endpoint.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from typing import Any

import httpx

logger = logging.getLogger("stronghold.embeddings")

_DIMENSION = 384


class InMemoryEmbeddingClient:
    """Deterministic fake embedding client for testing.

    Generates 384-dim vectors from a SHA-256 hash of the input text.
    Same input always produces the same vector. Implements EmbeddingClient protocol.
    """

    @property
    def dimension(self) -> int:
        return _DIMENSION

    def _hash_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic 384-dim vector via SHA-256 cycling."""
        # We need 384 floats. SHA-256 gives 32 bytes = 8 floats (4 bytes each).
        # Cycle the hash with different seeds to fill 384 dimensions.
        result: list[float] = []
        idx = 0
        while len(result) < _DIMENSION:
            digest = hashlib.sha256(f"{idx}:{text}".encode()).digest()
            # Each 4 bytes -> one float in [-1, 1]
            for offset in range(0, 32, 4):
                if len(result) >= _DIMENSION:
                    break
                raw = struct.unpack_from(">I", digest, offset)[0]
                # Map uint32 to [-1, 1]
                val = (raw / 0xFFFFFFFF) * 2.0 - 1.0
                result.append(val)
            idx += 1

        return result

    async def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns a 384-dim vector."""
        return self._hash_to_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of 384-dim vectors."""
        return [self._hash_to_vector(t) for t in texts]


class LiteLLMEmbeddingClient:
    """Embedding client that proxies to LiteLLM /embeddings endpoint.

    Implements EmbeddingClient protocol. Sends OpenAI-compatible requests
    to the LiteLLM proxy and returns the resulting vectors.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "text-embedding-3-small",
        dim: int = _DIMENSION,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def _request(self, input_data: str | list[str]) -> dict[str, Any]:
        """Send an embedding request to LiteLLM."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "input": input_data,
            "model": self._model,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/v1/embeddings",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def embed(self, text: str) -> list[float]:
        """Embed a single text via LiteLLM."""
        data = await self._request(text)
        return data["data"][0]["embedding"]  # type: ignore[no-any-return]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts via LiteLLM in one request."""
        if not texts:
            return []
        data = await self._request(texts)
        # Sort by index to guarantee order
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]
