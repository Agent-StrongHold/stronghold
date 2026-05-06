"""Templates + brand kits (spec §11).

A `Template` is a documented Document skeleton with placeholders +
parametric prompts; applying a template instantiates a new Document
with the placeholders filled. A `BrandKit` is a tenant-scoped palette +
fonts + logos + voice prompt that can be re-applied across documents.

Bundled templates are TrustTier T0 (built-in) and tenant-scoped
templates start at T3. Application is non-destructive — it writes a
new Document via the injected DocumentStore.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from stronghold.tools.canvas_layouts import layout_apply
from stronghold.types.canvas_design import (
    BrandKit,
    BrandKitFonts,
    BrandLogo,
    Color,
    DocumentKind,
    FontRef,
    FontWeight,
    Layer,
    LayerSourceKind,
    LayerTransform,
    LayoutKind,
    LogoVariant,
    Page,
    PrintSpec,
    RasterSource,
    ShapeKind,
    ShapeSource,
    TextSource,
)
from stronghold.types.errors import (
    BrandKitExtractionError,
    TemplateApplyError,
    TemplateNotFoundError,
    TemplatePromptTemplateError,
    TemplateTrustViolationError,
)
from stronghold.types.security import Provenance, TrustTier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from stronghold.persistence.canvas_design_memory import InMemoryDocumentStore


# ---------------------------------------------------------------------------
# Template variable + page model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateVariable:
    id: str
    display_name: str
    type: str  # STR | INT | COLOR | IMAGE | ENUM
    required: bool = True
    default_value: Any = None
    enum_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateLayer:
    """One layer in a Template skeleton."""

    layer_id: str
    intent: str  # LITERAL | PLACEHOLDER | PARAMETRIC | LOCKED
    layout_slot_id: str | None = None
    layer_kind: LayerSourceKind = LayerSourceKind.RASTER
    literal_text: str | None = None
    prompt_template: str | None = None
    placeholder_variable_id: str | None = None
    transform: LayerTransform = dataclasses.field(default_factory=LayerTransform)
    z_index: int = 0


@dataclass(frozen=True)
class TemplatePage:
    ordering: int
    layout_kind: LayoutKind
    layers: tuple[TemplateLayer, ...] = ()


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    category: str
    doc_kind: DocumentKind
    pages: tuple[TemplatePage, ...]
    variables: tuple[TemplateVariable, ...] = ()
    print_spec: PrintSpec | None = None
    trust_tier: TrustTier = TrustTier.T3
    provenance: Provenance = Provenance.USER
    tenant_id: str | None = None  # None for built-ins
    owner_id: str | None = None
    template_version: int = 1
    uses_count: int = 0
    description: str = ""

    def variable(self, var_id: str) -> TemplateVariable:
        for v in self.variables:
            if v.id == var_id:
                return v
        raise TemplatePromptTemplateError(f"unknown variable {var_id!r}")


# ---------------------------------------------------------------------------
# Bundled starter set
# ---------------------------------------------------------------------------


def _picture_book_classic_32() -> Template:
    return Template(
        id="builtin-picture-book-classic-32",
        name="Classic 32-page picture book",
        category="picture_book",
        doc_kind=DocumentKind.PICTURE_BOOK,
        trust_tier=TrustTier.T0,
        provenance=Provenance.BUILTIN,
        variables=(
            TemplateVariable(id="title", display_name="Title", type="STR"),
            TemplateVariable(id="byline", display_name="Author", type="STR"),
            TemplateVariable(id="hero_prompt", display_name="Cover art prompt", type="STR"),
        ),
        pages=(
            TemplatePage(
                ordering=0,
                layout_kind=LayoutKind.COVER,
                layers=(
                    TemplateLayer(
                        layer_id="title",
                        intent="PLACEHOLDER",
                        placeholder_variable_id="title",
                        layout_slot_id="title",
                        layer_kind=LayerSourceKind.TEXT,
                    ),
                    TemplateLayer(
                        layer_id="byline",
                        intent="PLACEHOLDER",
                        placeholder_variable_id="byline",
                        layout_slot_id="byline",
                        layer_kind=LayerSourceKind.TEXT,
                    ),
                    TemplateLayer(
                        layer_id="hero",
                        intent="PARAMETRIC",
                        layout_slot_id="hero_art",
                        layer_kind=LayerSourceKind.RASTER,
                        prompt_template="{{hero_prompt}}",
                    ),
                ),
            ),
            TemplatePage(ordering=1, layout_kind=LayoutKind.TITLE_PAGE),
            TemplatePage(ordering=2, layout_kind=LayoutKind.COPYRIGHT_PAGE),
            TemplatePage(ordering=3, layout_kind=LayoutKind.DEDICATION_PAGE),
        ),
        description="32-page picture-book starter with cover, title, copyright, dedication.",
    )


def _movie_poster() -> Template:
    return Template(
        id="builtin-movie-poster",
        name="One-sheet movie poster",
        category="poster",
        doc_kind=DocumentKind.POSTER,
        trust_tier=TrustTier.T0,
        provenance=Provenance.BUILTIN,
        variables=(
            TemplateVariable(id="title", display_name="Title", type="STR"),
            TemplateVariable(id="hero_prompt", display_name="Hero art", type="STR"),
            TemplateVariable(
                id="cta",
                display_name="Call-to-action",
                type="STR",
                required=False,
                default_value="In theatres now",
            ),
        ),
        pages=(
            TemplatePage(
                ordering=0,
                layout_kind=LayoutKind.POSTER,
                layers=(
                    TemplateLayer(
                        layer_id="title",
                        intent="PLACEHOLDER",
                        placeholder_variable_id="title",
                        layout_slot_id="title",
                        layer_kind=LayerSourceKind.TEXT,
                    ),
                    TemplateLayer(
                        layer_id="cta",
                        intent="PLACEHOLDER",
                        placeholder_variable_id="cta",
                        layout_slot_id="cta",
                        layer_kind=LayerSourceKind.TEXT,
                    ),
                    TemplateLayer(
                        layer_id="hero",
                        intent="PARAMETRIC",
                        layout_slot_id="hero_art",
                        layer_kind=LayerSourceKind.RASTER,
                        prompt_template="{{hero_prompt}}",
                    ),
                ),
            ),
        ),
        description="Single-page hero poster with title + CTA.",
    )


def _infographic_a2() -> Template:
    return Template(
        id="builtin-infographic-a2",
        name="A2 infographic flow",
        category="infographic",
        doc_kind=DocumentKind.INFOGRAPHIC,
        trust_tier=TrustTier.T0,
        provenance=Provenance.BUILTIN,
        variables=(TemplateVariable(id="title", display_name="Title", type="STR"),),
        pages=(
            TemplatePage(
                ordering=0,
                layout_kind=LayoutKind.INFOGRAPHIC_FLOW,
            ),
        ),
        description="A2 vertical-flow infographic with 3 sections.",
    )


_BUNDLED: dict[str, Template] = {
    t.id: t
    for t in (
        _picture_book_classic_32(),
        _movie_poster(),
        _infographic_a2(),
    )
}


# ---------------------------------------------------------------------------
# Template store
# ---------------------------------------------------------------------------


class InMemoryTemplateStore:
    """Bundled + tenant-scoped template registry."""

    def __init__(self) -> None:
        # tenant_id → template_id → Template (excluding built-ins)
        self._tenant: dict[str, dict[str, Template]] = {}

    async def list(
        self,
        *,
        tenant_id: str,
        category: str | None = None,
        doc_kind: DocumentKind | None = None,
        tenant_only: bool = False,
    ) -> list[Template]:
        out: list[Template] = []
        if not tenant_only:
            for tmpl in _BUNDLED.values():
                if category and tmpl.category != category:
                    continue
                if doc_kind and tmpl.doc_kind is not doc_kind:
                    continue
                out.append(tmpl)
        for tmpl in self._tenant.get(tenant_id, {}).values():
            if category and tmpl.category != category:
                continue
            if doc_kind and tmpl.doc_kind is not doc_kind:
                continue
            out.append(tmpl)
        return out

    async def get(self, template_id: str, *, tenant_id: str) -> Template:
        if template_id in _BUNDLED:
            return _BUNDLED[template_id]
        bucket = self._tenant.get(tenant_id, {})
        tmpl = bucket.get(template_id)
        if tmpl is None:
            raise TemplateNotFoundError(f"template {template_id!r} not found")
        return tmpl

    async def publish(self, template: Template) -> Template:
        if template.tenant_id is None:
            raise TemplateApplyError("tenant_id required to publish a template")
        bucket = self._tenant.setdefault(template.tenant_id, {})
        bucket[template.id] = template
        return template

    async def bump_uses(self, template_id: str, *, tenant_id: str) -> None:
        if template_id in _BUNDLED:
            tmpl = _BUNDLED[template_id]
            _BUNDLED[template_id] = dataclasses.replace(tmpl, uses_count=tmpl.uses_count + 1)
            return
        bucket = self._tenant.get(tenant_id, {})
        tenant_tmpl = bucket.get(template_id)
        if tenant_tmpl is not None:
            bucket[template_id] = dataclasses.replace(
                tenant_tmpl, uses_count=tenant_tmpl.uses_count + 1
            )


# ---------------------------------------------------------------------------
# Template apply
# ---------------------------------------------------------------------------


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_prompt_template(prompt_template: str, variables: Mapping[str, Any]) -> str:
    """Substitute `{{var}}` references; raise on undeclared keys."""
    referenced = set(_PLACEHOLDER_RE.findall(prompt_template))
    missing = referenced - set(variables)
    if missing:
        raise TemplatePromptTemplateError(
            f"prompt template references undeclared variables: {sorted(missing)}"
        )
    return _PLACEHOLDER_RE.sub(lambda m: str(variables[m.group(1)]), prompt_template)


def _validate_variables(template: Template, variables: Mapping[str, Any]) -> dict[str, Any]:
    bound: dict[str, Any] = {}
    for v in template.variables:
        provided = variables.get(v.id, v.default_value)
        if provided is None and v.required:
            raise TemplateApplyError(f"template {template.id!r} requires variable {v.id!r}")
        if provided is None:
            continue
        if v.type == "INT":
            try:
                bound[v.id] = int(provided)
            except (TypeError, ValueError) as exc:
                raise TemplateApplyError(
                    f"variable {v.id!r} must be INT, got {provided!r}"
                ) from exc
        elif v.type == "COLOR":
            if not isinstance(provided, str):
                raise TemplateApplyError(
                    f"variable {v.id!r} must be COLOR (hex string), got {type(provided).__name__}"
                )
            Color(provided)  # validates
            bound[v.id] = provided
        elif v.type == "ENUM":
            if provided not in v.enum_options:
                raise TemplateApplyError(
                    f"variable {v.id!r} must be one of {v.enum_options}, got {provided!r}"
                )
            bound[v.id] = provided
        elif v.type == "STR":
            bound[v.id] = str(provided)
        else:
            bound[v.id] = provided
    return bound


def _build_layer(
    template_layer: TemplateLayer,
    *,
    variables: Mapping[str, Any],
) -> Layer:
    """Materialize one TemplateLayer for a Document instance."""
    source: TextSource | RasterSource | ShapeSource
    if template_layer.intent == "LITERAL":
        if template_layer.layer_kind is LayerSourceKind.TEXT and template_layer.literal_text:
            source = TextSource(content=template_layer.literal_text)
        else:
            source = RasterSource(blob_id="", width=0, height=0)
    elif template_layer.intent == "PLACEHOLDER":
        var_id = template_layer.placeholder_variable_id
        value = variables.get(var_id, "") if var_id else ""
        if template_layer.layer_kind is LayerSourceKind.TEXT:
            source = TextSource(content=str(value))
        else:
            source = RasterSource(blob_id="", width=0, height=0)
    elif template_layer.intent == "PARAMETRIC":
        # The orchestrator-side caller would render the prompt and call
        # the generative pipeline. Here we just materialise the prompt
        # into the layer's metadata so a downstream worker can pick it up.
        prompt = (
            render_prompt_template(template_layer.prompt_template, variables)
            if template_layer.prompt_template
            else ""
        )
        if template_layer.layer_kind is LayerSourceKind.RASTER:
            source = RasterSource(blob_id="", width=0, height=0)
        else:
            source = TextSource(content="")
        return Layer(
            id=template_layer.layer_id,
            name=template_layer.layer_id,
            source=source,
            transform=template_layer.transform,
            slot_id=template_layer.layout_slot_id,
            placeholder_slot=template_layer.layout_slot_id,
            z_index=template_layer.z_index,
            metadata={"parametric_prompt": prompt},
        )
    elif template_layer.intent == "LOCKED":
        if template_layer.layer_kind is LayerSourceKind.TEXT and template_layer.literal_text:
            source = TextSource(content=template_layer.literal_text)
        else:
            source = ShapeSource(
                shape_kind=ShapeKind.RECTANGLE,
                geometry={"width": 1, "height": 1},
            )
        return Layer(
            id=template_layer.layer_id,
            name=template_layer.layer_id,
            source=source,
            transform=template_layer.transform,
            slot_id=template_layer.layout_slot_id,
            z_index=template_layer.z_index,
            locked=True,
        )
    else:
        raise TemplateApplyError(f"unknown layer intent {template_layer.intent!r}")
    return Layer(
        id=template_layer.layer_id,
        name=template_layer.layer_id,
        source=source,
        transform=template_layer.transform,
        slot_id=template_layer.layout_slot_id,
        z_index=template_layer.z_index,
    )


async def template_apply(
    template: Template,
    *,
    variables: Mapping[str, Any],
    tenant_id: str,
    owner_id: str,
    document_store: InMemoryDocumentStore,
    template_store: InMemoryTemplateStore | None = None,
) -> str:
    """Instantiate a Document from a template + variables.

    - Validates required variables + types.
    - Walks the template's pages, builds Layers for each TemplateLayer,
      applies the layout to position by slot_id, and stores the Document.
    - Returns the new document id.
    """
    if template.trust_tier in (TrustTier.T4, TrustTier.SKULL):
        raise TemplateTrustViolationError(
            f"template {template.id!r} at trust {template.trust_tier.value} cannot be applied"
        )
    bound = _validate_variables(template, variables)
    title = str(bound.get("title", template.name))
    doc_id = await document_store.create(
        tenant_id=tenant_id,
        owner_id=owner_id,
        name=title,
        kind=template.doc_kind.value,
    )
    spec = template.print_spec or PrintSpec(trim_size=(2400, 2400))
    for tpl_page in template.pages:
        layers = tuple(_build_layer(tl, variables=bound) for tl in tpl_page.layers)
        page = Page(
            id=str(uuid.uuid4()),
            ordering=tpl_page.ordering,
            print_spec=spec,
            layers=layers,
            layout_kind=tpl_page.layout_kind,
        )
        positioned = layout_apply(page, tpl_page.layout_kind)
        await document_store.add_page(
            doc_id, positioned, tenant_id=tenant_id, ordering=tpl_page.ordering
        )
    if template_store is not None:
        await template_store.bump_uses(template.id, tenant_id=tenant_id)
    return doc_id


# ---------------------------------------------------------------------------
# Brand kit
# ---------------------------------------------------------------------------


class InMemoryBrandKitStore:
    def __init__(self) -> None:
        self._kits: dict[str, dict[str, BrandKit]] = {}

    async def create(self, kit: BrandKit) -> str:
        bucket = self._kits.setdefault(kit.tenant_id, {})
        bucket[kit.id] = kit
        return kit.id

    async def get(self, kit_id: str, *, tenant_id: str) -> BrandKit:
        bucket = self._kits.get(tenant_id, {})
        if kit_id not in bucket:
            raise TemplateNotFoundError(f"brand kit {kit_id!r} not found")
        return bucket[kit_id]

    async def list_for_tenant(self, *, tenant_id: str) -> list[BrandKit]:
        return list(self._kits.get(tenant_id, {}).values())

    async def apply_to_document(
        self,
        document_id: str,
        kit_id: str,
        *,
        tenant_id: str,
        document_store: InMemoryDocumentStore | None = None,
    ) -> None:
        kit = await self.get(kit_id, tenant_id=tenant_id)
        if document_store is not None:
            await document_store.update(
                document_id,
                tenant_id=tenant_id,
                delta={"brand_kit_id": kit.id},
            )


def extract_brand_kit_from_logo(
    *,
    tenant_id: str,
    owner_id: str,
    name: str,
    logo_bytes: bytes,
    palette: Sequence[str] | None = None,
) -> BrandKit:
    """Build a BrandKit from an uploaded logo + extracted palette.

    Real implementation extracts the palette via Pillow + ColorThief; for
    the in-memory plumbing the caller passes in `palette` (or we fall
    back to a small grey scale to satisfy the 3..7 invariant).
    """
    if not logo_bytes:
        raise BrandKitExtractionError("empty logo bytes")
    palette_strs = list(palette or ("#000000", "#444444", "#888888", "#CCCCCC", "#FFFFFF"))
    if not 3 <= len(palette_strs) <= 7:
        raise BrandKitExtractionError(f"palette must contain 3..7 colours, got {len(palette_strs)}")
    return BrandKit(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        owner_id=owner_id,
        name=name,
        palette=tuple(Color(c) for c in palette_strs),
        fonts=BrandKitFonts(
            display=FontRef(family="Inter", weight=FontWeight.BOLD),
            body=FontRef(family="Atkinson Hyperlegible"),
        ),
        logos=(
            BrandLogo(
                blob_id=f"blob-{uuid.uuid4()}",
                variant=LogoVariant.PRIMARY,
            ),
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
