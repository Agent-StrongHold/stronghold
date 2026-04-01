"""In-memory annotation store for conversation tagging, rating, and notes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.annotation import Annotation


class InMemoryAnnotationStore:
    """In-memory implementation of AnnotationStore protocol.

    All queries are org-scoped for tenant isolation.
    """

    def __init__(self) -> None:
        self._annotations: dict[str, Annotation] = {}

    async def annotate(self, annotation: Annotation) -> Annotation:
        """Create an annotation. Validates rating and assigns ID."""
        if annotation.rating is not None and not (1 <= annotation.rating <= 5):
            msg = "Rating must be between 1 and 5, or None"
            raise ValueError(msg)

        annotation.id = str(uuid.uuid4())
        annotation.created_at = datetime.now(UTC)
        self._annotations[annotation.id] = annotation
        return annotation

    async def get_annotations(self, session_id: str, *, org_id: str) -> list[Annotation]:
        """Get all annotations for a session within an org."""
        return [
            a
            for a in self._annotations.values()
            if a.session_id == session_id and a.org_id == org_id
        ]

    async def list_by_tag(self, tag: str, *, org_id: str, limit: int = 20) -> list[Annotation]:
        """List annotations matching a tag within an org."""
        results = [a for a in self._annotations.values() if a.org_id == org_id and tag in a.tags]
        return results[:limit]

    async def list_by_rating(
        self, max_rating: int, *, org_id: str, limit: int = 20
    ) -> list[Annotation]:
        """List annotations with rating <= max_rating within an org."""
        results = [
            a
            for a in self._annotations.values()
            if a.org_id == org_id and a.rating is not None and a.rating <= max_rating
        ]
        return results[:limit]

    async def delete_annotation(self, annotation_id: str, *, org_id: str) -> bool:
        """Delete an annotation by ID within an org. Returns True if found and deleted."""
        ann = self._annotations.get(annotation_id)
        if ann is None or ann.org_id != org_id:
            return False
        del self._annotations[annotation_id]
        return True
