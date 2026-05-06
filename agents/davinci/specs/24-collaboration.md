# 24 — Collaboration (Reach Goal)

**Status**: REACH / Phase 7. After single-author shipping.
**One-liner**: read-only sharing links, comment threads on layers,
approval workflow; no real-time multi-cursor.

## Out of scope (explicit)

- Real-time multi-cursor like Figma — explicit non-goal
- Branch + merge of edits — single canonical version per Document
- Public marketplace listings — separate spec (§29)

## In scope

- **Read-only share link**: tenant + non-tenant viewers, optional expiry
- **Layer comments**: thread per layer, mentions, resolved state
- **Approval workflow**: draft → review → approved → published states
- **Co-author add**: another tenant member can edit; lock per Page during
  active edit; audit log all changes

## Data model (sketch)

```
ShareLink (frozen):
  id: str
  document_id: str
  scope: ShareScope                # READ | COMMENT | EDIT
  expires_at: datetime | None
  password_hash: str | None
  audience: ShareAudience          # TENANT | EXTERNAL
  created_by, created_at

Comment (frozen):
  id, document_id, page_id, layer_id, parent_comment_id
  author_id, content, created_at, resolved_at

ApprovalState (frozen):
  document_id, status: DRAFT|IN_REVIEW|APPROVED|PUBLISHED|ARCHIVED
  reviewers: tuple[str, ...]
  approved_at, published_at
```

## API surface (sketch)

`share_link_create / share_link_revoke / share_link_list /
comment_add / comment_resolve / comment_thread / approval_request /
approval_grant / approval_publish`.

## Edge cases (sketch)

- Expired share link → 404
- Comment on a deleted layer → preserved with "(deleted layer)" tombstone
- Non-tenant viewer interacting with cost-gated UI → blocked with clear message
- Approval after edits → re-request approval

## Detailed design deferred to phase 7. Stub provided for completeness.

## Dependencies

- §02 document, §16 ui-ux, existing auth + audit
