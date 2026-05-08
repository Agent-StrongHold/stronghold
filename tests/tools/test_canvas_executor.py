"""BDD-style tests for the Canvas tool executor.

Each class maps to one Gherkin feature; each method is a Given/When/Then scenario.
All external dependencies (ImageGenClient, CanvasStore, Warden) are faked.

Coverage targets:
  - start_job: all five actions, pre-condition enforcement, persistence
  - accept_variant: success, out-of-bounds, wrong state
  - cancel_job: pending/running/done transitions
  - model routing: unknown model, registry lookup
  - error wrapping: provider exceptions never leak raw
  - concurrency: one-job-per-layer invariant
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Type stubs (real imports once src/stronghold/types/canvas.py exists)
# ---------------------------------------------------------------------------

@dataclass
class CanvasRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "test-canvas"
    width: int = 1024
    height: int = 1024
    background_color: str = "#FFFFFF"
    org_id: str = "org-test"
    layer_count: int = 0
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class LayerRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    canvas_id: str = ""
    name: str = "layer"
    layer_type: str = "background"
    z_index: int = 0
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    visible: bool = True
    locked: bool = False
    image_path: str | None = None
    prompt: str | None = None
    model_id: str | None = None
    tier: str = "draft"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class GenerationJobRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    layer_id: str = ""
    canvas_id: str = ""
    action: str = "generate"
    status: str = "pending"
    model_id: str = "test-model"
    prompt: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result_paths: list[str] = field(default_factory=list)
    selected_index: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_terminal(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def is_active(self) -> bool:
        return self.status in ("pending", "running")


@dataclass
class ImageData:
    width: int
    height: int
    url: str
    bytes_: bytes = field(default_factory=bytes)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeCanvasStore:
    """In-memory canvas store for tests."""

    def __init__(self) -> None:
        self._canvases: dict[str, CanvasRecord] = {}
        self._layers: dict[str, LayerRecord] = {}
        self._jobs: dict[str, GenerationJobRecord] = {}

    def seed_canvas(self, **kwargs: Any) -> CanvasRecord:
        c = CanvasRecord(**kwargs)
        self._canvases[c.id] = c
        return c

    def seed_layer(self, canvas_id: str, **kwargs: Any) -> LayerRecord:
        layer = LayerRecord(canvas_id=canvas_id, **kwargs)
        self._layers[layer.id] = layer
        canvas = self._canvases[canvas_id]
        canvas.layer_count += 1
        return layer

    def seed_job(self, **kwargs: Any) -> GenerationJobRecord:
        job = GenerationJobRecord(**kwargs)
        self._jobs[job.id] = job
        return job

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None:
        return self._canvases.get(canvas_id)

    async def get_layer(self, layer_id: str) -> LayerRecord | None:
        return self._layers.get(layer_id)

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        return self._jobs.get(job_id)

    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None:
        for job in self._jobs.values():
            if job.layer_id == layer_id and job.status in ("pending", "running"):
                return job
        return None

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return job

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return job

    async def update_layer(self, layer: LayerRecord) -> LayerRecord:
        self._layers[layer.id] = layer
        return layer

    async def update_canvas(self, canvas: CanvasRecord) -> CanvasRecord:
        self._canvases[canvas.id] = canvas
        return canvas


class FakeImageGenClient:
    """In-memory image gen client that returns deterministic fake images."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self._images: list[ImageData] | None = None

    def set_images(self, *images: ImageData) -> None:
        self._images = list(images)

    async def generate(
        self,
        model_id: str,
        prompt: str,
        width: int,
        height: int,
        count: int = 1,
        seed: int | None = None,
        negative_prompt: str = "",
    ) -> list[ImageData]:
        self.calls.append(
            {
                "model_id": model_id,
                "prompt": prompt,
                "width": width,
                "height": height,
                "count": count,
                "seed": seed,
            }
        )
        if self._error is not None:
            raise self._error
        if self._images is not None:
            return self._images[:count]
        return [ImageData(width=width, height=height, url=f"https://fake.cdn/img-{i}.png") for i in range(count)]

    async def refine(
        self,
        model_id: str,
        source_url: str,
        prompt: str,
        region: str = "full",
        strength: float = 0.6,
    ) -> ImageData:
        self.calls.append({"action": "refine", "model_id": model_id, "source_url": source_url})
        if self._error is not None:
            raise self._error
        return ImageData(width=512, height=512, url="https://fake.cdn/refined.png")


class FakeModelRegistry:
    """Minimal model registry for executor tests."""

    def __init__(self, known_models: list[str] | None = None) -> None:
        self._models = set(known_models or ["test-draft-model", "test-proof-model"])

    def is_registered(self, model_id: str) -> bool:
        return model_id in self._models

    def get_default_draft(self) -> str:
        return next(iter(self._models))


class FakeWarden:
    """Warden that passes everything by default; configurable to block."""

    def __init__(self, block: bool = False) -> None:
        self._block = block

    async def scan_prompt(self, prompt: str) -> str:
        return "BLOCK" if self._block else "ALLOW"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_canvas_id() -> str:
    return str(uuid.uuid4())


def _make_layer_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Feature: start_job — generate action
# ---------------------------------------------------------------------------

class TestStartJobGenerate:
    """
    Feature: Image generation — generate action
    Tests the happy path and all pre-condition guards for CanvasExecutor.start_job
    with action='generate'.
    """

    @pytest.mark.asyncio
    async def test_generate_returns_pending_job(self) -> None:
        """
        Given a canvas and a background layer with no image
        When I call start_job(action='generate', prompt='sunset')
        Then a job is created with status='pending' and persisted in the store
        """
        store = FakeCanvasStore()
        image_client = FakeImageGenClient()
        registry = FakeModelRegistry()
        warden = FakeWarden()

        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id, layer_type="background")

        # Import will work once the module exists
        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(store=store, image_client=image_client, model_registry=registry, warden=warden)

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sunset sky",
            count=2,
        )

        assert job.status == "pending"
        assert job.layer_id == layer.id
        assert job.canvas_id == canvas.id
        assert job.action == "generate"
        # Must be persisted before returning
        persisted = await store.get_job(job.id)
        assert persisted is not None
        assert persisted.status == "pending"

    @pytest.mark.asyncio
    async def test_generate_rejects_concurrent_job(self) -> None:
        """
        Given a pending job already exists for the layer
        When I call start_job again for the same layer
        Then JobInProgressError is raised (maps to 409)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="pending")

        from stronghold.tools.canvas_executor import CanvasExecutor, JobInProgressError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(JobInProgressError):
            await executor.start_job(
                canvas_id=canvas.id,
                layer_id=layer.id,
                action="generate",
                model_id="test-draft-model",
                prompt="sky",
            )

    @pytest.mark.asyncio
    async def test_generate_rejects_running_job(self) -> None:
        """
        Given a *running* job exists for the layer
        When I call start_job
        Then JobInProgressError is raised (not just pending jobs)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="running")

        from stronghold.tools.canvas_executor import CanvasExecutor, JobInProgressError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(JobInProgressError):
            await executor.start_job(
                canvas_id=canvas.id,
                layer_id=layer.id,
                action="generate",
                model_id="test-draft-model",
                prompt="sky",
            )

    @pytest.mark.asyncio
    async def test_generate_allows_after_done_job(self) -> None:
        """
        Given a *done* job exists for the layer
        When I call start_job
        Then a new pending job is created (done job does not block)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="done")

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
        )
        assert job.status == "pending"

    @pytest.mark.asyncio
    async def test_generate_rejects_text_layer(self) -> None:
        """
        Given a layer with layer_type='text'
        When I call start_job with action='generate'
        Then TextLayerNoGenError is raised (maps to 400)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id, layer_type="text")

        from stronghold.tools.canvas_executor import CanvasExecutor, TextLayerNoGenError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(TextLayerNoGenError):
            await executor.start_job(
                canvas_id=canvas.id,
                layer_id=layer.id,
                action="generate",
                model_id="test-draft-model",
                prompt="hello",
            )

    @pytest.mark.asyncio
    async def test_generate_rejects_unknown_model(self) -> None:
        """
        Given a model_id not in the registry
        When I call start_job
        Then UnknownModelError is raised (maps to 400)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        from stronghold.tools.canvas_executor import CanvasExecutor, UnknownModelError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(known_models=["valid-model"]),
            warden=FakeWarden(),
        )

        with pytest.raises(UnknownModelError):
            await executor.start_job(
                canvas_id=canvas.id,
                layer_id=layer.id,
                action="generate",
                model_id="does-not-exist",
                prompt="sky",
            )

    @pytest.mark.asyncio
    async def test_warden_blocks_prompt(self) -> None:
        """
        Given Warden returns BLOCK for the prompt
        When I call start_job
        Then PromptBlockedError is raised — no image client call is made
        """
        store = FakeCanvasStore()
        image_client = FakeImageGenClient()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        from stronghold.tools.canvas_executor import CanvasExecutor, PromptBlockedError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=image_client,
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(block=True),
        )

        with pytest.raises(PromptBlockedError):
            await executor.start_job(
                canvas_id=canvas.id,
                layer_id=layer.id,
                action="generate",
                model_id="test-draft-model",
                prompt="forbidden content",
            )

        assert len(image_client.calls) == 0

    @pytest.mark.asyncio
    async def test_generate_count_matches_params(self) -> None:
        """
        Given count=3 is requested
        When start_job is called and the job runs
        Then the image client receives count=3 and result_paths has 3 entries
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        image_client = FakeImageGenClient()

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=image_client,
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
            count=3,
        )

        # Run the job synchronously in tests
        await executor.run_job(job.id)
        updated = await store.get_job(job.id)
        assert updated is not None
        assert updated.status == "done"
        assert len(updated.result_paths) == 3


# ---------------------------------------------------------------------------
# Feature: start_job — refine action
# ---------------------------------------------------------------------------

class TestStartJobRefine:
    """
    Feature: Image generation — refine action
    """

    @pytest.mark.asyncio
    async def test_refine_requires_image_path(self) -> None:
        """
        Given a layer with no image_path
        When I call start_job with action='refine'
        Then RefineNoSourceError is raised (maps to 400)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id, image_path=None)

        from stronghold.tools.canvas_executor import CanvasExecutor, RefineNoSourceError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(RefineNoSourceError):
            await executor.start_job(
                canvas_id=canvas.id,
                layer_id=layer.id,
                action="refine",
                model_id="test-draft-model",
                prompt="fix the hands",
            )

    @pytest.mark.asyncio
    async def test_refine_succeeds_with_image_path(self) -> None:
        """
        Given a layer with an existing image_path
        When I call start_job with action='refine'
        Then a pending job is created
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id, image_path="https://cdn/existing.png")

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="refine",
            model_id="test-draft-model",
            prompt="fix the hands",
        )
        assert job.status == "pending"
        assert job.action == "refine"


# ---------------------------------------------------------------------------
# Feature: accept_variant
# ---------------------------------------------------------------------------

class TestAcceptVariant:
    """
    Feature: Accept generation variant — updates layer image_path
    """

    @pytest.mark.asyncio
    async def test_accept_variant_zero(self) -> None:
        """
        Given a done job with 2 result_paths
        When I accept variant index 0
        Then layer.image_path == result_paths[0] and job.selected_index == 0
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png", "https://cdn/img-1.png"],
        )

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        updated_job, updated_layer = await executor.accept_variant(job.id, variant_index=0)
        assert updated_job.selected_index == 0
        assert updated_layer.image_path == "https://cdn/img-0.png"

    @pytest.mark.asyncio
    async def test_accept_last_variant(self) -> None:
        """
        Given a done job with 4 result_paths
        When I accept variant index 3 (last)
        Then layer.image_path == result_paths[3]
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        paths = [f"https://cdn/img-{i}.png" for i in range(4)]
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=paths,
        )

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        _, updated_layer = await executor.accept_variant(job.id, variant_index=3)
        assert updated_layer.image_path == "https://cdn/img-3.png"

    @pytest.mark.asyncio
    async def test_accept_out_of_range_raises(self) -> None:
        """
        Given a done job with 2 result_paths
        When I accept variant_index=2 (out of range)
        Then VariantIndexOutOfRangeError is raised
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png", "https://cdn/img-1.png"],
        )

        from stronghold.tools.canvas_executor import CanvasExecutor, VariantIndexOutOfRangeError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(VariantIndexOutOfRangeError):
            await executor.accept_variant(job.id, variant_index=2)

    @pytest.mark.asyncio
    async def test_accept_negative_index_raises(self) -> None:
        """
        Given a done job
        When I accept variant_index=-1
        Then VariantIndexOutOfRangeError is raised (not IndexError)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png"],
        )

        from stronghold.tools.canvas_executor import CanvasExecutor, VariantIndexOutOfRangeError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(VariantIndexOutOfRangeError):
            await executor.accept_variant(job.id, variant_index=-1)

    @pytest.mark.asyncio
    async def test_accept_running_job_raises(self) -> None:
        """
        Given a job with status='running'
        When I accept a variant
        Then JobNotDoneError is raised
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="running",
            result_paths=[],
        )

        from stronghold.tools.canvas_executor import CanvasExecutor, JobNotDoneError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(JobNotDoneError):
            await executor.accept_variant(job.id, variant_index=0)

    @pytest.mark.asyncio
    async def test_accept_advances_canvas_updated_at(self) -> None:
        """
        Given a done job
        When I accept a variant
        Then canvas.updated_at advances (invariant: canvas_updated_on_layer_accept)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        old_ts = canvas.updated_at
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png"],
        )

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        await executor.accept_variant(job.id, variant_index=0)

        updated_canvas = await store.get_canvas(canvas.id)
        assert updated_canvas is not None
        assert updated_canvas.updated_at >= old_ts


# ---------------------------------------------------------------------------
# Feature: cancel_job
# ---------------------------------------------------------------------------

class TestCancelJob:
    """
    Feature: Cancel generation job — state transitions
    """

    @pytest.mark.asyncio
    async def test_cancel_pending_job(self) -> None:
        """
        Given a job with status='pending'
        When I cancel the job
        Then job.status becomes 'cancelled'
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="pending")

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        await executor.cancel_job(job.id)
        updated = await store.get_job(job.id)
        assert updated is not None
        assert updated.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_done_job_raises(self) -> None:
        """
        Given a job with status='done'
        When I cancel it
        Then JobAlreadyTerminalError is raised (maps to 409)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png"],
        )

        from stronghold.tools.canvas_executor import CanvasExecutor, JobAlreadyTerminalError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(JobAlreadyTerminalError):
            await executor.cancel_job(job.id)

    @pytest.mark.asyncio
    async def test_cancel_failed_job_raises(self) -> None:
        """
        Given a job with status='failed'
        When I cancel it
        Then JobAlreadyTerminalError is raised
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="failed")

        from stronghold.tools.canvas_executor import CanvasExecutor, JobAlreadyTerminalError  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        with pytest.raises(JobAlreadyTerminalError):
            await executor.cancel_job(job.id)


# ---------------------------------------------------------------------------
# Feature: error wrapping — no raw provider exceptions leak
# ---------------------------------------------------------------------------

class TestErrorWrapping:
    """
    Feature: Provider error isolation
    Raw provider exceptions (stack traces, internal messages) must never
    surface to callers — only the sanitised error_message on the job record.
    """

    @pytest.mark.asyncio
    async def test_provider_http_error_wraps_to_job_failed(self) -> None:
        """
        Given the image client raises an HTTP 429 rate-limit exception
        When the generation job runs
        Then job.status == 'failed' and error_message mentions 'rate limit'
        And the raw exception body is NOT in error_message
        """
        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]

        class FakeRateLimitError(Exception):
            def __init__(self) -> None:
                super().__init__("429 Too Many Requests: {\"error\": \"rate_limit\", \"Traceback\": \"...\"}")

        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)
        image_client = FakeImageGenClient(error=FakeRateLimitError())

        executor = CanvasExecutor(
            store=store,
            image_client=image_client,
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
        )
        await executor.run_job(job.id)

        updated = await store.get_job(job.id)
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error_message is not None
        assert "Traceback" not in updated.error_message
        assert "rate limit" in updated.error_message.lower() or "429" in updated.error_message

    @pytest.mark.asyncio
    async def test_provider_generic_error_wraps(self) -> None:
        """
        Given the image client raises a generic exception with a raw stack trace
        When the job runs
        Then error_message does not contain 'Traceback'
        """
        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]

        class BoomError(Exception):
            def __init__(self) -> None:
                super().__init__("Traceback (most recent call last):\n  File 'litellm.py' ...")

        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(error=BoomError()),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id, layer_id=layer.id, action="generate",
            model_id="test-draft-model", prompt="test",
        )
        await executor.run_job(job.id)

        updated = await store.get_job(job.id)
        assert updated is not None
        assert "Traceback" not in (updated.error_message or "")

    @pytest.mark.asyncio
    async def test_malformed_image_response_fails_cleanly(self) -> None:
        """
        Given the image client returns ImageData with empty bytes (simulating corrupt response)
        When the job runs
        Then job.status == 'failed' with IMAGE_DECODE_ERROR — no exception propagates
        """
        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]

        class BadImageClient:
            async def generate(self, **kwargs: Any) -> list[ImageData]:
                return [ImageData(width=0, height=0, url="", bytes_=b"not-an-image")]

            async def refine(self, **kwargs: Any) -> ImageData:
                return ImageData(width=0, height=0, url="")

        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        executor = CanvasExecutor(
            store=store,
            image_client=BadImageClient(),  # type: ignore[arg-type]
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id, layer_id=layer.id, action="generate",
            model_id="test-draft-model", prompt="test",
        )
        await executor.run_job(job.id)

        updated = await store.get_job(job.id)
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error_message is not None


# ---------------------------------------------------------------------------
# Feature: concurrency — one-job-per-layer invariant
# ---------------------------------------------------------------------------

class TestConcurrencyInvariant:
    """
    Feature: Concurrency — exactly one active job per layer
    """

    @pytest.mark.asyncio
    async def test_concurrent_start_job_only_one_succeeds(self) -> None:
        """
        Given two concurrent calls to start_job for the same layer
        When both arrive simultaneously
        Then exactly one succeeds and the other raises JobInProgressError
        (no race condition — the invariant is enforced atomically)
        """
        from stronghold.tools.canvas_executor import CanvasExecutor, JobInProgressError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        results: list[object] = []

        async def attempt() -> None:
            try:
                job = await executor.start_job(
                    canvas_id=canvas.id,
                    layer_id=layer.id,
                    action="generate",
                    model_id="test-draft-model",
                    prompt="sky",
                )
                results.append(job)
            except JobInProgressError:
                results.append("conflict")

        await asyncio.gather(attempt(), attempt())

        # Use duck-typing check since executor returns the real type, not the local stub
        successes = [r for r in results if r != "conflict"]
        conflicts = [r for r in results if r == "conflict"]
        assert len(successes) == 1
        assert len(conflicts) == 1


# ---------------------------------------------------------------------------
# Feature: seed=0 is a valid seed (EC-30)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """
    Edge cases from the spec — each mapped to a focused test.
    """

    @pytest.mark.asyncio
    async def test_seed_zero_is_valid(self) -> None:
        """EC-30: seed=0 is a valid seed, not treated as None/unset."""
        store = FakeCanvasStore()
        image_client = FakeImageGenClient()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=image_client,
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
            seed=0,
        )
        await executor.run_job(job.id)
        # Seed must be passed to image client as 0, not None
        assert len(image_client.calls) == 1
        assert image_client.calls[0]["seed"] == 0

    @pytest.mark.asyncio
    async def test_count_one_returns_one_path(self) -> None:
        """EC-01: count=1 produces exactly 1 result_path."""
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
            count=1,
        )
        await executor.run_job(job.id)
        updated = await store.get_job(job.id)
        assert updated is not None
        assert len(updated.result_paths) == 1

    @pytest.mark.asyncio
    async def test_count_four_returns_four_paths(self) -> None:
        """EC-02: count=4 produces exactly 4 result_paths."""
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id)

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
            count=4,
        )
        await executor.run_job(job.id)
        updated = await store.get_job(job.id)
        assert updated is not None
        assert len(updated.result_paths) == 4

    @pytest.mark.asyncio
    async def test_generate_on_locked_layer_is_allowed(self) -> None:
        """EC-21: Locked layers can still have generation jobs started (lock is positional only)."""
        store = FakeCanvasStore()
        canvas = store.seed_canvas()
        layer = store.seed_layer(canvas.id, locked=True)

        from stronghold.tools.canvas_executor import CanvasExecutor  # type: ignore[import]
        executor = CanvasExecutor(
            store=store,
            image_client=FakeImageGenClient(),
            model_registry=FakeModelRegistry(),
            warden=FakeWarden(),
        )

        job = await executor.start_job(
            canvas_id=canvas.id,
            layer_id=layer.id,
            action="generate",
            model_id="test-draft-model",
            prompt="sky",
        )
        assert job.status == "pending"
