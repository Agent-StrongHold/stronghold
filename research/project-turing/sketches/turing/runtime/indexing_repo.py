"""IndexingRepo: Repo that also maintains an EmbeddingIndex on writes.

Wraps a Repo; every insert of an I_DID memory is mirrored into the
EmbeddingIndex so semantic retrieval can find it. Non-I_DID memories
(I_IMAGINED daydreams, I_WAS_TOLD claims) are intentionally not indexed
by default — the self searches its own experience, not its imagined
or hearsay content. Callers that want those can call
`index_memory()` explicitly.

Embeddings are persisted as BLOB in the episodic_memory table so that
restarts only need to embed new memories, not the entire corpus.
"""

from __future__ import annotations

import logging
import struct
import time

from ..repo import Repo
from ..types import EpisodicMemory, SourceKind
from .embedding_index import EmbeddingIndex


logger = logging.getLogger("turing.runtime.indexing_repo")

_VEC_DTYPE = "f"  # 32-bit float
_VEC_SIZE = 4  # bytes per float


def _vec_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}{_VEC_DTYPE}", *vec)


def _bytes_to_vec(data: bytes) -> list[float]:
    n = len(data) // _VEC_SIZE
    return list(struct.unpack(f"{n}{_VEC_DTYPE}", data))


class IndexingRepo(Repo):
    """Repo that also maintains an EmbeddingIndex on writes.

    Wraps a Repo's existing connection; does not open a new one.
    Every insert of an I_DID memory is mirrored into the EmbeddingIndex
    so semantic retrieval can find it. Embeddings are persisted to the
    episodic_memory.embedding BLOB column for fast restart.
    """

    def __init__(self, *, inner: Repo, index: EmbeddingIndex) -> None:
        # Bypass Repo.__init__ to reuse inner's connection — no second DB handle.
        self._path = inner._path
        self._lock = inner._lock
        self._conn = inner._conn
        self._inner = inner
        self._index = index

    def insert(self, memory: EpisodicMemory) -> str:
        memory_id = self._inner.insert(memory)
        if memory.source == SourceKind.I_DID:
            self.index_memory(memory)
        return memory_id

    def index_memory(self, memory: EpisodicMemory) -> None:
        cached = self._read_cached_embedding(memory.memory_id)
        if cached is not None:
            self._index.add_precomputed(
                memory.memory_id,
                cached,
                memory.content,
                meta={
                    "self_id": memory.self_id,
                    "tier": memory.tier.value,
                    "source": memory.source.value,
                    "intent_at_time": memory.intent_at_time,
                    "created_at": memory.created_at.isoformat(),
                },
            )
            return
        self._index.add(
            memory.memory_id,
            memory.content,
            meta={
                "self_id": memory.self_id,
                "tier": memory.tier.value,
                "source": memory.source.value,
                "intent_at_time": memory.intent_at_time,
                "created_at": memory.created_at.isoformat(),
            },
        )
        vec = self._index.get_vector(memory.memory_id)
        if vec is not None:
            self._persist_embedding(memory.memory_id, vec)

    def _read_cached_embedding(self, memory_id: str) -> list[float] | None:
        try:
            row = self._conn.execute(
                "SELECT embedding FROM episodic_memory WHERE memory_id = ? AND embedding IS NOT NULL",
                (memory_id,),
            ).fetchone()
            if row and row[0]:
                return _bytes_to_vec(row[0])
        except Exception:
            pass
        return None

    def _persist_embedding(self, memory_id: str, vec: list[float]) -> None:
        try:
            self._conn.execute(
                "UPDATE episodic_memory SET embedding = ? WHERE memory_id = ?",
                (_vec_to_bytes(vec), memory_id),
            )
            self._conn.commit()
        except Exception:
            logger.debug("failed to persist embedding for %s", memory_id, exc_info=True)

    _REBUILD_BATCH_SIZE = 50
    _REBUILD_PAUSE_SECONDS = 2.0

    def rebuild_index_from_repo(self, self_id: str) -> int:
        count = 0
        for memory in self._inner.find(
            self_id=self_id,
            source=SourceKind.I_DID,
            include_superseded=True,
        ):
            self.index_memory(memory)
            count += 1
            if count % self._REBUILD_BATCH_SIZE == 0:
                logger.info("embedding rebuild progress: %d memories indexed", count)
                time.sleep(self._REBUILD_PAUSE_SECONDS)
        logger.info("rebuilt embedding index with %d entries", count)
        return count
