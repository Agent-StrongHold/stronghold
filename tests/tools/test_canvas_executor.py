"""Coverage tests for `tools.canvas_executor`.

Drives the public CanvasExecutor surface (start_job / run_job /
accept_variant / cancel_job) and `_sanitise_error`. Uses minimal in-memory
fakes for CanvasStore, ImageGenClient, ModelRegistry, and Warden so the
executor's own validation + lifecycle logic is exercised without external
deps.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from stronghold.tools.canvas_executor import CanvasExecutor, _sanitise_error
from stronghold.types.canvas import (
    CanvasNotFoundError,
    CanvasRecord,
    GenerationJobRecord,
    JobAction,
    JobAlreadyTerminalError,
    JobInProgressError,
    JobNotDoneError,
    JobNotFoundError,
    JobStatus,
    LayerNotFoundError,
    LayerRecord,
    LayerType,
    PromptBlockedError,
    RefineNoSourceError,
    TextLayerNoGenError,
    UnknownModelError,
    VariantIndexOutOfRangeError,
)

if TYPE_CHECKING:
    from stronghold.protocols.canvas import ImageData


class _FakeStore:
    def __init__(self) -> None:
        self.canvases: dict[str, CanvasRecord] = {}
        self.layers: dict[str, LayerRecord] = {}
        self.jobs: dict[str, GenerationJobRecord] = {}

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None:
        return self.canvases.get(canvas_id)

    async def update_canvas(self, canvas: CanvasRecord) -> CanvasRecord:
        self.canvases[canvas.id] = canvas
        return canvas

    async def get_layer(self, layer_id: str) -> LayerRecord | None:
        return self.layers.get(layer_id)

    async def update_layer(self, layer: LayerRecord) -> LayerRecord:
        self.layers[layer.id] = layer
        return layer

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self.jobs[job.id] = job
        return job

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        return self.jobs.get(job_id)

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self.jobs[job.id] = job
        return job

    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None:
        for job in self.jobs.values():
            if job.layer_id == layer_id and job.is_active():
                return job
        return None


class _Img:
    def __init__(self, url: str = "") -> None:
        self.width = 1
        self.height = 1
        self.url = url
        self.bytes_ = b""


class _FakeImageClient:
    def __init__(self) -> None:
        self.generate_calls: list[dict[str, object]] = []
        self.refine_calls: list[dict[str, object]] = []
        # Configurable behaviour
        self.gen_urls: list[str] = ["http://gen/0", "http://gen/1"]
        self.refine_url: str = "http://refined/0"
        self.gen_raises: Exception | None = None

    async def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        width: int,
        height: int,
        count: int = 1,
        seed: int | None = None,
        negative_prompt: str = "",
    ) -> list[ImageData]:
        self.generate_calls.append(
            {
                "model_id": model_id,
                "prompt": prompt,
                "count": count,
                "seed": seed,
                "negative_prompt": negative_prompt,
            }
        )
        if self.gen_raises is not None:
            raise self.gen_raises
        return [_Img(url=u) for u in self.gen_urls[:count]]  # type: ignore[return-value]

    async def refine(
        self,
        *,
        model_id: str,
        source_url: str,
        prompt: str,
        region: str = "full",
        strength: float = 0.6,
    ) -> ImageData:
        self.refine_calls.append(
            {
                "model_id": model_id,
                "source_url": source_url,
                "prompt": prompt,
                "region": region,
                "strength": strength,
            }
        )
        return _Img(url=self.refine_url)  # type: ignore[return-value]


class _FakeRegistry:
    def __init__(self, *, registered: set[str], default: str = "model-a") -> None:
        self._registered = registered
        self._default = default

    def is_registered(self, model_id: str) -> bool:
        return model_id in self._registered

    def get_default_draft(self) -> str:
        return self._default


class _FakeWarden:
    def __init__(self, *, verdict: str = "ALLOW") -> None:
        self.verdict = verdict
        self.calls: list[str] = []

    async def scan_prompt(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.verdict


def _executor(
    store: _FakeStore,
    *,
    warden_verdict: str = "ALLOW",
    registered: set[str] | None = None,
) -> tuple[CanvasExecutor, _FakeImageClient, _FakeWarden]:
    registry = _FakeRegistry(registered=registered or {"model-a"})
    image_client = _FakeImageClient()
    warden = _FakeWarden(verdict=warden_verdict)
    return (
        CanvasExecutor(
            store=store, image_client=image_client, model_registry=registry, warden=warden
        ),
        image_client,
        warden,
    )


def _seed_canvas_with_layer(
    store: _FakeStore,
    *,
    layer_type: str = LayerType.BACKGROUND,
    image_path: str | None = None,
) -> tuple[CanvasRecord, LayerRecord]:
    canvas = CanvasRecord(id="c1", name="Demo", width=512, height=512)
    store.canvases[canvas.id] = canvas
    layer = LayerRecord(
        id="l1",
        canvas_id=canvas.id,
        name="bg",
        layer_type=layer_type,
        image_path=image_path,
    )
    store.layers[layer.id] = layer
    return canvas, layer


# ── _sanitise_error ─────────────────────────────────────────────────


class TestSanitiseError:
    @pytest.mark.parametrize(
        ("raw", "expected_substring"),
        [
            ("HTTP 429: Rate Limit Exceeded", "rate limit reached"),
            ("rate_limit hit", "rate limit reached"),
            ("Too many requests", "rate limit reached"),
            ("ratelimit error", "rate limit reached"),
            ("HTTP 503", "temporarily unavailable"),
            ("Service Unavailable", "temporarily unavailable"),
            ("HTTP 401: Unauthorized", "authentication error"),
            ("HTTP 403", "authentication error"),
            ("Forbidden access", "authentication error"),
            ("Request timed out", "timed out"),
            ("connection timeout", "timed out"),
            ("uncategorised internal weirdness", "provider error"),
        ],
    )
    def test_classifications(self, raw: str, expected_substring: str) -> None:
        out = _sanitise_error(Exception(raw))
        assert expected_substring in out


# ── start_job ───────────────────────────────────────────────────────


class TestStartJob:
    async def test_happy_path_creates_pending_job(self) -> None:
        store = _FakeStore()
        _, _ = _seed_canvas_with_layer(store)
        executor, _, warden = _executor(store)

        job = await executor.start_job(
            canvas_id="c1",
            layer_id="l1",
            action=JobAction.GENERATE,
            prompt="hello",
            count=2,
            seed=7,
        )

        assert job.status == JobStatus.PENDING
        assert job.action == JobAction.GENERATE
        assert job.params["count"] == 2
        assert job.params["seed"] == 7
        assert warden.calls == ["hello"]

    async def test_unknown_layer_raises(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        with pytest.raises(LayerNotFoundError):
            await executor.start_job(
                canvas_id="c1", layer_id="nope", action=JobAction.GENERATE, prompt="x"
            )

    async def test_text_layer_blocks_image_gen_actions(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store, layer_type=LayerType.TEXT)
        executor, _, _ = _executor(store)
        with pytest.raises(TextLayerNoGenError):
            await executor.start_job(
                canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x"
            )

    async def test_unregistered_explicit_model_raises(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store, registered={"model-a"})
        with pytest.raises(UnknownModelError):
            await executor.start_job(
                canvas_id="c1",
                layer_id="l1",
                action=JobAction.GENERATE,
                prompt="x",
                model_id="bogus-model",
            )

    async def test_warden_block_rejects_prompt(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store, warden_verdict="BLOCK")
        with pytest.raises(PromptBlockedError):
            await executor.start_job(
                canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="bad"
            )

    async def test_refine_without_image_path_raises(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        with pytest.raises(RefineNoSourceError):
            await executor.start_job(
                canvas_id="c1", layer_id="l1", action=JobAction.REFINE, prompt="x"
            )

    async def test_active_job_blocks_concurrent_start(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x"
        )
        with pytest.raises(JobInProgressError):
            await executor.start_job(
                canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="y"
            )

    async def test_layer_lock_is_reused_per_layer(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        first = executor._layer_lock("l1")
        second = executor._layer_lock("l1")
        assert first is second


# ── run_job ─────────────────────────────────────────────────────────


class TestRunJob:
    async def test_unknown_job_raises(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        with pytest.raises(JobNotFoundError):
            await executor.run_job("nope")

    async def test_non_pending_job_returns_unchanged(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        job = GenerationJobRecord(
            id=str(uuid.uuid4()),
            layer_id="l1",
            canvas_id="c1",
            action=JobAction.GENERATE,
            status=JobStatus.RUNNING,
        )
        store.jobs[job.id] = job
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.RUNNING

    async def test_generate_path_marks_done_with_paths(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, image_client, _ = _executor(store)
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x", count=2
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.DONE
        assert out.result_paths == ["http://gen/0", "http://gen/1"]
        assert image_client.generate_calls

    async def test_generate_path_failure_marks_failed_with_sanitised_msg(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, image_client, _ = _executor(store)
        image_client.gen_raises = Exception("HTTP 429: rate_limit hit")
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x"
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.FAILED
        assert out.error_message is not None
        assert "rate limit" in out.error_message.lower()
        # Original exception detail must not leak through
        assert "HTTP 429" not in out.error_message

    async def test_generate_with_no_urls_marks_failed(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, image_client, _ = _executor(store)
        image_client.gen_urls = ["", ""]
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x", count=2
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.FAILED

    async def test_generate_count_mismatch_warns_but_succeeds(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, image_client, _ = _executor(store)
        image_client.gen_urls = ["only-one"]
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x", count=4
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.DONE
        assert out.result_paths == ["only-one"]

    async def test_canvas_missing_at_run_time_marks_failed(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x"
        )
        # Drop the canvas before run_job
        del store.canvases["c1"]
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.FAILED

    async def test_refine_path_marks_done(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store, image_path="http://existing/")
        executor, image_client, _ = _executor(store)
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFINE, prompt="x"
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.DONE
        assert out.result_paths == ["http://refined/0"]
        assert image_client.refine_calls

    async def test_refine_with_layer_image_path_dropped_at_runtime_fails(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store, image_path="http://existing/")
        executor, _, _ = _executor(store)
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFINE, prompt="x"
        )
        # Wipe image_path before run
        store.layers["l1"].image_path = None
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.FAILED

    async def test_reference_action_emits_hero_plus_views(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, image_client, _ = _executor(store)
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFERENCE, prompt="dragon"
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.DONE
        # Hero + 3 view refines
        assert len(out.result_paths) == 4
        assert len(image_client.refine_calls) == 3

    async def test_reference_action_with_empty_hero_returns_no_paths(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, image_client, _ = _executor(store)
        image_client.gen_urls = [""]
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.REFERENCE, prompt="x"
        )
        out = await executor.run_job(job.id)
        # REFERENCE returns [] (no exception) when the hero is missing —
        # run_job marks the job DONE with an empty result_paths list.
        assert out.status == JobStatus.DONE
        assert out.result_paths == []

    async def test_composite_action_is_not_a_gen_action(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        # COMPOSITE is not in _IMAGE_GEN_ACTIONS so start_job allows it,
        # but _execute_action raises ValueError → FAILED.
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.COMPOSITE, prompt=""
        )
        out = await executor.run_job(job.id)
        assert out.status == JobStatus.FAILED


# ── accept_variant ──────────────────────────────────────────────────


class TestAcceptVariant:
    async def _seed_done_job(self, store: _FakeStore, *, paths: list[str]) -> GenerationJobRecord:
        _, _ = _seed_canvas_with_layer(store)
        job = GenerationJobRecord(
            id=str(uuid.uuid4()),
            layer_id="l1",
            canvas_id="c1",
            action=JobAction.GENERATE,
            status=JobStatus.DONE,
            result_paths=paths,
        )
        store.jobs[job.id] = job
        return job

    async def test_accept_updates_layer_image_path(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        job = await self._seed_done_job(store, paths=["url-a", "url-b"])
        out_job, out_layer = await executor.accept_variant(job.id, 1)
        assert out_layer.image_path == "url-b"
        assert out_job.selected_index == 1

    async def test_accept_unknown_job_raises(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        with pytest.raises(JobNotFoundError):
            await executor.accept_variant("nope", 0)

    async def test_accept_non_done_job_raises(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        job = GenerationJobRecord(
            id="j1",
            layer_id="l1",
            canvas_id="c1",
            status=JobStatus.PENDING,
        )
        store.jobs[job.id] = job
        with pytest.raises(JobNotDoneError):
            await executor.accept_variant("j1", 0)

    @pytest.mark.parametrize("idx", [-1, 2])
    async def test_accept_out_of_range_index_raises(self, idx: int) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        await self._seed_done_job(store, paths=["a", "b"])
        job_id = next(iter(store.jobs))
        with pytest.raises(VariantIndexOutOfRangeError):
            await executor.accept_variant(job_id, idx)

    async def test_accept_with_layer_gone_raises(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        await self._seed_done_job(store, paths=["a"])
        job_id = next(iter(store.jobs))
        del store.layers["l1"]
        with pytest.raises(LayerNotFoundError):
            await executor.accept_variant(job_id, 0)

    async def test_accept_advances_canvas_updated_at(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        await self._seed_done_job(store, paths=["a"])
        job_id = next(iter(store.jobs))
        before = store.canvases["c1"].updated_at
        _, _ = await executor.accept_variant(job_id, 0)
        assert store.canvases["c1"].updated_at >= before

    async def test_accept_when_canvas_missing_does_not_raise(self) -> None:
        # If the canvas record is gone, accept still completes (layer
        # update happened first); the canvas-touch becomes a no-op.
        store = _FakeStore()
        executor, _, _ = _executor(store)
        await self._seed_done_job(store, paths=["a"])
        job_id = next(iter(store.jobs))
        del store.canvases["c1"]
        out_job, _ = await executor.accept_variant(job_id, 0)
        assert out_job.selected_index == 0


# ── cancel_job ──────────────────────────────────────────────────────


class TestCancelJob:
    async def test_cancel_unknown_job_raises(self) -> None:
        store = _FakeStore()
        executor, _, _ = _executor(store)
        with pytest.raises(JobNotFoundError):
            await executor.cancel_job("nope")

    async def test_cancel_pending_job_marks_cancelled(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        job = await executor.start_job(
            canvas_id="c1", layer_id="l1", action=JobAction.GENERATE, prompt="x"
        )
        out = await executor.cancel_job(job.id)
        assert out.status == JobStatus.CANCELLED
        assert out.completed_at is not None

    async def test_cancel_terminal_job_raises(self) -> None:
        store = _FakeStore()
        _seed_canvas_with_layer(store)
        executor, _, _ = _executor(store)
        job = GenerationJobRecord(
            id="j1",
            layer_id="l1",
            canvas_id="c1",
            status=JobStatus.DONE,
        )
        store.jobs[job.id] = job
        with pytest.raises(JobAlreadyTerminalError):
            await executor.cancel_job("j1")

    async def test_canvas_not_found_error_unused(self) -> None:
        # CanvasNotFoundError is raised via _execute_action on missing canvas.
        # Covered by test_canvas_missing_at_run_time_marks_failed but we
        # also assert the import path here for completeness.
        assert CanvasNotFoundError.code == "CANVAS_NOT_FOUND"
