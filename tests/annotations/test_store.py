"""Tests for InMemoryAnnotationStore — annotation CRUD, org scoping, validation."""

from __future__ import annotations

import pytest

from stronghold.annotations.store import InMemoryAnnotationStore
from stronghold.types.annotation import Annotation


class TestAnnotationCreate:
    async def test_create_annotation_assigns_id(self) -> None:
        """Creating an annotation should assign a UUID id."""
        store = InMemoryAnnotationStore()
        ann = Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["good"])
        result = await store.annotate(ann)
        assert result.id != ""
        assert result.session_id == "s1"
        assert result.user_id == "u1"
        assert result.org_id == "org-a"
        assert result.tags == ["good"]

    async def test_create_annotation_with_rating(self) -> None:
        """Rating 1-5 should be accepted."""
        store = InMemoryAnnotationStore()
        ann = Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=4)
        result = await store.annotate(ann)
        assert result.rating == 4

    async def test_create_annotation_with_note(self) -> None:
        """Free-text notes should be stored."""
        store = InMemoryAnnotationStore()
        ann = Annotation(
            session_id="s1", user_id="u1", org_id="org-a", note="Needs review"
        )
        result = await store.annotate(ann)
        assert result.note == "Needs review"


class TestAnnotationRatingValidation:
    async def test_rating_zero_rejected(self) -> None:
        """Rating 0 is out of range (must be 1-5 or None)."""
        store = InMemoryAnnotationStore()
        ann = Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=0)
        with pytest.raises(ValueError, match="[Rr]ating"):
            await store.annotate(ann)

    async def test_rating_six_rejected(self) -> None:
        """Rating 6 is out of range (must be 1-5 or None)."""
        store = InMemoryAnnotationStore()
        ann = Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=6)
        with pytest.raises(ValueError, match="[Rr]ating"):
            await store.annotate(ann)

    async def test_rating_negative_rejected(self) -> None:
        """Negative ratings are rejected."""
        store = InMemoryAnnotationStore()
        ann = Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=-1)
        with pytest.raises(ValueError, match="[Rr]ating"):
            await store.annotate(ann)

    async def test_rating_none_accepted(self) -> None:
        """None rating means 'not rated' — should be accepted."""
        store = InMemoryAnnotationStore()
        ann = Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=None)
        result = await store.annotate(ann)
        assert result.rating is None


class TestAnnotationGetBySession:
    async def test_get_annotations_for_session(self) -> None:
        """Should return all annotations for a given session in the org."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["good"])
        )
        await store.annotate(
            Annotation(session_id="s1", user_id="u2", org_id="org-a", tags=["bad"])
        )
        await store.annotate(
            Annotation(session_id="s2", user_id="u1", org_id="org-a", tags=["ok"])
        )

        results = await store.get_annotations("s1", org_id="org-a")
        assert len(results) == 2
        tags = [t for a in results for t in a.tags]
        assert "good" in tags
        assert "bad" in tags

    async def test_get_annotations_empty_session(self) -> None:
        """No annotations for a session returns empty list."""
        store = InMemoryAnnotationStore()
        results = await store.get_annotations("nonexistent", org_id="org-a")
        assert results == []


class TestAnnotationListByTag:
    async def test_list_by_tag_filters_correctly(self) -> None:
        """Only annotations with the specified tag should be returned."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["compliance"])
        )
        await store.annotate(
            Annotation(session_id="s2", user_id="u1", org_id="org-a", tags=["training"])
        )
        await store.annotate(
            Annotation(
                session_id="s3", user_id="u1", org_id="org-a", tags=["compliance", "training"]
            )
        )

        results = await store.list_by_tag("compliance", org_id="org-a")
        assert len(results) == 2
        for ann in results:
            assert "compliance" in ann.tags

    async def test_list_by_tag_respects_limit(self) -> None:
        """Limit parameter constrains result count."""
        store = InMemoryAnnotationStore()
        for i in range(5):
            await store.annotate(
                Annotation(
                    session_id=f"s{i}", user_id="u1", org_id="org-a", tags=["review"]
                )
            )
        results = await store.list_by_tag("review", org_id="org-a", limit=3)
        assert len(results) == 3


class TestAnnotationListByRating:
    async def test_list_by_rating_filters_correctly(self) -> None:
        """Only annotations with rating <= max_rating should be returned."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=1)
        )
        await store.annotate(
            Annotation(session_id="s2", user_id="u1", org_id="org-a", rating=3)
        )
        await store.annotate(
            Annotation(session_id="s3", user_id="u1", org_id="org-a", rating=5)
        )

        results = await store.list_by_rating(3, org_id="org-a")
        assert len(results) == 2
        for ann in results:
            assert ann.rating is not None
            assert ann.rating <= 3

    async def test_list_by_rating_excludes_unrated(self) -> None:
        """Annotations without a rating should not appear in rating queries."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=2)
        )
        await store.annotate(
            Annotation(session_id="s2", user_id="u1", org_id="org-a", rating=None)
        )
        results = await store.list_by_rating(5, org_id="org-a")
        assert len(results) == 1

    async def test_list_by_rating_respects_limit(self) -> None:
        """Limit parameter constrains result count."""
        store = InMemoryAnnotationStore()
        for i in range(5):
            await store.annotate(
                Annotation(
                    session_id=f"s{i}", user_id="u1", org_id="org-a", rating=1
                )
            )
        results = await store.list_by_rating(5, org_id="org-a", limit=2)
        assert len(results) == 2


class TestAnnotationDelete:
    async def test_delete_existing_annotation(self) -> None:
        """Deleting an existing annotation returns True."""
        store = InMemoryAnnotationStore()
        ann = await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["test"])
        )
        result = await store.delete_annotation(ann.id, org_id="org-a")
        assert result is True

        # Verify it's gone
        remaining = await store.get_annotations("s1", org_id="org-a")
        assert len(remaining) == 0

    async def test_delete_nonexistent_annotation(self) -> None:
        """Deleting a nonexistent annotation returns False."""
        store = InMemoryAnnotationStore()
        result = await store.delete_annotation("no-such-id", org_id="org-a")
        assert result is False


class TestAnnotationOrgScoping:
    async def test_cannot_see_other_org_annotations(self) -> None:
        """Annotations from org-a should not be visible to org-b."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["secret"])
        )
        await store.annotate(
            Annotation(session_id="s1", user_id="u2", org_id="org-b", tags=["public"])
        )

        results_a = await store.get_annotations("s1", org_id="org-a")
        results_b = await store.get_annotations("s1", org_id="org-b")
        assert len(results_a) == 1
        assert results_a[0].tags == ["secret"]
        assert len(results_b) == 1
        assert results_b[0].tags == ["public"]

    async def test_list_by_tag_org_scoped(self) -> None:
        """Tag queries should only return annotations from the queried org."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["flagged"])
        )
        await store.annotate(
            Annotation(session_id="s2", user_id="u2", org_id="org-b", tags=["flagged"])
        )

        results = await store.list_by_tag("flagged", org_id="org-a")
        assert len(results) == 1
        assert results[0].org_id == "org-a"

    async def test_list_by_rating_org_scoped(self) -> None:
        """Rating queries should only return annotations from the queried org."""
        store = InMemoryAnnotationStore()
        await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", rating=1)
        )
        await store.annotate(
            Annotation(session_id="s2", user_id="u2", org_id="org-b", rating=1)
        )

        results = await store.list_by_rating(5, org_id="org-a")
        assert len(results) == 1
        assert results[0].org_id == "org-a"

    async def test_delete_cannot_cross_org_boundary(self) -> None:
        """Cannot delete annotations belonging to another org."""
        store = InMemoryAnnotationStore()
        ann = await store.annotate(
            Annotation(session_id="s1", user_id="u1", org_id="org-a", tags=["mine"])
        )

        # org-b tries to delete org-a's annotation
        result = await store.delete_annotation(ann.id, org_id="org-b")
        assert result is False

        # Still exists for org-a
        remaining = await store.get_annotations("s1", org_id="org-a")
        assert len(remaining) == 1
