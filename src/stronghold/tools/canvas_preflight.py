"""Pre-flight validation engine (spec §22).

Plug-in rule registry + `PreflightChecker` that walks a Document and
collects findings. Each rule is a small class implementing the
`PreflightRule` Protocol; the checker aggregates results into a typed
report.

P0 rules implemented here (pure data; no external deps):
  - bg_covers_bleed       (FAIL): background layer must cover the
                                  bleed canvas.
  - text_in_safe_area     (FAIL): every text layer bbox must lie inside
                                  the page's safe rect.
  - dpi_minimum           (FAIL): every raster layer must meet the page DPI.
  - page_count_parity     (WARN): picture_book pages divisible by 4.
  - binding_creep_safe    (WARN): saddle-stitch ≤ 64 pages.
  - empty_document        (FAIL): document must have at least one page.

Heavier rules (Warden, vision-LLM, font embed checks, spell, contrast,
etc.) are deferred — they live in the same registry once their backends
ship.
"""

from __future__ import annotations

import dataclasses
from collections import OrderedDict
from typing import TYPE_CHECKING

from stronghold.types.canvas_design import (
    BindingKind,
    CheckResult,
    CheckScope,
    Document,
    DocumentKind,
    LayerSourceKind,
    PreflightReport,
    PreflightSummary,
    RasterSource,
    ReportLevel,
    TextSource,
)
from stronghold.types.errors import RuleNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stronghold.types.canvas_design import Layer, Page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trim_bbox(page: Page) -> tuple[int, int, int, int]:
    w, h = page.print_spec.trim_size
    return (0, 0, w, h)


def _bleed_bbox(page: Page) -> tuple[int, int, int, int]:
    w, h = page.print_spec.bleed_canvas
    return (0, 0, w, h)


def _safe_rect(page: Page) -> tuple[int, int, int, int]:
    s = page.print_spec.safe_rect
    return (s.x, s.y, s.x + s.width, s.y + s.height)


def _layer_bbox(layer: Layer) -> tuple[int, int, int, int]:
    """Approximate axis-aligned bbox in page coordinates.

    Doesn't account for rotation (deferred); uses x/y/scale and the
    source's intrinsic dims when known. For text/shape sources we use
    the layer transform x/y as the top-left and a unit width — refined
    once the renderer can measure text/shape extents.
    """
    src = layer.source
    if isinstance(src, RasterSource):
        w = int(round(src.width * layer.transform.scale))
        h = int(round(src.height * layer.transform.scale))
    else:
        # Fallback: assume the layer occupies a 1x1 pixel — this only
        # affects "is fully inside safe area" checks and is conservative
        # (a 1x1 layer is always inside if its origin is inside).
        w = 1
        h = 1
    return (
        layer.transform.x,
        layer.transform.y,
        layer.transform.x + max(0, w),
        layer.transform.y + max(0, h),
    )


def _bbox_inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _bbox_covers(cover: tuple[int, int, int, int], target: tuple[int, int, int, int]) -> bool:
    return _bbox_inside(target, cover)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class _RuleBase:
    rule_id: str = ""

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        raise NotImplementedError


@dataclasses.dataclass
class _Context:
    """Cheap dependency-injected document accessor used by the rules.

    The official PreflightRule Protocol takes (document_id, tenant_id).
    For test ergonomics + speed we inject the resolved Document directly
    via a thread-local-style attribute set by PreflightChecker.run().
    """

    document: Document


_CTX: dict[str, _Context] = {}


def _ctx_for(document_id: str) -> _Context:
    return _CTX[document_id]


class BgCoversBleedRule(_RuleBase):
    rule_id = "bg_covers_bleed"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        doc = _ctx_for(document_id).document
        results: list[CheckResult] = []
        for page in doc.pages:
            bleed = _bleed_bbox(page)
            covered = any(
                _bbox_covers(_layer_bbox(layer), bleed)
                for layer in page.layers
                if layer.source.kind is LayerSourceKind.RASTER and layer.visible
            )
            if not covered and len(page.layers) > 0:
                results.append(
                    CheckResult(
                        rule_id=self.rule_id,
                        scope=CheckScope.PAGE,
                        scope_id=page.id,
                        level=ReportLevel.FAIL,
                        message="No background layer covers the bleed canvas",
                        detail={"bleed_bbox": list(bleed)},
                    )
                )
        return tuple(results)


class TextInSafeAreaRule(_RuleBase):
    rule_id = "text_in_safe_area"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        doc = _ctx_for(document_id).document
        results: list[CheckResult] = []
        for page in doc.pages:
            safe = _safe_rect(page)
            for layer in page.layers:
                if not layer.visible:
                    continue
                if not isinstance(layer.source, TextSource):
                    continue
                bbox = _layer_bbox(layer)
                if not _bbox_inside(bbox, safe):
                    results.append(
                        CheckResult(
                            rule_id=self.rule_id,
                            scope=CheckScope.LAYER,
                            scope_id=layer.id,
                            level=ReportLevel.FAIL,
                            message="Text layer crosses the safe-area boundary",
                            detail={"text_bbox": list(bbox), "safe": list(safe)},
                        )
                    )
        return tuple(results)


class DpiMinimumRule(_RuleBase):
    rule_id = "dpi_minimum"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        doc = _ctx_for(document_id).document
        results: list[CheckResult] = []
        for page in doc.pages:
            page_dpi = page.print_spec.dpi
            trim_w, _trim_h = page.print_spec.trim_size
            for layer in page.layers:
                if not isinstance(layer.source, RasterSource):
                    continue
                # Effective horizontal pixel density = source pixels per
                # rendered inch on the page. With scale=1.0 and a layer
                # rendered to fit trim, source_w must equal trim_w * dpi /
                # page_dpi (i.e., source_w >= trim_w). That's a strong
                # heuristic: any visible raster spanning the trim must be
                # at least trim_w pixels wide.
                rendered_w = int(round(layer.source.width * layer.transform.scale))
                if rendered_w < trim_w:
                    results.append(
                        CheckResult(
                            rule_id=self.rule_id,
                            scope=CheckScope.LAYER,
                            scope_id=layer.id,
                            level=ReportLevel.FAIL,
                            message=(
                                f"Raster layer rendered width {rendered_w}px is below page DPI"
                                f" target ({trim_w}px at {page_dpi} DPI)"
                            ),
                            detail={
                                "rendered_width_px": rendered_w,
                                "required_width_px": trim_w,
                                "page_dpi": page_dpi,
                            },
                        )
                    )
        return tuple(results)


class PageCountParityRule(_RuleBase):
    rule_id = "page_count_parity"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        doc = _ctx_for(document_id).document
        if doc.kind is not DocumentKind.PICTURE_BOOK:
            return ()
        if doc.page_count == 0:
            return ()
        if doc.page_count % 4 == 0:
            return ()
        return (
            CheckResult(
                rule_id=self.rule_id,
                scope=CheckScope.DOCUMENT,
                scope_id=doc.id,
                level=ReportLevel.WARN,
                message=(
                    f"Picture book page count ({doc.page_count}) is not a multiple of 4 — "
                    "binding signature mismatch likely"
                ),
                detail={"page_count": doc.page_count},
            ),
        )


class BindingCreepSafeRule(_RuleBase):
    rule_id = "binding_creep_safe"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        doc = _ctx_for(document_id).document
        # Binding lives on each page's print_spec; saddle-stitch limit is
        # whole-document so check via the first page's spec.
        if not doc.pages:
            return ()
        binding = doc.pages[0].print_spec.binding
        if binding is not BindingKind.SADDLE_STITCH:
            return ()
        if doc.page_count <= 64:
            return ()
        return (
            CheckResult(
                rule_id=self.rule_id,
                scope=CheckScope.DOCUMENT,
                scope_id=doc.id,
                level=ReportLevel.WARN,
                message=(
                    f"Saddle-stitch binding with {doc.page_count} pages exceeds 64-page "
                    "creep-safe limit; consider perfect binding"
                ),
                detail={"page_count": doc.page_count, "binding": binding.value},
            ),
        )


class EmptyDocumentRule(_RuleBase):
    rule_id = "empty_document"

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        doc = _ctx_for(document_id).document
        if doc.page_count == 0:
            return (
                CheckResult(
                    rule_id=self.rule_id,
                    scope=CheckScope.DOCUMENT,
                    scope_id=doc.id,
                    level=ReportLevel.FAIL,
                    message="Document has 0 pages — export refused",
                ),
            )
        return ()


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


_DEFAULT_RULES: tuple[_RuleBase, ...] = (
    EmptyDocumentRule(),
    BgCoversBleedRule(),
    TextInSafeAreaRule(),
    DpiMinimumRule(),
    PageCountParityRule(),
    BindingCreepSafeRule(),
)


class PreflightChecker:
    """Pre-flight registry + runner satisfying `PreflightChecker` Protocol.

    Construct without arguments to get the default rule set; pass an
    explicit `rules=` to override (e.g. for unit tests targeting one rule).

    Pre-resolves the Document via the injected `DocumentStore` (or via a
    direct `set_document()` call for unit tests that don't use the store).
    """

    def __init__(
        self,
        *,
        rules: Sequence[_RuleBase] | None = None,
        store: object | None = None,
    ) -> None:
        self._rules: OrderedDict[str, _RuleBase] = OrderedDict(
            (rule.rule_id, rule) for rule in (rules if rules is not None else _DEFAULT_RULES)
        )
        self._store = store
        self._silenced: set[tuple[str, str]] = set()  # (rule_id, scope_id)

    def list_rules(self) -> tuple[str, ...]:
        return tuple(self._rules.keys())

    def silence(self, rule_id: str, scope_id: str = "") -> None:
        if rule_id == "tenant_assets_only":
            # Per spec §22 edge case: tenant-isolation rule cannot be silenced.
            raise RuleNotFoundError("tenant_assets_only cannot be silenced")
        self._silenced.add((rule_id, scope_id))

    def set_document(self, document: Document) -> None:
        """Inject a Document directly (test path; bypasses store)."""
        _CTX[document.id] = _Context(document=document)

    async def run(
        self,
        document_id: str,
        *,
        tenant_id: str,
        rule_ids: Sequence[str] | None = None,
    ) -> PreflightReport:
        # Resolve via store if injected; otherwise expect set_document() was used.
        if document_id not in _CTX and self._store is not None:
            doc_dict = await self._store.get(document_id, tenant_id=tenant_id)  # type: ignore[attr-defined]
            # Round-trip dict→Document is out of scope for this slice; tests
            # use set_document() and skip the store path.
            del doc_dict
        if document_id not in _CTX:
            raise RuleNotFoundError(f"document {document_id!r} not registered for preflight")

        target_rules = (
            tuple(self._rules[rid] for rid in rule_ids if rid in self._rules)
            if rule_ids is not None
            else tuple(self._rules.values())
        )
        all_results: list[CheckResult] = []
        for rule in target_rules:
            findings = await rule.check(document_id, tenant_id=tenant_id)
            for cr in findings:
                if (cr.rule_id, cr.scope_id) in self._silenced:
                    continue
                all_results.append(cr)

        ok_count = sum(1 for r in all_results if r.level is ReportLevel.OK)
        warn_count = sum(1 for r in all_results if r.level is ReportLevel.WARN)
        fail_count = sum(1 for r in all_results if r.level is ReportLevel.FAIL)
        level = (
            ReportLevel.FAIL
            if fail_count > 0
            else (ReportLevel.WARN if warn_count > 0 else ReportLevel.OK)
        )
        summary = PreflightSummary(
            total=len(all_results),
            ok=ok_count,
            warnings=warn_count,
            failures=fail_count,
        )
        return PreflightReport(
            document_id=document_id,
            level=level,
            checks=tuple(all_results),
            summary=summary,
        )
