# 29 — Marketplace (Reach)

**Status**: REACH / Phase 7. Distribute books to readers; share templates
across users.
**One-liner**: a tenant-/community-scoped marketplace for finished kids'
books (read-online or ePub download), reusable templates, character refs,
and brand kits.

## Two distinct surfaces

### Reader marketplace (P0 of phase 7)

For finished children's books: the user publishes a Document; readers
discover, read in browser, or download ePub.

| Item | What |
|---|---|
| Visibility | tenant / community / public per item |
| Reader UX | book reader with page-flip / read-along audio (§27) |
| Discovery | tags, categories, search, ratings |
| Monetization | optional: pay-per-download / subscription / free |
| Rights | author retains; platform license non-exclusive |

### Creator marketplace (P1 of phase 7)

For templates, brand kits, character refs, prop assets:

| Item | What |
|---|---|
| Trust tier gating | community items start at T4 (not auto-importable) |
| Review process | platform AI review + optional admin review |
| Attribution | original creator credited; usage tracked |
| Forking | items can be forked (with attribution) and re-published |

## Cross-cutting concerns

- **Content moderation**: Warden + Sentinel + community-flagging pipeline.
  Children's content held to higher bar.
- **Copyright**: DMCA-style takedown flow (P1)
- **Tenant isolation by default**; opt-in for cross-tenant visibility
- **Rev share** (if monetized): platform fee, creator share

## Data model (sketch)

```
Listing (frozen):
  id, tenant_id, owner_id
  kind: BOOK | TEMPLATE | CHARACTER_REF | PROP | BRAND_KIT
  source_id                          # the Document / Template / Asset
  title, description, tags
  visibility: TENANT | COMMUNITY | PUBLIC
  monetization: FREE | ONE_TIME_PRICE | SUBSCRIPTION
  price_usd: Decimal | None
  ratings_count, ratings_avg
  downloads, views
  status: DRAFT | PUBLISHED | TAKEN_DOWN
  trust_tier: TrustTier
  created_at, published_at, taken_down_at
```

## API surface (sketch)

`listing_create / listing_publish / listing_search / listing_install /
listing_rate / listing_takedown / listing_fork`.

## Edge cases (sketch)

- Mass-download abuse → rate limits per IP / per user
- Inappropriate content slipping past Warden → community-flag pipeline
- Forked template breaking on re-import → migration helpers
- Author deletes account with published listings → grace period; readers
  who installed retain copies

## Detailed design deferred to phase 7. Stub provided for completeness.

## Dependencies

- §11 templates, §17 template authoring, §18 asset library, §27 audio,
  §13 export, existing tenancy + auth
