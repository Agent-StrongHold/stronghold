"""Canvas store and image generation client protocols.

These are the two primary dependency-inverted interfaces for the canvas
tool executor.  Production implementations wrap PostgreSQL + cloud image
gen; tests use in-memory fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from stronghold.types.canvas import (
        CanvasRecord,
        GenerationJobRecord,
        ImageData,
        LayerRecord,
    )


class CanvasStore(Protocol):
    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None: ...
    async def get_layer(self, layer_id: str) -> LayerRecord | None: ...
    async def get_job(self, job_id: str) -> GenerationJobRecord | None: ...
    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None: ...
    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord: ...
    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord: ...
    async def update_layer(self, layer: LayerRecord) -> LayerRecord: ...
    async def update_canvas(self, canvas: CanvasRecord) -> CanvasRecord: ...


class ImageGenClient(Protocol):
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
    ) -> list[ImageData]: ...

    async def refine(
        self,
        *,
        model_id: str,
        source_url: str,
        prompt: str,
        region: str = "full",
        strength: float = 0.6,
    ) -> ImageData: ...
