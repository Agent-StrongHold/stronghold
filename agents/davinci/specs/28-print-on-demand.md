# 28 — Print-on-Demand Integration (Reach)

**Status**: REACH / Phase 7. Ship physical books and posters.
**One-liner**: order printed copies of a Document via Lulu / KDP / Blurb /
Printful adapters; spec verification per service; cost preview; ISBN /
fulfilment.

## Providers (P-level)

| Provider | Products | P-level |
|---|---|---|
| **Lulu** | books, photo books | P0 (best book API) |
| **Amazon KDP** | books (paperback/hardcover), KDP Print | P1 (less open API; semi-manual) |
| **Blurb** | premium photo books, magazines | P1 |
| **Printful** | posters, canvas prints, art prints | P0 |
| **Gelato** | global poster + book network | P1 |
| **IngramSpark** | wider distribution | P2 |

## Flow

```
1. SPEC VERIFY     run print-spec preflight against provider's strict requirements
2. EXPORT          generate provider-required PDF + cover separately (book) or
                   high-res PNG/PDF (poster)
3. PRICE PREVIEW   provider quote with shipping
4. ORDER           submit order via API
5. TRACK           webhook updates from provider
6. ISBN ALLOC      (optional, P1) automatic ISBN allocation via Bowker / provider
7. STOREFRONT      (optional, P2) own storefront link
```

## Provider-specific verification

Each provider has stricter pre-flight rules than generic print spec (§22):
- Lulu: gutter margin >= 0.5", trim sizes from approved list, cover spine
  width formula
- Printful: bleed exact, no transparency in PDF, specific colour profile
- KDP: image resolution + barcode placement requirements

These rules extend §22's preflight via per-provider adapters.

## Data model (sketch)

```
PrintOrder (frozen):
  id, tenant_id, user_id, document_id
  provider: ProviderKind
  provider_order_id: str
  product_kind: PRODUCT_BOOK | PRODUCT_POSTER | ...
  quantity: int
  shipping_address: Address (encrypted at rest)
  status: PrintOrderStatus
  cost_breakdown: CostBreakdown
  tracking_url: str | None
  created_at, submitted_at, fulfilled_at
```

## API surface (sketch)

`provider_quote / provider_validate / provider_order / provider_track /
isbn_allocate`

## Edge cases

- Provider API down → retry; surface user-friendly status
- Provider rejects spec → surface details + auto-fix suggestion (e.g. "spine
  width 0.04" too thin; needs ≥ 24 pages or saddle-stitch")
- Address validation per locale
- Refund / cancellation windows per provider
- Provider price changes between quote and order → re-quote required

## Detailed design deferred to phase 7. Stub provided for completeness.

## Dependencies

- §08 print spec, §13 export, §31 cost gate, §22 preflight
- Provider SDKs / direct REST
