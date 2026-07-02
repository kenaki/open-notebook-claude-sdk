# Notebook Flow Optimization — Track C: Errors & cache

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, the cross-track conflict map — then execute this track's chunks here, one
> per session. You should never need to open another track's file.
> **Location:** `.claude/plans/notebook-flow-optimization/c-errors-cache.md` → archived with the
> directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none. **Concurrent with:** A, B, D (run anytime).
**State at handoff (2026-06-23):** planning complete, no code yet.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Notebook Flow Optimization Track C. Read
> `.claude/plans/notebook-flow-optimization/coordinator.md` then `c-errors-cache.md` in full.
> Implement the next unstarted chunk (one only), verify it, then update BOTH this file's Status table
> AND the coordinator's Global status table + Changelog, and tell me when it's safe to clear context.
> If that was the last chunk of the last track, archive the feature directory per the coordinator's
> Completion section.

## This track's file ownership
Files this track creates/modifies:
- `frontend/src/lib/api/query-client.ts`
- `frontend/src/lib/hooks/use-sources.ts`
- `frontend/src/lib/hooks/use-notes.ts`
- `frontend/src/app/(dashboard)/notebooks/.../AddExistingSourceDialog.tsx` (the consumer of the
  redundant `useSources` key — confirm exact path during the chunk)
- `frontend/CLAUDE.md`, `frontend/src/CLAUDE.md`, `frontend/src/lib/hooks/CLAUDE.md` (doc drift)
Shared files I must NOT touch: chat files (Track A), notebook page/provider (Track B), animation files
(Track D). **Convention:** the global error handler (C1) must fire on **query** errors only — do not
make it toast mutation errors (A/B/C mutations already toast). When you unify the source key (C2), keep
`QUERY_KEYS.sourcesInfinite` as canonical so Track B's prefetch stays valid.

## Per-chunk workflow
read referenced files → implement → verify (`cd frontend && npm run typecheck`) → mark ☑ here AND in
the coordinator → note new Open Questions → announce "✅ Chunk C.n complete — safe to clear context"
→ stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| C1 | Global React Query error handler | ☑ done | Track C session 2026-06-23 | `QueryCache.onError` added; toasts query errors via `getApiErrorMessage(err, i18n.t)`; `meta.silent` opts out (prefetch/polling); mutations untouched. |
| C2 | Unify duplicate source query keys | ☑ done | Track C 2026-06-23 | `AddExistingSourceDialog` now reads canonical `useNotebookSources` (infinite cache); dead `useSources` hook removed. `QUERY_KEYS.sources` KEPT — still read by `GeneratePodcastDialog` (multi-notebook). |
| C3 | Narrow broad invalidations | ☑ done | Track C 2026-06-23 | Add/remove-to-notebook scoped to `sourcesInfinite(nbId)`+`sources(nbId)`+`source(id)` (dropped broad `['sources']`); dead no-arg `sources()` invalidation removed from `useCreateSource`. Update/delete/retry/deleteNote KEPT broad (no nb id in their variables — sanctioned fallback). |
| C4 | Fix CLAUDE.md doc drift | ☑ done | Track C 2026-06-23 | Corrected `refetchOnWindowFocus` (global `false`; only `use-sources.ts` opts in) + the blanket "optimistic updates" claim (it's invalidate-and-refetch + 2 optimistic surfaces) in `src/CLAUDE.md` & `lib/hooks/CLAUDE.md`; added a line on the `QueryCache.onError` global query-error surface. No `frontend/CLAUDE.md` exists. **Track C COMPLETE.** |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- **C4 (2026-06-23):** Fixed CLAUDE.md doc drift against the real `query-client.ts`/`use-sources.ts`.
  In `frontend/src/CLAUDE.md`: corrected "Auto-refetch: `refetchOnWindowFocus: true` (sources,
  notebooks)" → global default is `false`, only `use-sources.ts` opts in (`true` + `staleTime: 5s`);
  notebook/note/chat use the global default. Replaced the blanket "Optimistic updates: chat messages
  added before confirmation" gotcha → "not a general pattern; most mutations invalidate-and-refetch",
  naming the two real optimistic surfaces (user chat bubble + `createSessionMutation` `onMutate` temp-id
  card from Track A). Added an Error Handling line documenting the C1 `QueryCache.onError` global
  query-error surface (queries-only toast, `meta.silent` opt-out, mutations keep per-hook toasts). Noted
  the notebook-scoped vs broad invalidation split (C3). In `frontend/src/lib/hooks/CLAUDE.md`: same
  `refetchOnWindowFocus` + optimistic-updates + invalidation-breadth corrections. **No `frontend/CLAUDE.md`
  exists** (track file listed it; confirmed absent — skipped). Markdown-only, no typecheck. **Track C is
  now COMPLETE (C1–C4 all ☑).**
- **C3 (2026-06-23):** Narrowed source/note list invalidations to the affected notebook where the
  mutation actually knows it. **`useAddSourcesToNotebook`** and **`useRemoveSourceFromNotebook`** (both
  carry `notebookId`) dropped the broad `['sources']` invalidation and now invalidate
  `sourcesInfinite(notebookId)` (the canonical key the workspace renders — **added**, since the broad
  tree previously covered it), `sources(notebookId)` (flat list, still read by `GeneratePodcastDialog`),
  and each affected `source(id)`. Adding/removing in notebook X no longer refetches every other
  notebook's source list. **`useCreateSource`**: removed the dead no-arg `QUERY_KEYS.sources()`
  (`['sources', undefined]`) invalidation flagged as a C3 candidate in C2 — it had no consumer; the
  per-notebook `sources(nbId)`+`sourcesInfinite(nbId)` invalidations it already does are kept.
  **Left broad on purpose (documented inline):** `useUpdateSource`, `useDeleteSource`, `useRetrySource`
  (variables = source id only) and `useDeleteNote` (note id only) carry **no notebook id**, and a
  source/note can live in multiple notebooks, so broad `['sources']`/`['notes']` is the spec's
  sanctioned fallback — scoping would require threading nb id through call sites in other tracks' files.
  Did not touch any other track's files. `npx tsc --noEmit` + `eslint` clean.
- **C2 (2026-06-23):** Unified the single-notebook source-list read. `AddExistingSourceDialog` (the
  only consumer of the flat `useSources(notebookId)` hook) now reads `useNotebookSources(notebookId)`
  — the canonical `QUERY_KEYS.sourcesInfinite` cache the workspace already populates — so opening the
  dialog reuses loaded pages instead of firing a redundant `['sources', nbId]` fetch. The now-dead
  `useSources` hook was removed from `use-sources.ts`. **Q-C2-remove-key resolved → KEEP the key:**
  `QUERY_KEYS.sources` still has real consumers — `GeneratePodcastDialog` reads it via `useQueries` +
  `prefetchQuery` across *multiple* notebooks (a full-list, multi-notebook case the single-notebook
  infinite query doesn't serve), plus mutation-invalidation writers — so it was NOT deleted. Per the
  spec's "leave it" branch. Invalidation writers left untouched (narrowing is C3's job; the now-dead
  no-arg `QUERY_KEYS.sources()` invalidation in `useCreateSource` is harmless and a C3 candidate).
  **Tradeoff noted:** the dialog now derives its "already-linked" set from loaded infinite pages
  rather than a single full fetch, so for notebooks with more sources than are currently paged in, a
  linked source may not show its "Linked" badge (benign — `addSources` uses `Promise.allSettled`).
  `npx tsc --noEmit` + `eslint` on both files clean.
- **C1 (2026-06-23):** Added `queryCache: new QueryCache({ onError })` to the singleton client in
  `query-client.ts`. Query failures now toast via `getApiErrorMessage(error, i18n.t.bind(i18n))`
  (translated through the singleton `@/lib/i18n` instance, outside React). Queries opt out with
  `meta: { silent: true }` (for Track B prefetch + background polling). No `MutationCache` added —
  mutations keep their per-hook toasts (no double-toast). `defaultOptions` unchanged. Typecheck (`npx
  tsc --noEmit`) passes. **Note for Q-C1-silent:** confirmed via grep there are currently no
  `meta`-bearing queries; Track B must set `meta:{silent:true}` on its prefetch/polling queries.

## Chunks (verbatim — do not require another track file)

### Chunk C1 — Global React Query error handler
- **Goal:** Query failures stop being silent. Add a `QueryCache` `onError` to the singleton client so
  failed queries surface a toast, without double-toasting mutations (which already have `onError`).
- **Read first:** `query-client.ts` (full file — `new QueryClient` :3-15, `QUERY_KEYS` :17-35; there is
  **no** `QueryCache`/`MutationCache` today), `lib/utils/error-handler.ts` (`getApiErrorMessage`,
  `formatApiError`, `ERROR_MAP`).
- **Spec / exact values:** Attach `queryCache: new QueryCache({ onError })`. Do NOT add a
  `MutationCache` onError — mutations keep their per-hook toasts (coordinator convention; avoids
  double-toast). Resolve the message via `getApiErrorMessage(error)` / `formatApiError`.
- **Reuse:** `QueryCache` from `@tanstack/react-query`; `sonner` `toast.error`; existing
  `error-handler.ts` helpers.
- **Steps:**
  1. Construct the client with a `queryCache: new QueryCache({ onError: (error, query) => { ... } })`.
  2. In the handler, toast the resolved error message. Optionally suppress toasts for queries that opt
     out via `meta: { silent: true }` (e.g. background polling, prefetch) — add a `meta.silent` check so
     Track B's prefetch and status-polling queries don't spam toasts. (Prefetch errors should be
     silent.)
  3. Keep the existing `defaultOptions` exactly as-is (staleTime/gcTime/retry/refetchOnWindowFocus).
- **Verify:** Force a query (e.g. notes list) to 500 — one toast appears; trigger a mutation failure —
  still exactly one toast (no duplicate). Prefetch failures (meta.silent) produce no toast. Typecheck
  passes.

### Chunk C2 — Unify duplicate source query keys
- **Goal:** One canonical source-list cache entry. Today `useSources` (`['sources',nbId]`) and
  `useNotebookSources` (`['sources','infinite',nbId]`) hold the same backend list under different keys,
  so opening the "add existing source" dialog refetches data the infinite query already has.
- **Read first:** `use-sources.ts` (`useSources` :23-24 + its query, `useNotebookSources` infinite
  :32-55), `query-client.ts` `QUERY_KEYS.sources`/`sourcesInfinite` (:22-23), the `useSources`
  consumer (`AddExistingSourceDialog.tsx` — confirm path via grep `useSources(`).
- **Spec / exact values:** Keep `sourcesInfinite` as canonical (Track B prefetch + the workspace
  already use it). Either (a) point the dialog at the infinite query (flatten pages) or (b) make
  `useSources` read from / share the infinite cache. Prefer the smallest faithful change.
- **Reuse:** the existing infinite query + `select`/flatten of pages.
- **Steps:**
  1. Migrate the `useSources` consumer(s) to the canonical infinite source list (flatten
     `data.pages`), or have `useSources` delegate to the same key so cache is shared.
  2. Remove the now-redundant `QUERY_KEYS.sources` entry only if it has no remaining consumers (grep
     first); otherwise leave it but ensure it shares the canonical cache.
  3. Update any invalidation that targeted the removed key.
- **Verify:** Open the add-existing-source dialog right after the workspace loaded sources — no
  duplicate network request (the dialog reads from cache). Typecheck passes.

### Chunk C3 — Narrow broad invalidations
- **Goal:** A single source/note edit shouldn't refetch every notebook's lists. Today mutations
  invalidate the entire `['sources']` / `['notes']` trees.
- **Read first:** `use-sources.ts` broad invalidations (`useUpdateSource` :159, `useDeleteSource` :185,
  `useRetrySource` :274, add :314, remove :367), `use-notes.ts` (`useDeleteNote` invalidates `['notes']`
  :87).
- **Spec / exact values:** Scope invalidations to the affected notebook where the mutation knows the
  notebook id (e.g. `QUERY_KEYS.sourcesInfinite(nbId)` / `QUERY_KEYS.notes(nbId)`), plus the specific
  item key (`QUERY_KEYS.source(id)` / `QUERY_KEYS.note(id)`). Only fall back to the broad tree when the
  notebook id genuinely isn't available.
- **Reuse:** `QUERY_KEYS` helpers.
- **Steps:**
  1. For each listed mutation, replace the broad `['sources']`/`['notes']` invalidation with the
     notebook-scoped + item-scoped keys, using the id(s) the mutation already has.
  2. Where a source can belong to multiple notebooks (add/remove to-notebook), invalidate the specific
     notebook(s) involved rather than all.
- **Verify:** Edit a source in notebook X with notebook Y also in cache — only X's source list
  refetches (Network tab). No stale UI in X. Typecheck passes.

### Chunk C4 — Fix CLAUDE.md doc drift
- **Goal:** Docs match reality so future work isn't misled. Current docs claim "optimistic updates" as
  a general mutation pattern and `refetchOnWindowFocus: true` as a default — neither is true (0
  `onMutate` pre-this-plan; global focus-refetch is `false`, only source hooks opt in).
- **Read first:** `frontend/src/CLAUDE.md` (Caching & Invalidation + Error Handling sections),
  `frontend/src/lib/hooks/CLAUDE.md`, and the actual `query-client.ts` defaults.
- **Spec / exact values:** Correct statements: global `refetchOnWindowFocus: false`; only
  `use-sources.ts` sets it `true` + `staleTime: 5s`. Note the new global query error handler (from C1)
  and the optimistic chat-creation/message patterns (from Track A) once those land — describe the
  *actual* state. Reuse-before-create: keep edits to the drifted lines, don't rewrite the docs.
- **Steps:**
  1. Fix the `refetchOnWindowFocus` claim and the blanket "optimistic updates" claim.
  2. Add a one-line note pointing at `QueryCache.onError` as the global query-error surface.
- **Verify:** Re-read the edited sections — they match `query-client.ts` and the hooks. (No typecheck
  needed for markdown.)

## Open Questions (this track)
- **Q-C1-silent** — Which queries should opt out of the global error toast (`meta.silent`)? Default:
  prefetch (Track B) and background status/episode polling. Confirm the polling hooks during C1.
- **Q-C2-remove-key** — ✅ RESOLVED (C2): KEPT. Grep showed `GeneratePodcastDialog` still reads
  `QUERY_KEYS.sources(nbId)` (via `useQueries` + `prefetchQuery`, multi-notebook) plus invalidation
  writers, so the key was not deleted. Only the dead `useSources` *hook* was removed.
