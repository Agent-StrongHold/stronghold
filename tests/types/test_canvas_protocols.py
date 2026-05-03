"""Protocol shape conformance tests for canvas protocols.

Verifies every Protocol is importable + runtime_checkable, and that minimal
fake implementations satisfy isinstance() checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.protocols.canvas_design import (
    AssetStore,
    BrandKitStore,
    BudgetStore,
    CanvasBackend,
    CanvasLearningStore,
    ChartRenderer,
    CorrectionStore,
    CostForecaster,
    Critic,
    DocumentStore,
    EffectApplier,
    ImageEmbedder,
    LayerRenderer,
    LoraTrainerBackend,
    ManuscriptImporter,
    MaskGenerator,
    PreflightChecker,
    PreflightRule,
    PrintExporter,
    StyleLockChecker,
    TranslationBackend,
    TTSBackend,
    VersionStore,
)
from stronghold.types.canvas_design import (
    BrandKit,
    Budget,
    BudgetScope,
    BudgetStatus,
    CanvasLearning,
    CanvasLearningScope,
    CheckResult,
    Correction,
    CorrectionContext,
    CorrectionKind,
    CorrectionSource,
    CostForecast,
    Effect,
    EffectKind,
    LearningRuleKind,
    Mask,
    MaskOrigin,
    PreflightReport,
    PreflightSummary,
    ReportLevel,
    StyleLock,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# ─── Minimal fakes that should conform structurally ─────────────────────────


class _FakeBackend:
    async def generate(
        self,
        prompt: str,
        *,
        tier: str = "draft",
        aspect_ratio: str = "1:1",
        count: int = 1,
        negative_prompt: str = "",
        reference_images: Sequence[bytes] = (),
        lora_id: str | None = None,
    ) -> list[bytes]:
        return [b""] * count

    async def refine(
        self,
        source_image: bytes,
        prompt: str,
        *,
        strength: float = 0.6,
        reference_images: Sequence[bytes] = (),
    ) -> bytes:
        return source_image

    async def inpaint(
        self,
        source_image: bytes,
        mask: Mask,
        prompt: str,
        *,
        reference_images: Sequence[bytes] = (),
        strength: float = 0.8,
    ) -> bytes:
        return source_image

    async def outpaint(
        self,
        source_image: bytes,
        direction: str,
        pixels: int,
        prompt: str,
    ) -> bytes:
        return source_image

    async def upscale(
        self,
        source_image: bytes,
        factor: int,
        *,
        model: str | None = None,
    ) -> bytes:
        return source_image


class _FakeMaskGen:
    async def create(
        self,
        origin: MaskOrigin,
        *,
        layer_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Mask:
        return Mask(id="m", width=1, height=1, data=b"\x00", origin=origin)

    def combine(self, op: str, masks: Sequence[Mask]) -> Mask:
        return masks[0]


class _FakeStyleLockChecker:
    async def score(self, layer_bytes: bytes, lock: StyleLock) -> float:
        return 0.0

    async def extract_palette(self, image_bytes: bytes, *, k: int = 5) -> tuple[str, ...]:
        return tuple(["#000000"] * k)

    async def describe(self, image_bytes: bytes) -> str:
        return "stub"


class _FakeChartRenderer:
    def render(
        self,
        spec: dict[str, Any],
        *,
        size_px: tuple[int, int] = (800, 600),
        palette: Sequence[str] = (),
    ) -> bytes:
        return b"<svg/>"


class _FakeDocStore:
    async def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        name: str,
        kind: str,
    ) -> str:
        return "doc-id"

    async def get(self, document_id: str, *, tenant_id: str) -> dict[str, Any]:
        return {}

    async def update(
        self,
        document_id: str,
        *,
        tenant_id: str,
        delta: dict[str, Any],
        expected_version: int | None = None,
    ) -> int:
        return 1

    async def list_for_owner(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        archived: bool = False,
    ) -> list[dict[str, Any]]:
        return []

    async def archive(self, document_id: str, *, tenant_id: str) -> None:
        return None


class _FakePreflight:
    async def run(
        self,
        document_id: str,
        *,
        tenant_id: str,
        rule_ids: Sequence[str] | None = None,
    ) -> PreflightReport:
        return PreflightReport(
            document_id=document_id,
            level=ReportLevel.OK,
            checks=(),
            summary=PreflightSummary(total=0, ok=0, warnings=0, failures=0),
        )

    def list_rules(self) -> tuple[str, ...]:
        return ()


class _FakeRule:
    @property
    def rule_id(self) -> str:
        return "fake_rule"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        return ()


class _FakePrintExporter:
    async def export(
        self,
        document_id: str,
        *,
        tenant_id: str,
        format: str,  # noqa: A002
        options: dict[str, Any] | None = None,
    ) -> bytes:
        return b"PDF"

    def supported_formats(self) -> tuple[str, ...]:
        return ("png",)


class _FakeVersionStore:
    async def append(
        self,
        document_id: str,
        *,
        tenant_id: str,
        author_id: str,
        author_kind: str,
        delta: dict[str, Any],
        message: str = "",
    ) -> str:
        return "v1"

    async def checkpoint(
        self,
        document_id: str,
        *,
        tenant_id: str,
        author_id: str,
        message: str,
    ) -> str:
        return "v1"

    async def get(
        self,
        document_id: str,
        version_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {}

    async def list(
        self,
        document_id: str,
        *,
        tenant_id: str,
        limit: int = 100,
        before: object | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def revert(
        self,
        document_id: str,
        version_id: str,
        *,
        tenant_id: str,
        author_id: str,
    ) -> str:
        return "v2"


class _FakeForecaster:
    def forecast(
        self,
        action: str,
        args: dict[str, Any],
        *,
        cache_lookup: bool = True,
    ) -> CostForecast:
        from decimal import Decimal

        return CostForecast(
            action=action,
            selected_model="stub",
            estimated_cost_usd=Decimal("0"),
        )


class _FakeBudgetStore:
    async def get_state(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {}

    async def reserve(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
        amount_usd: str,
    ) -> BudgetStatus:
        return BudgetStatus.OK

    async def commit(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
        amount_usd: str,
    ) -> None:
        return None

    async def upsert_budget(self, budget: Budget, *, tenant_id: str) -> None:
        return None


class _FakeBrandKitStore:
    async def create(self, kit: BrandKit) -> str:
        return kit.id

    async def get(self, kit_id: str, *, tenant_id: str) -> BrandKit:
        raise NotImplementedError

    async def list_for_tenant(self, *, tenant_id: str) -> list[BrandKit]:
        return []

    async def apply_to_document(self, document_id: str, kit_id: str, *, tenant_id: str) -> None:
        return None


class _FakeAssetStore:
    async def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        kind: str,
        name: str,
        primary_blob_id: str,
        tags: Sequence[str] = (),
    ) -> str:
        return "a"

    async def get(self, asset_id: str, *, tenant_id: str) -> dict[str, Any]:
        return {}

    async def search(
        self,
        *,
        tenant_id: str,
        query: str = "",
        kind: str | None = None,
        tags: Sequence[str] = (),
        mode: str = "tag",
    ) -> list[dict[str, Any]]:
        return []

    async def archive(self, asset_id: str, *, tenant_id: str) -> None:
        return None


class _FakeCorrectionStore:
    async def capture(
        self,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str,
        page_id: str,
        layer_id: str | None,
        session_id: str,
        kind: CorrectionKind,
        source: CorrectionSource,
        before: dict[str, Any],
        after: dict[str, Any],
        context: CorrectionContext,
    ) -> Correction:
        return Correction(
            id="c",
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=document_id,
            page_id=page_id,
            session_id=session_id,
            kind=kind,
            source=source,
            before=before,
            after=after,
            context=context,
            layer_id=layer_id,
        )

    async def list_for_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        kind: CorrectionKind | None = None,
        since: object | None = None,
        limit: int = 1000,
    ) -> list[Correction]:
        return []

    async def mark_reverted(self, correction_id: str, *, tenant_id: str) -> None:
        return None

    async def delete_for_user(self, *, tenant_id: str, user_id: str) -> int:
        return 0


class _FakeLearningStore:
    async def upsert(self, learning: CanvasLearning) -> None:
        return None

    async def list(
        self,
        *,
        tenant_id: str,
        scope: CanvasLearningScope | None = None,
        user_id: str | None = None,
        document_id: str | None = None,
        asset_id: str | None = None,
        rule_kinds: Iterable[LearningRuleKind] | None = None,
    ) -> list[CanvasLearning]:
        return []

    async def decay(self, *, days_since_run: int) -> int:
        return 0

    async def pin(self, learning_id: str, *, tenant_id: str, pinned: bool) -> None:
        return None


class _FakeCritic:
    @property
    def name(self) -> str:
        return "TYPE"

    @property
    def watches(self) -> tuple[CorrectionKind, ...]:
        return (CorrectionKind.FONT_CHANGE,)

    @property
    def precedence(self) -> int:
        return 2

    async def aggregate(
        self,
        corrections: Sequence[Correction],
    ) -> list[CanvasLearning]:
        return []


class _FakeEffectApplier:
    def supports(self, kind: EffectKind) -> bool:
        return True

    def apply(self, image: bytes, effect: Effect) -> bytes:
        return image


class _FakeLayerRenderer:
    def render(self, layer: dict[str, Any]) -> bytes:
        return b""


class _FakeManuscriptImporter:
    async def import_(
        self,
        file_bytes: bytes,
        format: str,  # noqa: A002
        *,
        doc_kind: str,
        age_band: str,
        tenant_id: str,
        owner_id: str,
        layout_kind: str | None = None,
        language: str = "en",
    ) -> str:
        return "doc-id"


class _FakeTranslationBackend:
    async def translate(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        age_band: str | None = None,
    ) -> str:
        return text


class _FakeTTS:
    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        language: str = "en",
    ) -> bytes:
        return b""

    async def list_voices(self, *, language: str | None = None) -> list[dict[str, Any]]:
        return []


class _FakeLoraTrainer:
    async def submit(
        self,
        *,
        tenant_id: str,
        scope: str,
        scope_id: str,
        base_model: str,
        training_blob_ids: Sequence[str],
        metadata_jsonl: bytes,
    ) -> str:
        return "job"

    async def status(self, job_id: str) -> dict[str, Any]:
        return {}

    async def cancel(self, job_id: str) -> None:
        return None


class _FakeEmbedder:
    async def embed(self, image: bytes) -> tuple[float, ...]:
        return (0.0,) * 512


# ─── Conformance assertions ────────────────────────────────────────────────


class TestProtocolConformance:
    def test_canvas_backend(self) -> None:
        assert isinstance(_FakeBackend(), CanvasBackend)

    def test_mask_generator(self) -> None:
        assert isinstance(_FakeMaskGen(), MaskGenerator)

    def test_style_lock_checker(self) -> None:
        assert isinstance(_FakeStyleLockChecker(), StyleLockChecker)

    def test_chart_renderer(self) -> None:
        assert isinstance(_FakeChartRenderer(), ChartRenderer)

    def test_document_store(self) -> None:
        assert isinstance(_FakeDocStore(), DocumentStore)

    def test_preflight_checker(self) -> None:
        assert isinstance(_FakePreflight(), PreflightChecker)

    def test_preflight_rule(self) -> None:
        assert isinstance(_FakeRule(), PreflightRule)

    def test_print_exporter(self) -> None:
        assert isinstance(_FakePrintExporter(), PrintExporter)

    def test_version_store(self) -> None:
        assert isinstance(_FakeVersionStore(), VersionStore)

    def test_cost_forecaster(self) -> None:
        assert isinstance(_FakeForecaster(), CostForecaster)

    def test_budget_store(self) -> None:
        assert isinstance(_FakeBudgetStore(), BudgetStore)

    def test_brand_kit_store(self) -> None:
        assert isinstance(_FakeBrandKitStore(), BrandKitStore)

    def test_asset_store(self) -> None:
        assert isinstance(_FakeAssetStore(), AssetStore)

    def test_correction_store(self) -> None:
        assert isinstance(_FakeCorrectionStore(), CorrectionStore)

    def test_canvas_learning_store(self) -> None:
        assert isinstance(_FakeLearningStore(), CanvasLearningStore)

    def test_critic(self) -> None:
        assert isinstance(_FakeCritic(), Critic)

    def test_effect_applier(self) -> None:
        assert isinstance(_FakeEffectApplier(), EffectApplier)

    def test_layer_renderer(self) -> None:
        assert isinstance(_FakeLayerRenderer(), LayerRenderer)

    def test_manuscript_importer(self) -> None:
        assert isinstance(_FakeManuscriptImporter(), ManuscriptImporter)

    def test_translation_backend(self) -> None:
        assert isinstance(_FakeTranslationBackend(), TranslationBackend)

    def test_tts_backend(self) -> None:
        assert isinstance(_FakeTTS(), TTSBackend)

    def test_lora_trainer(self) -> None:
        assert isinstance(_FakeLoraTrainer(), LoraTrainerBackend)

    def test_image_embedder(self) -> None:
        assert isinstance(_FakeEmbedder(), ImageEmbedder)


class TestErrorHierarchy:
    """Canvas errors plug into Stronghold's existing hierarchy."""

    def test_effect_kind_unknown_inherits_canvas(self) -> None:
        from stronghold.types.errors import (
            CanvasStudioError,
            EffectKindUnknownError,
            StrongholdError,
        )

        err = EffectKindUnknownError("test")
        assert isinstance(err, CanvasStudioError)
        assert isinstance(err, StrongholdError)
        assert err.code == "EFFECT_KIND_UNKNOWN"

    def test_budget_exceeded_inherits_quota_exhausted(self) -> None:
        from stronghold.types.errors import (
            BudgetExceededError,
            QuotaExhaustedError,
            RoutingError,
        )

        err = BudgetExceededError("over")
        assert isinstance(err, QuotaExhaustedError)
        assert isinstance(err, RoutingError)
        assert err.code == "BUDGET_EXCEEDED"

    def test_mask_backend_inherits_tool(self) -> None:
        from stronghold.types.errors import MaskBackendError, ToolError

        err = MaskBackendError("rembg failed")
        assert isinstance(err, ToolError)
        assert err.code == "MASK_BACKEND_ERROR"

    def test_font_validation_inherits_security(self) -> None:
        from stronghold.types.errors import FontValidationError, SecurityError

        err = FontValidationError("bad table")
        assert isinstance(err, SecurityError)
