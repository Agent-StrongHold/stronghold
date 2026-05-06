"""Print-on-Demand integration (spec §28).

Core delivery path for children's books + posters: the user pays the
provider, we ship them physical copies. Each provider has its own strict
spec on top of §08/§22 (gutter, bleed, DPI, embedded fonts), exposed via
a `PrintProvider` Protocol shape that production replaces with real
Lulu / KDP / Blurb / Printful / Gelato / IngramSpark adapters.

This module ships:
  - `PrintOrder` + supporting types (Address, CostBreakdown, ProviderKind)
  - `MockPrintProvider`: deterministic in-memory simulator for tests + dev
  - `InMemoryPrintOrderManager`: orchestrates quote → validate → submit →
    poll → cancel, gates pre-flight, applies provider spec rules, persists
    orders tenant-scoped
  - `PROVIDER_RULES`: per-provider validation rules (gutter, max trim,
    bleed exact, DPI floor, etc.)

Address storage is plaintext in-memory; production uses tenant-keyed
envelope encryption (out of scope for this slice).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from stronghold.types.canvas_design import (
    BindingKind,
    DocumentKind,
    PrintSpec,
)
from stronghold.types.errors import (
    PrintAddressInvalidError,
    PrintOrderNotFoundError,
    PrintProviderError,
    PrintProviderRejectedError,
    PrintQuoteExpiredError,
)

# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------


class ProviderKind(StrEnum):
    LULU = "lulu"
    KDP = "kdp"
    BLURB = "blurb"
    PRINTFUL = "printful"
    GELATO = "gelato"
    INGRAMSPARK = "ingramspark"


class ProductKind(StrEnum):
    PAPERBACK_BOOK = "paperback_book"
    HARDCOVER_BOOK = "hardcover_book"
    PHOTO_BOOK = "photo_book"
    POSTER = "poster"
    CANVAS_PRINT = "canvas_print"
    ART_PRINT = "art_print"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    QUOTED = "quoted"
    SUBMITTED = "submitted"
    IN_PRODUCTION = "in_production"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Per-provider validation rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderRules:
    """The strict-mode constraints each provider enforces beyond §08."""

    name: str
    products: tuple[ProductKind, ...]
    min_dpi: int
    bleed_px: int  # required exact value at 300 DPI
    gutter_min_px: int  # binding gutter (book providers); 0 for posters
    max_trim_px: tuple[int, int]
    requires_embedded_fonts: bool
    requires_cmyk: bool
    book_min_pages: int
    book_max_pages: int


PROVIDER_RULES: dict[ProviderKind, ProviderRules] = {
    ProviderKind.LULU: ProviderRules(
        name="Lulu",
        products=(
            ProductKind.PAPERBACK_BOOK,
            ProductKind.HARDCOVER_BOOK,
            ProductKind.PHOTO_BOOK,
        ),
        min_dpi=300,
        bleed_px=38,  # 0.125" @ 300 DPI
        gutter_min_px=150,  # 0.5" @ 300 DPI
        max_trim_px=(3300, 5100),  # tabloid
        requires_embedded_fonts=True,
        requires_cmyk=False,
        book_min_pages=24,
        book_max_pages=800,
    ),
    ProviderKind.KDP: ProviderRules(
        name="Amazon KDP",
        products=(ProductKind.PAPERBACK_BOOK, ProductKind.HARDCOVER_BOOK),
        min_dpi=300,
        bleed_px=38,
        gutter_min_px=180,
        max_trim_px=(2550, 3300),
        requires_embedded_fonts=True,
        requires_cmyk=False,
        book_min_pages=24,
        book_max_pages=828,
    ),
    ProviderKind.BLURB: ProviderRules(
        name="Blurb",
        products=(ProductKind.PHOTO_BOOK, ProductKind.HARDCOVER_BOOK),
        min_dpi=300,
        bleed_px=38,
        gutter_min_px=120,
        max_trim_px=(3300, 5100),
        requires_embedded_fonts=True,
        requires_cmyk=False,
        book_min_pages=20,
        book_max_pages=440,
    ),
    ProviderKind.PRINTFUL: ProviderRules(
        name="Printful",
        products=(
            ProductKind.POSTER,
            ProductKind.CANVAS_PRINT,
            ProductKind.ART_PRINT,
        ),
        min_dpi=300,
        bleed_px=38,
        gutter_min_px=0,
        max_trim_px=(7200, 10800),  # 24x36 movie poster
        requires_embedded_fonts=False,
        requires_cmyk=False,
        book_min_pages=0,
        book_max_pages=0,
    ),
    ProviderKind.GELATO: ProviderRules(
        name="Gelato",
        products=(
            ProductKind.PAPERBACK_BOOK,
            ProductKind.HARDCOVER_BOOK,
            ProductKind.POSTER,
            ProductKind.ART_PRINT,
        ),
        min_dpi=300,
        bleed_px=38,
        gutter_min_px=120,
        max_trim_px=(7200, 10800),
        requires_embedded_fonts=True,
        requires_cmyk=False,
        book_min_pages=4,
        book_max_pages=800,
    ),
    ProviderKind.INGRAMSPARK: ProviderRules(
        name="IngramSpark",
        products=(ProductKind.PAPERBACK_BOOK, ProductKind.HARDCOVER_BOOK),
        min_dpi=300,
        bleed_px=38,
        gutter_min_px=180,
        max_trim_px=(3300, 5100),
        requires_embedded_fonts=True,
        requires_cmyk=True,
        book_min_pages=18,
        book_max_pages=1200,
    ),
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Address:
    name: str
    street1: str
    city: str
    postal_code: str
    country: str  # ISO 3166-1 alpha-2
    street2: str = ""
    state: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PrintAddressInvalidError("recipient name required")
        if not self.street1.strip():
            raise PrintAddressInvalidError("street1 required")
        if not self.city.strip():
            raise PrintAddressInvalidError("city required")
        if not self.postal_code.strip():
            raise PrintAddressInvalidError("postal_code required")
        if len(self.country) != 2:
            raise PrintAddressInvalidError(
                f"country must be ISO 3166-1 alpha-2, got {self.country!r}"
            )


@dataclass(frozen=True)
class CostBreakdown:
    unit_cost_usd: Decimal
    quantity: int
    shipping_usd: Decimal = Decimal("0")
    tax_usd: Decimal = Decimal("0")
    currency: str = "USD"

    @property
    def subtotal_usd(self) -> Decimal:
        return self.unit_cost_usd * self.quantity

    @property
    def total_usd(self) -> Decimal:
        return self.subtotal_usd + self.shipping_usd + self.tax_usd


@dataclass(frozen=True)
class PrintQuote:
    id: str
    provider: ProviderKind
    document_id: str
    product_kind: ProductKind
    quantity: int
    cost: CostBreakdown
    valid_until: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PrintOrder:
    id: str
    tenant_id: str
    user_id: str
    document_id: str
    provider: ProviderKind
    provider_order_id: str
    product_kind: ProductKind
    quantity: int
    shipping_address: Address
    cost: CostBreakdown
    status: OrderStatus = OrderStatus.SUBMITTED
    quote_id: str = ""
    tracking_url: str | None = None
    isbn: str | None = None
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    submitted_at: datetime | None = None
    fulfilled_at: datetime | None = None


# ---------------------------------------------------------------------------
# Provider validation
# ---------------------------------------------------------------------------


def validate_for_provider(
    *,
    provider: ProviderKind,
    product_kind: ProductKind,
    print_spec: PrintSpec,
    page_count: int,
) -> tuple[str, ...]:
    """Run provider-specific spec checks. Raises PrintProviderRejected on
    fatal mismatches; returns soft warnings as a tuple of strings.

    This sits on top of the generic §22 preflight — preflight gates raster
    DPI / bleed coverage; this gate gates *binding* + provider quirks.
    """
    rules = PROVIDER_RULES[provider]
    if product_kind not in rules.products:
        raise PrintProviderRejectedError(
            f"{rules.name} does not offer product kind {product_kind.value!r}"
        )
    if print_spec.dpi < rules.min_dpi:
        raise PrintProviderRejectedError(
            f"{rules.name} requires DPI ≥ {rules.min_dpi}, got {print_spec.dpi}"
        )
    if print_spec.bleed != rules.bleed_px:
        raise PrintProviderRejectedError(
            f"{rules.name} requires bleed exactly {rules.bleed_px}px, got {print_spec.bleed}"
        )
    if rules.requires_cmyk and print_spec.color_mode.value != "cmyk":
        raise PrintProviderRejectedError(
            f"{rules.name} requires CMYK; got {print_spec.color_mode.value}"
        )
    tw, th = print_spec.trim_size
    max_w, max_h = rules.max_trim_px
    if tw > max_w or th > max_h:
        raise PrintProviderRejectedError(f"{rules.name} max trim {max_w}x{max_h}, got {tw}x{th}")
    warnings: list[str] = []
    is_book = product_kind in (
        ProductKind.PAPERBACK_BOOK,
        ProductKind.HARDCOVER_BOOK,
        ProductKind.PHOTO_BOOK,
    )
    if is_book:
        if page_count < rules.book_min_pages:
            raise PrintProviderRejectedError(
                f"{rules.name} requires ≥ {rules.book_min_pages} pages, got {page_count}"
            )
        if page_count > rules.book_max_pages:
            raise PrintProviderRejectedError(
                f"{rules.name} max {rules.book_max_pages} pages, got {page_count}"
            )
        # Saddle-stitch creep over 64 pages is universally a warning
        if print_spec.binding is BindingKind.SADDLE_STITCH and page_count > 64:
            warnings.append("saddle_stitch_over_64_pages_creep_risk")
    return tuple(warnings)


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


_QUOTE_TTL_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class MockPrintProvider:
    """Deterministic in-memory provider for tests + dev.

    Each provider call records into `calls`. Configurable failure modes
    via `set_unit_cost` + `fail_next_submit`.
    """

    def __init__(
        self,
        *,
        provider: ProviderKind = ProviderKind.LULU,
        unit_cost_usd: Decimal = Decimal("8.00"),
        shipping_usd: Decimal = Decimal("4.99"),
    ) -> None:
        self.provider = provider
        self.calls: list[dict[str, Any]] = []
        self._unit_cost = unit_cost_usd
        self._shipping = shipping_usd
        self._fail_submit_count = 0
        self._order_status: dict[str, OrderStatus] = {}

    def set_unit_cost(self, value: Decimal) -> None:
        self._unit_cost = value

    def fail_next_submit(self, n: int) -> None:
        self._fail_submit_count = n

    async def quote(
        self,
        *,
        document_id: str,
        product_kind: ProductKind,
        quantity: int,
        country: str = "US",
    ) -> PrintQuote:
        self.calls.append(
            {"op": "quote", "document_id": document_id, "qty": quantity, "country": country}
        )
        ship = self._shipping if country == "US" else self._shipping + Decimal("9")
        cost = CostBreakdown(
            unit_cost_usd=self._unit_cost,
            quantity=quantity,
            shipping_usd=ship,
        )
        return PrintQuote(
            id=_new_id(),
            provider=self.provider,
            document_id=document_id,
            product_kind=product_kind,
            quantity=quantity,
            cost=cost,
            valid_until=_now() + timedelta(minutes=_QUOTE_TTL_MINUTES),
        )

    async def submit(
        self,
        *,
        quote: PrintQuote,
        shipping_address: Address,
        export_blob_id: str,
    ) -> str:
        self.calls.append({"op": "submit", "quote_id": quote.id, "blob": export_blob_id})
        if self._fail_submit_count > 0:
            self._fail_submit_count -= 1
            raise PrintProviderError(f"{self.provider.value} mock submit failed")
        if _now() > quote.valid_until:
            raise PrintQuoteExpiredError(
                f"quote {quote.id!r} expired at {quote.valid_until.isoformat()}"
            )
        digest = hashlib.sha256(quote.id.encode()).hexdigest()[:8]
        provider_order_id = f"{self.provider.value}-{digest}"
        self._order_status[provider_order_id] = OrderStatus.SUBMITTED
        return provider_order_id

    async def status(self, provider_order_id: str) -> dict[str, Any]:
        self.calls.append({"op": "status", "id": provider_order_id})
        # Deterministic state machine: SUBMITTED → IN_PRODUCTION → SHIPPED → DELIVERED
        current = self._order_status.get(provider_order_id, OrderStatus.SUBMITTED)
        if current is OrderStatus.SUBMITTED:
            self._order_status[provider_order_id] = OrderStatus.IN_PRODUCTION
            return {"status": OrderStatus.IN_PRODUCTION.value}
        if current is OrderStatus.IN_PRODUCTION:
            self._order_status[provider_order_id] = OrderStatus.SHIPPED
            return {
                "status": OrderStatus.SHIPPED.value,
                "tracking_url": f"https://track.example/{provider_order_id}",
            }
        if current is OrderStatus.SHIPPED:
            self._order_status[provider_order_id] = OrderStatus.DELIVERED
            return {"status": OrderStatus.DELIVERED.value}
        return {"status": current.value}

    async def cancel(self, provider_order_id: str) -> None:
        self.calls.append({"op": "cancel", "id": provider_order_id})
        if provider_order_id not in self._order_status:
            raise PrintProviderError(f"unknown provider_order_id {provider_order_id!r}")
        cur = self._order_status[provider_order_id]
        if cur in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
            raise PrintProviderError(f"cannot cancel order in status {cur.value}")
        self._order_status[provider_order_id] = OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# Order manager
# ---------------------------------------------------------------------------


class InMemoryPrintOrderManager:
    """Tenant-scoped print-order orchestration.

    Wraps any number of `MockPrintProvider` instances behind a single
    `quote → validate → submit → poll` flow. Quotes have TTL; expired
    quotes raise. Cross-tenant access raises PrintOrderNotFoundError.
    """

    def __init__(self) -> None:
        self._orders: dict[str, dict[str, PrintOrder]] = {}
        self._quotes: dict[str, PrintQuote] = {}
        self._providers: dict[ProviderKind, MockPrintProvider] = {}

    def register_provider(self, provider: MockPrintProvider) -> None:
        self._providers[provider.provider] = provider

    async def quote(
        self,
        *,
        provider_kind: ProviderKind,
        document_id: str,
        product_kind: ProductKind,
        quantity: int,
        country: str = "US",
        print_spec: PrintSpec,
        page_count: int,
    ) -> PrintQuote:
        provider = self._provider_or_raise(provider_kind)
        validate_for_provider(
            provider=provider_kind,
            product_kind=product_kind,
            print_spec=print_spec,
            page_count=page_count,
        )
        quote = await provider.quote(
            document_id=document_id,
            product_kind=product_kind,
            quantity=quantity,
            country=country,
        )
        self._quotes[quote.id] = quote
        return quote

    async def submit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        quote_id: str,
        shipping_address: Address,
        export_blob_id: str,
    ) -> PrintOrder:
        quote = self._quotes.get(quote_id)
        if quote is None:
            raise PrintOrderNotFoundError(f"quote {quote_id!r} not found")
        if _now() > quote.valid_until:
            raise PrintQuoteExpiredError(f"quote {quote_id!r} expired")
        provider = self._provider_or_raise(quote.provider)
        provider_order_id = await provider.submit(
            quote=quote,
            shipping_address=shipping_address,
            export_blob_id=export_blob_id,
        )
        order = PrintOrder(
            id=_new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=quote.document_id,
            provider=quote.provider,
            provider_order_id=provider_order_id,
            product_kind=quote.product_kind,
            quantity=quote.quantity,
            shipping_address=shipping_address,
            cost=quote.cost,
            status=OrderStatus.SUBMITTED,
            quote_id=quote_id,
            submitted_at=_now(),
        )
        self._orders.setdefault(tenant_id, {})[order.id] = order
        return order

    async def get(self, order_id: str, *, tenant_id: str) -> PrintOrder:
        bucket = self._orders.get(tenant_id, {})
        if order_id not in bucket:
            raise PrintOrderNotFoundError(f"order {order_id!r} not found")
        return bucket[order_id]

    async def list_for_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        status: OrderStatus | None = None,
    ) -> list[PrintOrder]:
        return [
            o
            for o in self._orders.get(tenant_id, {}).values()
            if o.user_id == user_id and (status is None or o.status is status)
        ]

    async def poll(self, order_id: str, *, tenant_id: str) -> PrintOrder:
        order = await self.get(order_id, tenant_id=tenant_id)
        if order.status in (
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
            OrderStatus.FAILED,
        ):
            return order
        provider = self._provider_or_raise(order.provider)
        upstream = await provider.status(order.provider_order_id)
        new_status = OrderStatus(upstream["status"])
        tracking_url = upstream.get("tracking_url", order.tracking_url)
        fulfilled_at = (
            _now()
            if new_status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED)
            and order.fulfilled_at is None
            else order.fulfilled_at
        )
        updated = dataclasses.replace(
            order,
            status=new_status,
            tracking_url=tracking_url,
            fulfilled_at=fulfilled_at,
        )
        self._orders[tenant_id][order_id] = updated
        return updated

    async def cancel(self, order_id: str, *, tenant_id: str) -> PrintOrder:
        order = await self.get(order_id, tenant_id=tenant_id)
        provider = self._provider_or_raise(order.provider)
        await provider.cancel(order.provider_order_id)
        updated = dataclasses.replace(order, status=OrderStatus.CANCELLED)
        self._orders[tenant_id][order_id] = updated
        return updated

    async def assign_isbn(self, order_id: str, isbn: str, *, tenant_id: str) -> PrintOrder:
        """Optional ISBN allocation hook (P1 — Bowker / provider-side)."""
        order = await self.get(order_id, tenant_id=tenant_id)
        if not _isbn_is_valid(isbn):
            raise PrintProviderRejectedError(f"invalid ISBN {isbn!r}")
        updated = dataclasses.replace(order, isbn=isbn)
        self._orders[tenant_id][order_id] = updated
        return updated

    def _provider_or_raise(self, kind: ProviderKind) -> MockPrintProvider:
        provider = self._providers.get(kind)
        if provider is None:
            raise PrintProviderError(f"no provider registered for {kind.value!r}")
        return provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _isbn_is_valid(isbn: str) -> bool:
    digits = isbn.replace("-", "").replace(" ", "")
    if len(digits) not in (10, 13):
        return False
    return digits[:-1].isdigit()  # last char may be X for ISBN-10


def recommended_provider(
    *,
    doc_kind: DocumentKind,
    product_kind: ProductKind,
    page_count: int,
) -> ProviderKind:
    """Heuristic: pick the cheapest+available provider for the project."""
    candidates: list[ProviderKind] = []
    for kind, rules in PROVIDER_RULES.items():
        if product_kind not in rules.products:
            continue
        if product_kind in (
            ProductKind.PAPERBACK_BOOK,
            ProductKind.HARDCOVER_BOOK,
            ProductKind.PHOTO_BOOK,
        ) and not (rules.book_min_pages <= page_count <= rules.book_max_pages):
            continue
        candidates.append(kind)
    if not candidates:
        raise PrintProviderError(
            f"no provider supports product={product_kind.value!r}, pages={page_count}"
        )
    if doc_kind is DocumentKind.PICTURE_BOOK:
        for preferred in (
            ProviderKind.LULU,
            ProviderKind.BLURB,
            ProviderKind.KDP,
            ProviderKind.GELATO,
        ):
            if preferred in candidates:
                return preferred
    if product_kind is ProductKind.POSTER:
        for preferred in (ProviderKind.PRINTFUL, ProviderKind.GELATO):
            if preferred in candidates:
                return preferred
    return candidates[0]
