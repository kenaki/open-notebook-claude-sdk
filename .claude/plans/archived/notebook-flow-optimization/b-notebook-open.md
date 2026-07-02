# Notebook Flow Optimization — Track B: Notebook open

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, the cross-track conflict map — then execute this track's chunks here, one
> per session. You should never need to open another track's file.
> **Location:** `.claude/plans/notebook-flow-optimization/b-notebook-open.md` → archived with the
> directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none. **Concurrent with:** A, C, D (run anytime).
**State at handoff (2026-06-23):** planning complete, no code yet.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Notebook Flow Optimization Track B. Read
> `.claude/plans/notebook-flow-optimization/coordinator.md` then `b-notebook-open.md` in full.
> Implement the next unstarted chunk (one only), verify it, then update BOTH this file's Status table
> AND the coordinator's Global status table + Changelog, and tell me when it's safe to clear context.
> If that was the last chunk of the last track, archive the feature directory per the coordinator's
> Completion section.

## This track's file ownership
Files this track creates/modifies:
- `frontend/src/app/(dashboard)/notebooks/components/NotebookCard.tsx`
- `frontend/src/app/(dashboard)/notebooks/components/NotebookRow.tsx`
- `frontend/src/lib/hooks/use-notebooks.ts`
- `frontend/src/app/(dashboard)/notebooks/[id]/page.tsx`
- `frontend/src/app/(dashboard)/notebooks/[id]/chat/[chatId]/page.tsx`
- `frontend/src/app/(dashboard)/notebooks/[id]/layout.tsx`
- `frontend/src/components/layout/AppShell.tsx`
- `frontend/src/components/notebooks/NotebookWorkspaceProvider.tsx`
- NEW: a page-level gallery skeleton component (e.g. `components/notebooks/GallerySkeleton.tsx`)
Shared files I must NOT touch: `ChatGallery.tsx` (Track A — do **not** add intra-gallery skeletons
there; B2 uses a page-level skeleton instead), `query-client.ts` (Track C). **Convention:** B1 prefetch
must use `QUERY_KEYS.sourcesInfinite(nbId)` (the canonical key C keeps), never `QUERY_KEYS.sources`.

## Per-chunk workflow
read referenced files → implement → verify (`cd frontend && npm run typecheck`) → mark ☑ here AND in
the coordinator → note new Open Questions → announce "✅ Chunk B.n complete — safe to clear context"
→ stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| B1 | Prefetch-on-intent + cache-seed | ☑ done | Track B / 2026-06-23 | `useNotebookPrefetch()` in use-notebooks.ts (prefetch+seed); wired into NotebookCard (hover/focus + seed-on-click) & NotebookRow (row hover + Link focus/seed). Uses `sourcesInfinite` canonical key. tsc+eslint clean. |
| B2 | Render shell + skeleton (kill spinner flash) | ☑ done | Track B / 2026-06-23 | New `GallerySkeleton.tsx`; both notebook pages now render `<AppShell><GallerySkeleton/></AppShell>` on cold open instead of a full-screen spinner outside the shell. tsc+eslint clean. |
| B3 | Notebook-open error/retry state | ☑ done | Track B / 2026-06-23 | Provider surfaces `notebookNotFound`/`notebookFetchError`/`refetchNotebook` (404 vs transient via axios `response.status`); both pages branch transient-error → retry card, 404 → not-found. New `notebooks.loadError`/`loadErrorDesc` keys in all 14 locales. tsc+eslint clean. |
| B4 | Fix dataError loading/error conflation | ☑ done | Track B / 2026-06-23 | `dataError` now derives from real query flags (`!!sourcesError \|\| notesIsError`) instead of `!sources && !notes` (which was always false since `sources` is `?? []`). Empty notebook → empty state, loading → skeleton, only a true fetch error fires the ChatColumn error UI. Retry handler `refetchSources` already exposed; wiring a retry button into ChatColumn is Track A's (ChatColumn not a B file). tsc+eslint clean. |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

**Track B COMPLETE — all chunks ☑.**

## Changelog (this track)
- **B4 (2026-06-23):** Fixed the `dataError` loading/error conflation in
  `NotebookWorkspaceProvider`. The old derivation `dataError: !sources && !notes` was effectively
  **dead** — `useNotebookSources` returns `sources` as `?? []` (always a truthy array), so `!sources`
  is always false and `dataError` could never be true. It now derives from the real TanStack Query
  error flags: `const dataError = !!sourcesError || notesIsError` (destructured `error: sourcesError`
  from `useNotebookSources` and `isError: notesIsError` from `useNotes` — both already exposed, no
  cross-track hook edits). Result: a still-loading notebook renders the B2 skeleton (not error), an
  empty notebook renders the empty state (both queries succeed with empty data → `isError` false), and
  only a genuine fetch failure trips the `ChatColumn` error UI (consumed via the `error={dataError}`
  prop in `DeepDiveWorkspace`). The recovery handler is already on the workspace value
  (`refetchSources`); adding an actual "Try again" button inside `ChatColumn`'s error card is left to
  Track A since `ChatColumn.tsx`/`DeepDiveWorkspace.tsx` are not Track B files (B4 spec marks ChatColumn
  reference-only). Updated the interface doc comment + the `value` memo deps. Verified: `npx tsc
  --noEmit` + `eslint` both clean. **Track B is now COMPLETE (B1–B4 all ☑).**
- **B3 (2026-06-23):** A failed notebook fetch no longer renders the misleading "Notebook not found"
  screen with no recovery. `NotebookWorkspaceProvider` now destructures `isError`/`error`/`refetch`
  from `useNotebook` and derives two flags from the axios `response.status`: `notebookNotFound`
  (status 404 → genuine not-found) and `notebookFetchError` (any other error → transient/recoverable).
  Both flags + `refetchNotebook` are exposed on the workspace value. Both `[id]/page.tsx` and
  `[id]/chat/[chatId]/page.tsx` branch their `!notebook` case: `notebookFetchError` → a calm inline
  error card (`notebooks.loadError`/`loadErrorDesc` + a "Try Again" `Button` calling `refetchNotebook()`);
  otherwise → the existing "Notebook not found". Added `notebooks.loadError`/`loadErrorDesc` to `en-US`
  and mirrored (localized) into the other 13 locales; reused `common.retry` for the button. The inline
  card stays calm by design — Track C1's global handler already toasts the transient failure, so this is
  the recovery affordance, not a second alarm. Verified: `npx tsc --noEmit` + eslint both clean.
- **B2 (2026-06-23):** Killed the full-screen spinner that rendered *outside* `AppShell` on cold
  notebook open (the shell/sidebar vanished then snapped back). New page-level
  `components/notebooks/GallerySkeleton.tsx` — a coarse `animate-pulse` placeholder mirroring the
  gallery shape (header bar + title/toolbar + 6-card grid), kept out of `ChatGallery.tsx` so that
  file stays owned by Track A. Both `[id]/page.tsx` and `[id]/chat/[chatId]/page.tsx` now return
  `<AppShell><GallerySkeleton/></AppShell>` while `notebookLoading`, so the chrome always stays
  mounted and only the content area swaps. Removed the now-unused `LoadingSpinner` import from both
  pages. Verified: `npx tsc --noEmit` + eslint both clean.
- **B1 (2026-06-23):** Added `useNotebookPrefetch()` to `use-notebooks.ts` exposing `prefetch(id)`
  (notebook meta + sources page-1 infinite + notes + chat sessions, mirroring the workspace hooks'
  query fns/keys; uses canonical `QUERY_KEYS.sourcesInfinite`) and `seed(notebook)` (`setQueryData`
  with `old ?? notebook`, never clobbering a fuller entry). Wired into `NotebookCard`
  (`onMouseEnter`/`onFocus` → prefetch, seed before `router.push`) and `NotebookRow` (row
  `onMouseEnter` → prefetch, `seed` in row click + name `<Link>` click, `<Link>` `onFocus` → prefetch
  for keyboard users). All four prefetch queries carry `meta:{silent:true}` so the C1 global
  query-error handler stays quiet on speculative warm-ups. Verified: `npx tsc --noEmit` (no `typecheck`
  script exists) + eslint both clean.

## Chunks (verbatim — do not require another track file)

### Chunk B1 — Prefetch-on-intent + cache-seed
- **Goal:** Opening a notebook starts warm. On hover/focus of a notebook card, prefetch its data; on
  click, seed the notebook metadata into cache from the list so the title renders instantly and the
  loading gate is more likely to be skipped.
- **Read first:** `NotebookCard.tsx` (`onClick`→`router.push` :39-41), `NotebookRow.tsx` (:40-42, name
  `<Link>` :56-62), `use-notebooks.ts` (`useNotebook` :16-22, `useNotebooks`),
  `NotebookWorkspaceProvider.tsx` (which queries run on open :101-110). Reference prefetch usage in
  `GeneratePodcastDialog.tsx` (the only existing `prefetchQuery` precedent).
- **Spec / exact values:** Keys — `QUERY_KEYS.notebook(id)`, `QUERY_KEYS.sourcesInfinite(nbId)`,
  `QUERY_KEYS.notes(nbId)`, `QUERY_KEYS.notebookChatSessions(nbId)`. Use the SAME query fns the
  workspace hooks use so the cache entries are interchangeable.
- **Reuse:** `queryClient.prefetchQuery` / `prefetchInfiniteQuery`; `queryClient.setQueryData` for the
  cache-seed; existing resource API fns (`notebooksApi`, `sourcesApi`, `notesApi`, `chatApi`).
- **Steps:**
  1. Add `onMouseEnter`/`onFocus` handlers to `NotebookCard` and `NotebookRow` that prefetch the
     notebook + sources(infinite) + notes + chat sessions for that id. Guard against duplicate
     prefetch (prefetchQuery is a no-op if fresh, fine).
  2. On click (before `router.push`), `setQueryData(QUERY_KEYS.notebook(id), notebook)` using the
     notebook object already present in the list item — so the metadata gate is pre-satisfied.
  3. Keep prefetch lightweight: only page 1 of sources; don't prefetch heavy per-session messages
     beyond the most-recent session list.
- **Verify:** With cache cleared, hover a card for ~300ms then click — the notebook title shows with no
  spinner and sources/notes are already populating (Network shows requests fired on hover, not click).
  Typecheck passes.

### Chunk B2 — Render shell + skeleton (kill spinner flash)
- **Goal:** Eliminate the full-screen spinner rendered **outside** `AppShell` on cold open (the
  shell/sidebar vanish then snap back). Render the app chrome immediately and show a page-level
  skeleton in the content area while data loads.
- **Read first:** `[id]/page.tsx` (`notebookLoading` gate :24-30, not-found :33-39),
  `[id]/chat/[chatId]/page.tsx` (same spinner pattern :22-28), `AppShell.tsx` (flex row :13-21),
  `[id]/layout.tsx` (keyed by notebookId :23), `NotebookWorkspaceProvider.tsx` (`notebookLoading`).
- **Spec / exact values:** The spinner is currently `min-h-screen flex items-center justify-center`
  OUTSIDE the shell. Goal: shell always mounts; only the inner content swaps to a skeleton.
- **Reuse:** existing `Skeleton` primitive in `components/ui/` if present; otherwise simple animated
  placeholder blocks (keep it a NEW `GallerySkeleton.tsx` so `ChatGallery.tsx` stays owned by Track A).
- **Steps:**
  1. Move the loading branch so the page always renders within `AppShell`/chrome; when
     `notebookLoading`, render `<GallerySkeleton/>` in the content slot instead of the full-screen
     spinner. Do the same for the chat `[chatId]/page.tsx` (a deep-dive skeleton or reuse the gallery
     one).
  2. Create `GallerySkeleton.tsx` — coarse placeholder matching the gallery grid (a header bar + a few
     card placeholders). Do not edit `ChatGallery.tsx`.
  3. Confirm no layout shift: sidebar/shell stay put across the transition.
- **Verify:** Cold-open a not-recently-visited notebook — the sidebar/shell never disappear; a skeleton
  fills the content area, then real content replaces it with no shell flash. Typecheck passes.

### Chunk B3 — Notebook-open error/retry state
- **Goal:** A failed notebook fetch (500/network) shows a real error + retry, not the misleading
  "Notebook not found" screen with no recovery.
- **Read first:** `[id]/page.tsx` (not-found branch :33-39), `use-notebooks.ts` (`useNotebook` :16-22
  — currently no `isError` surfaced), `NotebookWorkspaceProvider.tsx`.
- **Spec / exact values:** Distinguish three states: loading (skeleton from B2), **error** (transient
  failure → retry), and genuine **not-found** (404 → keep current message). `useNotebook` exposes
  `isError`/`error`/`refetch` from TanStack Query.
- **Reuse:** existing `ConnectionErrorOverlay`/`ChatColumn` error pattern as a style reference;
  `getApiErrorMessage`. Note the coordinator convention: Track C's global handler will also toast query
  errors — that's fine; this chunk adds the inline retry UI. Avoid an alarmist double-message by keeping
  the inline UI calm (the toast is the transient notice, the inline panel is the recovery).
- **Steps:**
  1. Surface `isError`/`error`/`refetch` from the workspace provider for the notebook query (add to its
     return value if not already there — provider is owned by this track).
  2. In `page.tsx`, branch: 404-shaped error → existing "Notebook not found"; other error → an inline
     error card with a "Try again" button calling `refetch()`. Apply the same to the chat page.
- **Verify:** Force a 500 on the notebook endpoint — page shows an error card with a working "Try
  again"; force a 404 — shows "not found". Typecheck passes.

### Chunk B4 — Fix dataError loading/error conflation
- **Goal:** `dataError` must mean "a fetch genuinely failed," not "data is still undefined." Today
  `dataError: !sources && !notes` (NotebookWorkspaceProvider.tsx:226) is true during normal initial
  load and for empty notebooks, so the well-built `ChatColumn` error UI rarely fires correctly and can
  misfire.
- **Read first:** `NotebookWorkspaceProvider.tsx` (`dataError` :226, the source/notes/chat hooks
  :101-110), `ChatColumn.tsx` (error UI :46-59 — for reference only; do not edit, it's consumed via
  props this track provides).
- **Spec / exact values:** Derive from real flags: `dataError = sourcesQuery.isError || notesQuery.isError`
  (and/or sessions), NOT from `!data`. Pass a `refetch`/retry handler alongside it so the existing
  `ChatColumn` error UI can offer recovery.
- **Reuse:** the `isError`/`refetch` already exposed by `use-sources`/`use-notes` hooks.
- **Steps:**
  1. Replace the `!sources && !notes` derivation with an `isError`-based one.
  2. Pass a retry callback through to consumers so the error UI's recovery actually refetches.
  3. Confirm empty notebooks now render the empty state (not the error state) and still-loading renders
     the skeleton (B2), not the error state.
- **Verify:** Empty notebook → empty state; loading → skeleton; forced sources 500 → `ChatColumn` error
  UI with working retry. Typecheck passes.

## Open Questions (this track)
- **Q-B1-trigger** — Prefetch on hover/focus only, or also in-viewport (IntersectionObserver)? Default:
  hover/focus only (cheapest, avoids prefetching the whole list). In-viewport deferred.
- **Q-B2-skeleton-fidelity** — Page-level coarse skeleton vs. card-accurate skeletons inside the
  gallery. Default: page-level coarse skeleton in a NEW component (keeps `ChatGallery.tsx` owned by
  Track A; avoids a cross-track file conflict). Intra-gallery skeletons deferred.
