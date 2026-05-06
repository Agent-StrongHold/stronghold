"""Print-on-Demand integration tests — features/print-on-demand.feature."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from stronghold.tools.canvas_print_on_demand import (
    PROVIDER_RULES,
    Address,
    InMemoryPrintOrderManager,
    MockPrintProvider,
    OrderStatus,
    ProductKind,
    ProviderKind,
    recommended_provider,
    validate_for_provider,
)
from stronghold.types.canvas_design import (
    BindingKind,
    ColorMode,
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

# ─── Fixtures ──────────────────────────────────────────────────────────────


def _picture_book_spec() -> PrintSpec:
    return PrintSpec(trim_size=(2400, 2400), bleed=38, safe_area=75, dpi=300)


def _us_address() -> Address:
    return Address(
        name="Alice Smith",
        street1="123 Main St",
        city="Austin",
        postal_code="78701",
        country="US",
        state="TX",
    )


def _eu_address() -> Address:
    return Address(
        name="Erik Hansen",
        street1="Strandvejen 12",
        city="Copenhagen",
        postal_code="2100",
        country="DK",
    )


# ─── Address validation ────────────────────────────────────────────────────


class TestAddress:
    def test_valid_address_constructs(self) -> None:
        addr = _us_address()
        assert addr.country == "US"

    def test_missing_name_rejected(self) -> None:
        with pytest.raises(PrintAddressInvalidError):
            Address(
                name="  ",
                street1="x",
                city="x",
                postal_code="x",
                country="US",
            )

    def test_missing_street_rejected(self) -> None:
        with pytest.raises(PrintAddressInvalidError):
            Address(
                name="x",
                street1="",
                city="x",
                postal_code="x",
                country="US",
            )

    def test_country_must_be_two_chars(self) -> None:
        with pytest.raises(PrintAddressInvalidError):
            Address(
                name="x",
                street1="x",
                city="x",
                postal_code="x",
                country="USA",  # 3-letter
            )


# ─── Per-provider validation ───────────────────────────────────────────────


class TestProviderValidation:
    def test_lulu_picture_book_valid(self) -> None:
        warnings = validate_for_provider(
            provider=ProviderKind.LULU,
            product_kind=ProductKind.PAPERBACK_BOOK,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        assert warnings == ()

    def test_kdp_rejects_unsupported_product(self) -> None:
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.KDP,
                product_kind=ProductKind.POSTER,
                print_spec=_picture_book_spec(),
                page_count=32,
            )

    def test_below_min_dpi_rejected(self) -> None:
        spec = PrintSpec(trim_size=(2400, 2400), bleed=38, dpi=150)
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.LULU,
                product_kind=ProductKind.PAPERBACK_BOOK,
                print_spec=spec,
                page_count=32,
            )

    def test_wrong_bleed_rejected(self) -> None:
        spec = PrintSpec(trim_size=(2400, 2400), bleed=10, safe_area=20)
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.LULU,
                product_kind=ProductKind.PAPERBACK_BOOK,
                print_spec=spec,
                page_count=32,
            )

    def test_too_few_pages_rejected(self) -> None:
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.KDP,
                product_kind=ProductKind.PAPERBACK_BOOK,
                print_spec=_picture_book_spec(),
                page_count=8,
            )

    def test_too_many_pages_rejected(self) -> None:
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.BLURB,
                product_kind=ProductKind.PHOTO_BOOK,
                print_spec=_picture_book_spec(),
                page_count=500,
            )

    def test_oversize_trim_rejected(self) -> None:
        spec = PrintSpec(trim_size=(8000, 11000), bleed=38)
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.KDP,
                product_kind=ProductKind.PAPERBACK_BOOK,
                print_spec=spec,
                page_count=32,
            )

    def test_ingramspark_requires_cmyk(self) -> None:
        spec = PrintSpec(trim_size=(2400, 2400), bleed=38, color_mode=ColorMode.SRGB)
        with pytest.raises(PrintProviderRejectedError):
            validate_for_provider(
                provider=ProviderKind.INGRAMSPARK,
                product_kind=ProductKind.PAPERBACK_BOOK,
                print_spec=spec,
                page_count=32,
            )

    def test_saddle_stitch_creep_warning(self) -> None:
        spec = PrintSpec(
            trim_size=(2400, 2400),
            bleed=38,
            binding=BindingKind.SADDLE_STITCH,
        )
        warnings = validate_for_provider(
            provider=ProviderKind.LULU,
            product_kind=ProductKind.PAPERBACK_BOOK,
            print_spec=spec,
            page_count=80,
        )
        assert "saddle_stitch_over_64_pages_creep_risk" in warnings


# ─── Quote → submit flow ───────────────────────────────────────────────────


async def _setup() -> tuple[InMemoryPrintOrderManager, MockPrintProvider]:
    manager = InMemoryPrintOrderManager()
    provider = MockPrintProvider(provider=ProviderKind.LULU)
    manager.register_provider(provider)
    return manager, provider


class TestQuote:
    async def test_quote_returns_pricing(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=5,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        assert quote.cost.quantity == 5
        assert quote.cost.subtotal_usd == Decimal("8.00") * 5
        assert quote.valid_until > datetime.now(UTC)

    async def test_quote_country_affects_shipping(self) -> None:
        manager, _ = await _setup()
        us = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            country="US",
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        eu = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            country="DK",
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        assert eu.cost.shipping_usd > us.cost.shipping_usd

    async def test_quote_validates_against_provider_rules(self) -> None:
        manager, _ = await _setup()
        with pytest.raises(PrintProviderRejectedError):
            await manager.quote(
                provider_kind=ProviderKind.LULU,
                document_id="D1",
                product_kind=ProductKind.POSTER,  # Lulu doesn't ship posters
                quantity=1,
                print_spec=_picture_book_spec(),
                page_count=32,
            )

    async def test_quote_unknown_provider_raises(self) -> None:
        manager = InMemoryPrintOrderManager()
        with pytest.raises(PrintProviderError):
            await manager.quote(
                provider_kind=ProviderKind.LULU,
                document_id="D1",
                product_kind=ProductKind.PAPERBACK_BOOK,
                quantity=1,
                print_spec=_picture_book_spec(),
                page_count=32,
            )


class TestSubmit:
    async def test_submit_creates_order(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=3,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob-pdf-1",
        )
        assert order.status is OrderStatus.SUBMITTED
        assert order.provider_order_id.startswith("lulu-")
        assert order.shipping_address.country == "US"
        assert order.cost.quantity == 3

    async def test_submit_with_unknown_quote_raises(self) -> None:
        manager, _ = await _setup()
        with pytest.raises(PrintOrderNotFoundError):
            await manager.submit(
                tenant_id="acme",
                user_id="alice",
                quote_id="missing",
                shipping_address=_us_address(),
                export_blob_id="blob",
            )

    async def test_submit_provider_failure_raises(self) -> None:
        manager, provider = await _setup()
        provider.fail_next_submit(1)
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        with pytest.raises(PrintProviderError):
            await manager.submit(
                tenant_id="acme",
                user_id="alice",
                quote_id=quote.id,
                shipping_address=_us_address(),
                export_blob_id="blob",
            )

    async def test_expired_quote_raises(self) -> None:
        # Force an expired quote by inspecting and replacing valid_until
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        # Replace stored quote with an expired one
        import dataclasses

        manager._quotes[quote.id] = dataclasses.replace(  # noqa: SLF001
            quote, valid_until=datetime.now(UTC) - timedelta(minutes=1)
        )
        with pytest.raises(PrintQuoteExpiredError):
            await manager.submit(
                tenant_id="acme",
                user_id="alice",
                quote_id=quote.id,
                shipping_address=_us_address(),
                export_blob_id="blob",
            )


class TestPolling:
    async def test_status_progression(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob",
        )
        # SUBMITTED → IN_PRODUCTION
        in_prod = await manager.poll(order.id, tenant_id="acme")
        assert in_prod.status is OrderStatus.IN_PRODUCTION
        # → SHIPPED with tracking
        shipped = await manager.poll(order.id, tenant_id="acme")
        assert shipped.status is OrderStatus.SHIPPED
        assert shipped.tracking_url is not None
        assert shipped.fulfilled_at is not None
        # → DELIVERED
        delivered = await manager.poll(order.id, tenant_id="acme")
        assert delivered.status is OrderStatus.DELIVERED


class TestCancellation:
    async def test_cancel_in_production(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob",
        )
        cancelled = await manager.cancel(order.id, tenant_id="acme")
        assert cancelled.status is OrderStatus.CANCELLED

    async def test_cannot_cancel_after_shipping(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob",
        )
        # Walk to SHIPPED
        await manager.poll(order.id, tenant_id="acme")  # → IN_PRODUCTION
        await manager.poll(order.id, tenant_id="acme")  # → SHIPPED
        with pytest.raises(PrintProviderError):
            await manager.cancel(order.id, tenant_id="acme")


class TestTenantIsolation:
    async def test_cross_tenant_get_raises(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="globex",
            user_id="bob",
            quote_id=quote.id,
            shipping_address=_eu_address(),
            export_blob_id="blob",
        )
        with pytest.raises(PrintOrderNotFoundError):
            await manager.get(order.id, tenant_id="acme")

    async def test_list_for_user_filters_status(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob",
        )
        # Just-submitted listing, filter to SUBMITTED
        listing = await manager.list_for_user(
            tenant_id="acme", user_id="alice", status=OrderStatus.SUBMITTED
        )
        assert len(listing) == 1


class TestIsbn:
    async def test_assign_valid_isbn_13(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob",
        )
        with_isbn = await manager.assign_isbn(order.id, "978-3-16-148410-0", tenant_id="acme")
        assert with_isbn.isbn == "978-3-16-148410-0"

    async def test_invalid_isbn_rejected(self) -> None:
        manager, _ = await _setup()
        quote = await manager.quote(
            provider_kind=ProviderKind.LULU,
            document_id="D1",
            product_kind=ProductKind.PAPERBACK_BOOK,
            quantity=1,
            print_spec=_picture_book_spec(),
            page_count=32,
        )
        order = await manager.submit(
            tenant_id="acme",
            user_id="alice",
            quote_id=quote.id,
            shipping_address=_us_address(),
            export_blob_id="blob",
        )
        with pytest.raises(PrintProviderRejectedError):
            await manager.assign_isbn(order.id, "bogus-isbn", tenant_id="acme")


# ─── Provider recommendation ───────────────────────────────────────────────


class TestRecommendedProvider:
    def test_picture_book_prefers_lulu(self) -> None:
        recommendation = recommended_provider(
            doc_kind=DocumentKind.PICTURE_BOOK,
            product_kind=ProductKind.PAPERBACK_BOOK,
            page_count=32,
        )
        assert recommendation is ProviderKind.LULU

    def test_poster_prefers_printful(self) -> None:
        recommendation = recommended_provider(
            doc_kind=DocumentKind.POSTER,
            product_kind=ProductKind.POSTER,
            page_count=1,
        )
        assert recommendation is ProviderKind.PRINTFUL

    def test_no_provider_available_raises(self) -> None:
        with pytest.raises(PrintProviderError):
            recommended_provider(
                doc_kind=DocumentKind.PICTURE_BOOK,
                product_kind=ProductKind.PAPERBACK_BOOK,
                page_count=2_000,  # exceeds every provider's max
            )


class TestProviderCatalogue:
    def test_all_providers_have_rules(self) -> None:
        for kind in ProviderKind:
            assert kind in PROVIDER_RULES

    def test_book_providers_have_gutter(self) -> None:
        for kind in (ProviderKind.LULU, ProviderKind.KDP, ProviderKind.BLURB):
            assert PROVIDER_RULES[kind].gutter_min_px > 0

    def test_poster_provider_has_no_gutter(self) -> None:
        assert PROVIDER_RULES[ProviderKind.PRINTFUL].gutter_min_px == 0
