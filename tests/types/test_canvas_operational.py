"""Coverage tests for the operational `stronghold.types.canvas` module.

Focused on the public surface: enums, dataclasses, to_dict serialisation,
status helpers, error classes, and validators. Kept narrow and fast — no
external deps, no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stronghold.types.canvas import (
    _IMAGE_GEN_ACTIONS,
    BlendMode,
    CanvasArchivedError,
    CanvasError,
    CanvasHasLayersError,
    CanvasNotFoundError,
    CanvasRecord,
    CanvasTier,
    CompositeResult,
    DuplicateZIndexError,
    GenerationJobRecord,
    IncompleteReorderError,
    JobAction,
    JobAlreadyTerminalError,
    JobInProgressError,
    JobNotDoneError,
    JobNotFoundError,
    JobStatus,
    LayerLimitExceededError,
    LayerLockedError,
    LayerNotFoundError,
    LayerRecord,
    LayerType,
    ModelInfo,
    PromptBlockedError,
    RefineNoSourceError,
    TextConfig,
    TextLayerNoGenError,
    UnknownModelError,
    UnsupportedFormatError,
    VariantIndexOutOfRangeError,
    normalise_rotation,
    validate_canvas_dimensions,
)
from stronghold.types.errors import StrongholdError


class TestEnums:
    def test_layer_type_values(self) -> None:
        assert LayerType.BACKGROUND == "background"
        assert LayerType.CHARACTER == "character"
        assert LayerType.OBJECT == "object"
        assert LayerType.TEXT == "text"

    def test_blend_mode_values(self) -> None:
        assert {m.value for m in BlendMode} == {
            "normal",
            "multiply",
            "screen",
            "overlay",
            "darken",
            "lighten",
        }

    def test_job_action_values(self) -> None:
        assert {a.value for a in JobAction} == {
            "generate",
            "refine",
            "reference",
            "composite",
            "text",
        }

    def test_job_status_values(self) -> None:
        assert {s.value for s in JobStatus} == {
            "pending",
            "running",
            "done",
            "failed",
            "cancelled",
        }

    def test_canvas_tier_values(self) -> None:
        assert {t.value for t in CanvasTier} == {"draft", "proof"}

    def test_image_gen_actions_set(self) -> None:
        assert (
            frozenset({JobAction.GENERATE, JobAction.REFINE, JobAction.REFERENCE})
            == _IMAGE_GEN_ACTIONS
        )
        assert JobAction.COMPOSITE not in _IMAGE_GEN_ACTIONS
        assert JobAction.TEXT not in _IMAGE_GEN_ACTIONS


class TestTextConfig:
    def test_defaults(self) -> None:
        tc = TextConfig(content="hello")
        assert tc.content == "hello"
        assert tc.font == "sans-serif"
        assert tc.size == 48
        assert tc.color == "#FFFFFF"
        assert tc.weight == "normal"
        assert tc.alignment == "center"
        assert tc.shadow_color is None
        assert tc.shadow_offset == (2, 2)

    def test_overrides(self) -> None:
        tc = TextConfig(
            content="title",
            font="serif",
            size=72,
            color="#000000",
            weight="bold",
            alignment="left",
            shadow_color="#888",
            shadow_offset=(4, 6),
        )
        assert tc.shadow_color == "#888"
        assert tc.shadow_offset == (4, 6)

    def test_frozen(self) -> None:
        tc = TextConfig(content="x")
        with pytest.raises((AttributeError, Exception)):
            tc.size = 12  # type: ignore[misc]


class TestModelInfo:
    def test_defaults(self) -> None:
        m = ModelInfo(id="m1", display_name="Model One", provider="openai")
        assert m.supports_generate is True
        assert m.supports_refine is False
        assert m.tier_class == "draft"
        assert m.cost_per_image_usd == 0.0
        assert m.is_free is True

    def test_overrides(self) -> None:
        m = ModelInfo(
            id="paid",
            display_name="Paid Model",
            provider="anthropic",
            supports_generate=False,
            supports_refine=True,
            tier_class="proof",
            cost_per_image_usd=0.04,
            is_free=False,
        )
        assert m.supports_refine is True
        assert m.cost_per_image_usd == pytest.approx(0.04)
        assert m.is_free is False


class TestCanvasRecord:
    def test_minimal_construction(self) -> None:
        c = CanvasRecord(id="c1", name="Demo", width=512, height=512)
        assert c.background_color == "#FFFFFF"
        assert c.org_id == ""
        assert c.layer_count == 0
        assert c.archived_at is None
        assert isinstance(c.created_at, datetime)
        assert isinstance(c.updated_at, datetime)

    def test_is_archived_false_by_default(self) -> None:
        c = CanvasRecord(id="c1", name="Demo", width=512, height=512)
        assert c.is_archived() is False

    def test_is_archived_true_when_archived_at_set(self) -> None:
        now = datetime.now(UTC)
        c = CanvasRecord(id="c1", name="Demo", width=512, height=512, archived_at=now)
        assert c.is_archived() is True

    def test_to_dict_round_trip_keys(self) -> None:
        c = CanvasRecord(id="c1", name="Demo", width=512, height=512, org_id="acme")
        d = c.to_dict()
        assert d["id"] == "c1"
        assert d["name"] == "Demo"
        assert d["width"] == 512
        assert d["height"] == 512
        assert d["background_color"] == "#FFFFFF"
        assert d["org_id"] == "acme"
        assert d["layer_count"] == 0
        assert d["archived_at"] is None
        # Timestamps serialised to ISO strings
        datetime.fromisoformat(d["created_at"])
        datetime.fromisoformat(d["updated_at"])

    def test_to_dict_with_archive_serialises_archived_at(self) -> None:
        when = datetime(2026, 1, 1, tzinfo=UTC)
        c = CanvasRecord(id="c1", name="Demo", width=512, height=512, archived_at=when)
        d = c.to_dict()
        assert d["archived_at"] == when.isoformat()


class TestLayerRecord:
    def test_minimal_construction_uses_defaults(self) -> None:
        layer = LayerRecord(id="l1", canvas_id="c1", name="bg")
        assert layer.layer_type == LayerType.BACKGROUND
        assert layer.z_index == 0
        assert layer.x == 0.0
        assert layer.y == 0.0
        assert layer.scale == 1.0
        assert layer.rotation == 0.0
        assert layer.opacity == 1.0
        assert layer.blend_mode == BlendMode.NORMAL
        assert layer.visible is True
        assert layer.locked is False
        assert layer.image_path is None
        assert layer.prompt is None
        assert layer.negative_prompt is None
        assert layer.model_id is None
        assert layer.tier == CanvasTier.DRAFT
        assert layer.generation_seed is None
        assert layer.text_config is None

    def test_to_dict_without_text_config(self) -> None:
        layer = LayerRecord(id="l1", canvas_id="c1", name="bg")
        d = layer.to_dict()
        assert d["text_config"] is None
        assert d["layer_type"] == "background"
        assert d["blend_mode"] == "normal"
        assert d["tier"] == "draft"

    def test_to_dict_with_text_config_serialises_nested(self) -> None:
        tc = TextConfig(content="title", shadow_offset=(3, 5))
        layer = LayerRecord(
            id="l1",
            canvas_id="c1",
            name="title-layer",
            layer_type=LayerType.TEXT,
            text_config=tc,
        )
        d = layer.to_dict()
        assert d["layer_type"] == "text"
        assert d["text_config"] == {
            "content": "title",
            "font": "sans-serif",
            "size": 48,
            "color": "#FFFFFF",
            "weight": "normal",
            "alignment": "center",
            "shadow_color": None,
            "shadow_offset": [3, 5],
        }


class TestGenerationJobRecord:
    def test_defaults(self) -> None:
        j = GenerationJobRecord(id="j1", layer_id="l1", canvas_id="c1")
        assert j.action == JobAction.GENERATE
        assert j.status == JobStatus.PENDING
        assert j.model_id == ""
        assert j.prompt == ""
        assert j.params == {}
        assert j.result_paths == []
        assert j.selected_index is None
        assert j.error_message is None
        assert j.started_at is None
        assert j.completed_at is None

    @pytest.mark.parametrize(
        ("status", "terminal"),
        [
            (JobStatus.PENDING, False),
            (JobStatus.RUNNING, False),
            (JobStatus.DONE, True),
            (JobStatus.FAILED, True),
            (JobStatus.CANCELLED, True),
        ],
    )
    def test_is_terminal_status(self, status: JobStatus, terminal: bool) -> None:
        j = GenerationJobRecord(id="j", layer_id="l", canvas_id="c", status=status)
        assert j.is_terminal() is terminal

    @pytest.mark.parametrize(
        ("status", "active"),
        [
            (JobStatus.PENDING, True),
            (JobStatus.RUNNING, True),
            (JobStatus.DONE, False),
            (JobStatus.FAILED, False),
            (JobStatus.CANCELLED, False),
        ],
    )
    def test_is_active_status(self, status: JobStatus, active: bool) -> None:
        j = GenerationJobRecord(id="j", layer_id="l", canvas_id="c", status=status)
        assert j.is_active() is active

    def test_to_dict_with_timestamps(self) -> None:
        started = datetime(2026, 5, 1, tzinfo=UTC)
        completed = datetime(2026, 5, 1, 0, 5, tzinfo=UTC)
        j = GenerationJobRecord(
            id="j1",
            layer_id="l1",
            canvas_id="c1",
            status=JobStatus.DONE,
            started_at=started,
            completed_at=completed,
            result_paths=["p1", "p2"],
            selected_index=0,
            error_message=None,
        )
        d = j.to_dict()
        assert d["status"] == "done"
        assert d["started_at"] == started.isoformat()
        assert d["completed_at"] == completed.isoformat()
        assert d["result_paths"] == ["p1", "p2"]
        assert d["selected_index"] == 0

    def test_to_dict_unstarted_job_serialises_none(self) -> None:
        j = GenerationJobRecord(id="j1", layer_id="l1", canvas_id="c1")
        d = j.to_dict()
        assert d["started_at"] is None
        assert d["completed_at"] is None


class TestCompositeResult:
    def test_construction_and_defaults(self) -> None:
        r = CompositeResult(
            canvas_id="c1",
            image_bytes=b"PNG-bytes",
            width=512,
            height=512,
        )
        assert r.layer_snapshot == []
        assert isinstance(r.created_at, datetime)
        assert r.image_bytes == b"PNG-bytes"


class TestErrorHierarchy:
    @pytest.mark.parametrize(
        ("cls", "expected_code"),
        [
            (CanvasError, "CANVAS_ERROR"),
            (CanvasNotFoundError, "CANVAS_NOT_FOUND"),
            (CanvasArchivedError, "CANVAS_ARCHIVED"),
            (CanvasHasLayersError, "CANVAS_HAS_LAYERS"),
            (LayerNotFoundError, "LAYER_NOT_FOUND"),
            (LayerLimitExceededError, "LAYER_LIMIT_EXCEEDED"),
            (LayerLockedError, "LAYER_LOCKED"),
            (DuplicateZIndexError, "DUPLICATE_Z_INDEX"),
            (IncompleteReorderError, "INCOMPLETE_REORDER"),
            (JobNotFoundError, "JOB_NOT_FOUND"),
            (JobInProgressError, "JOB_IN_PROGRESS"),
            (JobNotDoneError, "JOB_NOT_DONE"),
            (JobAlreadyTerminalError, "JOB_ALREADY_TERMINAL"),
            (TextLayerNoGenError, "TEXT_LAYER_NO_GEN"),
            (UnknownModelError, "UNKNOWN_MODEL"),
            (PromptBlockedError, "PROMPT_BLOCKED"),
            (RefineNoSourceError, "REFINE_NO_SOURCE"),
            (VariantIndexOutOfRangeError, "VARIANT_INDEX_OUT_OF_RANGE"),
            (UnsupportedFormatError, "UNSUPPORTED_FORMAT"),
        ],
    )
    def test_error_codes(self, cls: type[CanvasError], expected_code: str) -> None:
        err = cls("boom")
        assert err.code == expected_code
        assert isinstance(err, CanvasError)
        assert isinstance(err, StrongholdError)
        assert "boom" in str(err)


class TestValidateCanvasDimensions:
    @pytest.mark.parametrize(
        ("w", "h"),
        [(64, 64), (512, 512), (1024, 768), (8192, 8192)],
    )
    def test_valid_dimensions_pass(self, w: int, h: int) -> None:
        validate_canvas_dimensions(w, h)  # no exception

    @pytest.mark.parametrize(
        "bad",
        [0, 8, 32, 63, 8193, 9000, -64],
    )
    def test_out_of_range_raises(self, bad: int) -> None:
        with pytest.raises(ValueError, match="must be between"):
            validate_canvas_dimensions(bad, 512)
        with pytest.raises(ValueError, match="must be between"):
            validate_canvas_dimensions(512, bad)

    @pytest.mark.parametrize("bad", [65, 100, 513, 1023])
    def test_not_divisible_by_8_raises(self, bad: int) -> None:
        with pytest.raises(ValueError, match="divisible by 8"):
            validate_canvas_dimensions(bad, 512)
        with pytest.raises(ValueError, match="divisible by 8"):
            validate_canvas_dimensions(512, bad)


class TestNormaliseRotation:
    @pytest.mark.parametrize(
        ("inp", "expected"),
        [
            (0.0, 0.0),
            (45.0, 45.0),
            (359.999, 359.999),
            (360.0, 0.0),
            (720.0, 0.0),
            (450.0, 90.0),
            (-90.0, 270.0),
            (-360.0, 0.0),
        ],
    )
    def test_wraps_into_zero_to_360(self, inp: float, expected: float) -> None:
        assert normalise_rotation(inp) == pytest.approx(expected)
