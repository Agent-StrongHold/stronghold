"""Mask system green tests — features/mask-system.feature scenarios."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from stronghold.tools.canvas_masks import PillowMaskGenerator
from stronghold.types.canvas_design import Mask, MaskOrigin
from stronghold.types.errors import MaskBackendError, MaskParamsError


def _decode(mask: Mask) -> Image.Image:
    img = Image.open(io.BytesIO(mask.data))
    img.load()
    assert img.mode == "L"
    return img


@pytest.fixture
def gen() -> PillowMaskGenerator:
    return PillowMaskGenerator()


# ─── BBOX ──────────────────────────────────────────────────────────────────


class TestBboxOrigin:
    async def test_bbox_produces_l_mode_png_of_correct_size(self, gen: PillowMaskGenerator) -> None:
        mask = await gen.create(
            MaskOrigin.BBOX,
            params={"dims": (512, 512), "bbox": (100, 100, 400, 400)},
        )
        img = _decode(mask)
        assert (mask.width, mask.height) == (512, 512)
        assert img.size == (512, 512)
        # Inside the bbox = 255, outside = 0
        assert img.getpixel((250, 250)) == 255
        assert img.getpixel((10, 10)) == 0
        assert img.getpixel((450, 450)) == 0
        assert img.getpixel((50, 50)) == 0
        assert mask.origin is MaskOrigin.BBOX

    async def test_bbox_malformed_coords_rejected(self, gen: PillowMaskGenerator) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(MaskOrigin.BBOX, params={"bbox": (100, 100, 50, 50)})

    async def test_bbox_missing_param(self, gen: PillowMaskGenerator) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(MaskOrigin.BBOX, params={})


# ─── POLYGON ───────────────────────────────────────────────────────────────


class TestPolygonOrigin:
    async def test_triangle_renders_correctly(self, gen: PillowMaskGenerator) -> None:
        mask = await gen.create(
            MaskOrigin.POLYGON,
            params={
                "dims": (512, 512),
                "vertices": [(50, 50), (450, 50), (250, 450)],
            },
        )
        img = _decode(mask)
        assert img.getpixel((250, 200)) == 255  # centroid-ish
        assert img.getpixel((0, 0)) == 0

    async def test_collinear_polygon_rejected(self, gen: PillowMaskGenerator) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(
                MaskOrigin.POLYGON,
                params={"vertices": [(0, 0), (10, 10), (20, 20)]},
            )

    async def test_too_few_vertices_rejected(self, gen: PillowMaskGenerator) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(MaskOrigin.POLYGON, params={"vertices": [(0, 0), (10, 10)]})


# ─── BRUSH ─────────────────────────────────────────────────────────────────


class TestBrushOrigin:
    async def test_brush_dabs_render(self, gen: PillowMaskGenerator) -> None:
        mask = await gen.create(
            MaskOrigin.BRUSH,
            params={
                "dims": (512, 512),
                "dabs": [(100, 100, 20), (200, 200, 30)],
            },
        )
        img = _decode(mask)
        assert img.getpixel((100, 100)) == 255
        assert img.getpixel((200, 200)) == 255
        # Far from any dab
        assert img.getpixel((400, 400)) == 0

    async def test_too_many_dabs_rejected(self, gen: PillowMaskGenerator) -> None:
        many_dabs = [(0, 0, 1)] * 1025
        with pytest.raises(MaskParamsError):
            await gen.create(MaskOrigin.BRUSH, params={"dabs": many_dabs})

    async def test_zero_radius_rejected(self, gen: PillowMaskGenerator) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(MaskOrigin.BRUSH, params={"dabs": [(50, 50, 0)]})


# ─── UPLOADED ──────────────────────────────────────────────────────────────


def _png_l(width: int, height: int, fill: int) -> bytes:
    img = Image.new("L", (width, height), color=fill)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_rgba(width: int, height: int) -> bytes:
    img = Image.new("RGBA", (width, height), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestUploadedOrigin:
    async def test_normalises_rgba_to_l(self, gen: PillowMaskGenerator) -> None:
        mask = await gen.create(
            MaskOrigin.UPLOADED,
            params={"data": _png_rgba(64, 64)},
        )
        img = _decode(mask)
        assert img.mode == "L"
        assert (mask.width, mask.height) == (64, 64)

    async def test_resize_to_target_when_dims_mismatch(self, gen: PillowMaskGenerator) -> None:
        mask = await gen.create(
            MaskOrigin.UPLOADED,
            params={
                "data": _png_l(256, 256, 200),
                "target_dims": (512, 512),
                "auto_resize": True,
            },
        )
        assert (mask.width, mask.height) == (512, 512)

    async def test_dims_mismatch_without_auto_resize_rejected(
        self, gen: PillowMaskGenerator
    ) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(
                MaskOrigin.UPLOADED,
                params={
                    "data": _png_l(256, 256, 200),
                    "target_dims": (512, 512),
                    "auto_resize": False,
                },
            )

    async def test_non_bytes_data_rejected(self, gen: PillowMaskGenerator) -> None:
        with pytest.raises(MaskParamsError):
            await gen.create(MaskOrigin.UPLOADED, params={"data": "not bytes"})


# ─── Backend-only origins ──────────────────────────────────────────────────


class TestBackendOrigins:
    @pytest.mark.parametrize(
        "origin",
        [MaskOrigin.AUTO_SUBJECT, MaskOrigin.AUTO_BACKGROUND, MaskOrigin.PROMPT],
    )
    async def test_backend_origins_raise(
        self, gen: PillowMaskGenerator, origin: MaskOrigin
    ) -> None:
        with pytest.raises(MaskBackendError):
            await gen.create(origin)


# ─── Combine ───────────────────────────────────────────────────────────────


def _bbox_mask(gen: PillowMaskGenerator, bbox: tuple[int, int, int, int]) -> Mask:
    import asyncio

    return asyncio.run(gen.create(MaskOrigin.BBOX, params={"dims": (200, 200), "bbox": bbox}))


class TestCombineOps:
    def test_union_is_commutative(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 100, 200))
        b = _bbox_mask(gen, (100, 0, 200, 200))
        u_ab = gen.combine("union", (a, b))
        u_ba = gen.combine("union", (b, a))
        assert _decode(u_ab).tobytes() == _decode(u_ba).tobytes()

    def test_intersect_is_commutative(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 150, 200))
        b = _bbox_mask(gen, (100, 0, 200, 200))
        i_ab = gen.combine("intersect", (a, b))
        i_ba = gen.combine("intersect", (b, a))
        assert _decode(i_ab).tobytes() == _decode(i_ba).tobytes()

    def test_subtract_is_not_commutative(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 150, 200))
        b = _bbox_mask(gen, (100, 0, 200, 200))
        s_ab = gen.combine("subtract", (a, b))
        s_ba = gen.combine("subtract", (b, a))
        assert _decode(s_ab).tobytes() != _decode(s_ba).tobytes()

    def test_invert_single_mask(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 100, 100))
        inv = gen.combine("invert", (a,))
        img_a = _decode(a)
        img_i = _decode(inv)
        # Pixel that was 255 should become 0; pixel that was 0 should become 255
        assert img_a.getpixel((50, 50)) == 255
        assert img_i.getpixel((50, 50)) == 0
        assert img_a.getpixel((150, 150)) == 0
        assert img_i.getpixel((150, 150)) == 255

    def test_invert_requires_exactly_one_mask(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 50, 50))
        b = _bbox_mask(gen, (50, 50, 100, 100))
        with pytest.raises(MaskParamsError):
            gen.combine("invert", (a, b))

    def test_combine_empty_input_rejected(self) -> None:
        gen = PillowMaskGenerator()
        with pytest.raises(MaskParamsError):
            gen.combine("union", ())

    def test_combine_single_input_for_binary_op_rejected(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 50, 50))
        with pytest.raises(MaskParamsError):
            gen.combine("union", (a,))

    def test_combine_unknown_op(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 50, 50))
        b = _bbox_mask(gen, (50, 50, 100, 100))
        with pytest.raises(MaskParamsError):
            gen.combine("xor", (a, b))

    def test_combine_dimension_mismatch_rejected(self) -> None:
        gen = PillowMaskGenerator()
        a = _bbox_mask(gen, (0, 0, 50, 50))
        # Different dims
        import asyncio

        b = asyncio.run(
            gen.create(MaskOrigin.BBOX, params={"dims": (100, 100), "bbox": (0, 0, 50, 50)})
        )
        with pytest.raises(MaskParamsError):
            gen.combine("union", (a, b))


# ─── Protocol conformance ──────────────────────────────────────────────────


class TestProtocolConformance:
    def test_satisfies_mask_generator_protocol(self) -> None:
        from stronghold.protocols.canvas_design import MaskGenerator

        assert isinstance(PillowMaskGenerator(), MaskGenerator)
