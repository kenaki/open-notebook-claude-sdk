# Notebook Flow Optimization — Coordinator / Index

> **Shared source of truth for a multi-track plan.** This file holds everything common to all tracks.
> Each track is executed from its own file (`<track>.md` in this directory) by its own chat.
> A track chat reads THIS file first, then owns exactly one track file.
> **Location:** `.claude/plans/notebook-flow-optimization/coordinator.md` → the whole directory is
> archived to `.claude/plans/archived/notebook-flow-optimization/` once every track is ☑.

## How to run this plan (read first)
1. Pick any track — **all four are concurrent** (disjoint files, no cross-track dep). Run them in
   parallel chats, or one at a time, in any order.
2. Open its file `<track>.md` (this directory) in a fresh chat; that file is self-contained.
3. One chunk per session. On each chunk completion, update BOTH the track file's status AND the
   Global status table here, then announce "safe to clear context" and stop.
4. Honor the two cross-track **conventions** below (global-error scope; canonical source key) so the
   concurrent tracks don't collide logically even though their files are disjoint.

## Concurrency matrix
| Track | File | Depends on (must be ☑) | Concurrent with | Sequential after | Why |
|-------|------|------------------------|-----------------|------------------|-----|
| A — Chat flow | `a-chat-flow.md` | — | B, C, D | — | disjoint files |
| B — Notebook open | `b-notebook-open.md` | — | A, C, D | — | disjoint files |
| C — Errors & cache | `c-errors-cache.md` | — | A, B, D | — | disjoint files |
| D — Animation | `d-animation.md` | — | A, B, C | — | disjoint files |
> Read as: `A ‖ B ‖ C ‖ D` — everything runs together. No track waits on another.

## Shared-file ownership (conflict map)
No file is edited by more than one track (verified against the audit's per-file ownership). The two
rows below are **logical** coordination points, not file conflicts:
| Concern | Owner | Other tracks | Note |
|---------|-------|--------------|------|
| `queryClient` global error behavior | C (chunk C1) | A, B read it | Global handler fires on **query** errors only — must NOT toast mutation errors (A/B/C mutations already toast via their own `onError`). Prevents double-toast. |
| Canonical source query key | C (chunk C2) | B (chunk B1 prefetch) | C removes the redundant `QUERY_KEYS.sources(nbId)` and keeps `QUERY_KEYS.sourcesInfinite(nbId)` as canonical. B1 must prefetch using `sourcesInfinite` so it stays valid regardless of C's timing. |

## Global status table
| Track | Chunk | Title | Status | Owner / session | Notes |
|-------|------:|-------|--------|-----------------|-------|
| A | A1 | Optimistic chat creation | ☑ done | opus/A1 2026-06-23 | Optimistic temp card + instant nav-to-temp, URL reconcile on success / gallery fallback on fail. tsc+eslint clean. |
| A | A2 | Restore draft on send failure | ☑ done | opus/A2 2026-06-23 | `sendMessageTo`→`{ok}`; composer restores draft + keeps staged media + refocus on failed send; ChatDock forwards result. tsc+eslint clean. |
| A | A3 | Memoize markdown message rendering | ☑ done | opus/A3 2026-06-23 | `AIMessageContent`→`memo`; markdown+LinkComponent `useMemo`; `handleReferenceClick` stable via ref+`useCallback([])`; hoisted `MSG_SCROLL_MARGIN`. tsc+eslint clean. |
| A | A4 | Debounce buildContext | ☑ done | opus/A4 2026-06-23 | Immediate first run (counts on mount) + 250ms trailing debounce via `useRef` timer; cleared on input change + unmount. tsc+eslint clean. **Track A COMPLETE — all tracks now done.** |
| B | B1 | Prefetch-on-intent + cache-seed | ☑ done | Track B / 2026-06-23 | `useNotebookPrefetch()` hover/focus prefetch + click-seed; uses `sourcesInfinite` canonical key per convention |
| B | B2 | Render shell + skeleton (kill spinner flash) | ☑ done | Track B / 2026-06-23 | New `GallerySkeleton.tsx`; both notebook pages render skeleton inside `AppShell` on cold open (no out-of-shell spinner flash) |
| B | B3 | Notebook-open error/retry state | ☑ done | Track B / 2026-06-23 | Provider surfaces `notebookNotFound`/`notebookFetchError`/`refetchNotebook` (404 vs transient); pages show retry card on transient error, not-found on 404; new `notebooks.loadError*` keys in all 14 locales |
| B | B4 | Fix dataError loading/error conflation | ☑ done | Track B / 2026-06-23 | `dataError = !!sourcesError \|\| notesIsError` (real query flags), replacing the dead `!sources && !notes`. Loading→skeleton, empty→empty state, only a true fetch error fires ChatColumn UI. **Track B COMPLETE.** |
| C | C1 | Global React Query error handler | ☑ done | Track C 2026-06-23 | QueryCache.onError; query-only toast; meta.silent opt-out |
| C | C2 | Unify duplicate source query keys | ☑ done | Track C 2026-06-23 | Dialog reads canonical `sourcesInfinite`; dead `useSources` hook removed; `QUERY_KEYS.sources` KEPT (podcast dialog still reads it) |
| C | C3 | Narrow broad invalidations | ☑ done | Track C 2026-06-23 | Add/remove-to-notebook scoped to `sourcesInfinite(nbId)`+`sources(nbId)`+`source(id)`; dead no-arg `sources()` invalidation removed from create. Update/delete/retry/deleteNote kept broad (no nb id available). |
| C | C4 | Fix CLAUDE.md doc drift | ☑ done | Track C 2026-06-23 | Corrected `refetchOnWindowFocus` + blanket "optimistic" claims; added `QueryCache.onError` note in `src/CLAUDE.md` + `lib/hooks/CLAUDE.md`. **Track C COMPLETE.** |
| D | D1 | Transform-based drawer/sidebar/maximize transitions | ☑ done | claude (2026-06-23) | Push kept (Q-D1 default); containment+will-change, eased maximize. |
| D | D2 | prefers-reduced-motion support | ☑ done | claude (2026-06-23) | Universal `@media (prefers-reduced-motion: reduce)` block in `globals.css` |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (cross-track)
- **2026-06-23 — A4 done (Track A) → PLAN COMPLETE:** Debounced the context-count rebuild in
  `useNotebookChat`. The effect that recomputes token/char counts no longer fires a
  `POST /chat/context` on every source/note toggle — it runs immediately on mount (counts populate)
  then debounces subsequent runs 250ms trailing (`useRef` timer cleared on input change + unmount), so
  a burst of toggles collapses to one request. `useRef` import added; `console.error`-only failure
  handling left as-is per spec. Only Track-A-owned `useNotebookChat.ts` touched. tsc + eslint clean.
  **This was the last chunk of the last open track — every chunk in every track (A1–A4, B1–B4,
  C1–C4, D1–D2) is now ☑.** Archiving the feature directory to
  `.claude/plans/archived/notebook-flow-optimization/` per the Completion section.
- **2026-06-23 — A3 done (Track A):** Stopped re-parsing every chat message's markdown on each turn /
  each popped panel. `AIMessageContent` (`ChatPanel.tsx`) is now `React.memo`'d; inside it the
  reference→compact-markdown conversion and the `LinkComponent` are each `useMemo`'d. For the memo to
  hold across turns the parent's `handleReferenceClick` is now fully stable — `openModal`/`t` (re-created
  each render) live in a ref and the handler is a `useCallback([])` reading from it. The per-row inline
  `scrollMarginTop` style was hoisted to a module constant (`MSG_SCROLL_MARGIN`). `AIMessageContent`
  became a `const = memo(...)` (was a hoisted `function`) — safe since it's only referenced inside
  `ChatPanel`'s render. Only Track-A-owned `ChatPanel.tsx` touched. tsc (no ChatPanel errors) + eslint
  clean. **Track A: only A4 (debounce buildContext) remains.**
- **2026-06-23 — C4 done (Track C):** Fixed CLAUDE.md doc drift against the real `query-client.ts`/
  `use-sources.ts`. In `frontend/src/CLAUDE.md` and `frontend/src/lib/hooks/CLAUDE.md`: corrected the
  "`refetchOnWindowFocus: true` (sources, notebooks)" claim — the global default is `false`; only
  `use-sources.ts` opts in (`true` + `staleTime: 5s`), notebook/note/chat use the global default.
  Replaced the blanket "optimistic updates" claim — it's not a general mutation pattern (most are
  invalidate-and-refetch); named the two real optimistic surfaces (the user's chat bubble + Track A's
  `createSessionMutation` `onMutate` temp-id card). Added an Error Handling line documenting the C1
  `QueryCache.onError` global query-error surface (queries-only toast, `meta.silent` opt-out, mutations
  keep per-hook toasts) and noted the C3 notebook-scoped-vs-broad invalidation split. The track file
  listed `frontend/CLAUDE.md` too, but it does not exist (confirmed) — skipped. Markdown-only; no
  typecheck. **Track C is now COMPLETE (C1–C4 ☑).** Remaining across the plan: Track A's A3 + A4.
- **2026-06-23 — B4 done (Track B):** Fixed the `dataError` loading/error conflation in
  `NotebookWorkspaceProvider` — and **Track B is now COMPLETE (B1–B4 all ☑)**. The old
  `dataError: !sources && !notes` was effectively dead: `useNotebookSources` returns `sources` as
  `?? []` (always a truthy array), so `!sources` is always false → `dataError` could never be true,
  meaning the `ChatColumn` error UI never fired. It now derives from real TanStack Query error flags:
  `const dataError = !!sourcesError || notesIsError` (destructured `error` from `useNotebookSources`
  and `isError` from `useNotes` — both already exposed, **no cross-track hook edits**). Now a
  still-loading notebook shows the B2 skeleton, an empty notebook shows the empty state (both queries
  succeed empty → not error), and only a genuine fetch failure trips the error UI. The recovery handler
  `refetchSources` is already on the workspace value; adding a "Try again" button inside `ChatColumn`'s
  error card is left to Track A (`ChatColumn.tsx`/`DeepDiveWorkspace.tsx` are not Track B files — B4
  spec marks ChatColumn reference-only). Only `NotebookWorkspaceProvider.tsx` touched. tsc + eslint
  clean. **Remaining across all tracks: A3, A4, C4.**
- **2026-06-23 — A2 done (Track A):** A failed message send no longer loses the user's typed draft.
  `sendMessageTo` (`useNotebookChat.ts`) now returns `Promise<{ ok: boolean }>` (true after the
  authoritative messages land; false on send failure post-rollback and on the auto-create-failure
  path). `ChatPanel.handleSend` (now async) captures text + staged media, optimistically clears the
  composer, awaits `onSendMessage`, and on `{ok:false}` restores the draft + refocuses the textarea;
  the `onSendMessage` prop widened to `=> void | Promise<{ ok: boolean } | void>` so **source chat**
  (returns void) keeps clear-on-send unchanged. **ChatDock.tsx** (a Track-A chat file — Tracks B/C/D
  all reserve "chat files (Track A)"; none touch it) forwards the result and gates
  `clearPending`/auto-rename behind `result.ok`, so a failed send also keeps the staged media + the
  new-chat title. No `query-client.ts`/page/provider/animation files touched. tsc + eslint clean.
- **2026-06-23 — C3 done (Track C):** Narrowed source/note list invalidations to the affected notebook
  where the mutation knows it. `useAddSourcesToNotebook` + `useRemoveSourceFromNotebook` (both carry
  `notebookId`) dropped the broad `['sources']` invalidation and now hit `sourcesInfinite(nbId)` (added —
  the canonical key the workspace renders, per C2/B), `sources(nbId)` (flat list, still read by the
  podcast dialog), and each affected `source(id)` — so an add/remove in notebook X no longer refetches
  every other notebook's list. Removed the dead no-arg `QUERY_KEYS.sources()` invalidation from
  `useCreateSource` (flagged as a C3 candidate in C2; no consumer). `useUpdateSource`/`useDeleteSource`/
  `useRetrySource`/`useDeleteNote` **kept broad on purpose** (documented inline) — their variables carry
  only the item id, never a notebook id, and the item can live in multiple notebooks, so the broad tree
  is the spec's sanctioned fallback. Only Track C's own files touched. `tsc --noEmit` + `eslint` clean.
- **2026-06-23 — B3 done (Track B):** A failed notebook fetch no longer collapses to the misleading
  "Notebook not found" screen with no recovery. `NotebookWorkspaceProvider` now surfaces
  `isError`/`error`/`refetch` from `useNotebook` as three workspace flags: `notebookNotFound` (axios
  `response.status === 404` → genuine not-found), `notebookFetchError` (any other failure → transient,
  recoverable), and `refetchNotebook`. Both `[id]/page.tsx` and `[id]/chat/[chatId]/page.tsx` branch
  their `!notebook` case → `notebookFetchError` renders a calm inline error card with a "Try Again"
  `Button` (`refetchNotebook()`); otherwise the existing not-found message. New `notebooks.loadError`/
  `loadErrorDesc` keys added to all 14 locales (English + localized); button reuses `common.retry`. The
  inline card is deliberately calm because Track C1's global query-error handler already toasts the
  transient failure — toast = transient notice, inline panel = recovery. Did not touch `ChatColumn.tsx`/
  `query-client.ts` (other tracks). tsc + eslint clean. **Track B: only B4 remains.**
- **2026-06-23 — C2 done (Track C):** Unified the single-notebook source-list read.
  `AddExistingSourceDialog` (the lone consumer of the flat `useSources(nbId)` hook) now reads
  `useNotebookSources(nbId)` — the canonical `QUERY_KEYS.sourcesInfinite` cache the workspace already
  warms (Track B's prefetch + the workspace use the same key) — so opening the dialog reuses loaded
  pages instead of firing a redundant `['sources', nbId]` fetch. Removed the now-dead `useSources`
  hook. **Q-C2-remove-key → KEEP:** `QUERY_KEYS.sources` was NOT deleted — `GeneratePodcastDialog`
  still reads it via `useQueries` + `prefetchQuery` across *multiple* notebooks (a full-list case the
  single-notebook infinite query doesn't cover), plus invalidation writers. Invalidation writers left
  for C3 (the dead no-arg `QUERY_KEYS.sources()` invalidation in `useCreateSource` is harmless; a C3
  candidate). **Tradeoff:** the dialog's "already-linked" set now comes from loaded infinite pages, so
  a linked source beyond the paged-in set may miss its "Linked" badge (benign — add uses
  `Promise.allSettled`). `tsc --noEmit` + `eslint` clean. Does not touch any other track's files.
- **2026-06-23 — B2 done (Track B):** Killed the full-screen spinner rendered *outside* `AppShell` on
  cold notebook open (shell/sidebar vanished then snapped back). New page-level
  `components/notebooks/GallerySkeleton.tsx` (coarse `animate-pulse` header bar + title/toolbar +
  6-card grid) — deliberately kept out of `ChatGallery.tsx` so that file stays owned by Track A.
  Both `[id]/page.tsx` and `[id]/chat/[chatId]/page.tsx` now return `<AppShell><GallerySkeleton/></AppShell>`
  while `notebookLoading`, so the chrome stays mounted and only the content area swaps. Reuses the
  gallery skeleton for the deep-dive route too (Q-B2 default: page-level coarse skeleton). Did **not**
  touch `AppShell.tsx`. Typecheck + eslint clean.
- **2026-06-23 — D2 done (Track D):** Added a universal `@media (prefers-reduced-motion: reduce)` block
  to `globals.css` (`*, *::before, *::after` → near-zero animation/transition durations, iteration-count 1,
  auto scroll-behavior). Neutralizes the custom keyframes (`onb-pulse`, `onb-flash`, `chat-msg-enter`), the
  D1 drawer/sidebar/maximize transitions, the `.sidebar-menu-item`/`.card-hover` hovers, and Radix /
  `tw-animate-css` `animate-in` — all in one rule; end states still apply instantly. CSS-only; lint clean.
  **Track D is now COMPLETE (D1 ☑ D2 ☑).**
- **2026-06-23 — C1 done (Track C):** `query-client.ts` now has a global `QueryCache.onError` that
  toasts failed **queries** via `getApiErrorMessage(err, i18n.t)`; mutations untouched (no double-toast,
  per the conflict-map convention); `meta: { silent: true }` opts a query out. Tracks A/B reading the
  client are unaffected. **Track B:** set `meta:{silent:true}` on prefetch/polling queries to avoid
  toast spam. Typecheck passes.
- **2026-06-23 — D1 done (Track D):** De-janked the two `width` transitions and gave panel maximize an
  eased size change, all **without touching `AppShell.tsx`** (Track B's file) — chose the Q-D1 default
  (keep push layout via `[contain:layout_paint] will-change-[width]` on `AppSidebar` + `UtilityDrawer`,
  not the grid/overlay alternatives). `transition-all`→specific properties on the sidebar, `.sidebar-menu-item`,
  and `.card-hover`. `PanelCard` maximize/restore now eases (`flex/width 0.25s`), suppressed during
  resize-drag and sort-drag. Resolves `P-drawer-transform` to the default. Typecheck + lint clean.
- **2026-06-23 — B1 done (Track B):** New `useNotebookPrefetch()` in `use-notebooks.ts` warms a
  notebook before open — `prefetch(id)` loads notebook meta + sources page-1 (canonical
  `sourcesInfinite`) + notes + chat sessions using the workspace hooks' exact query fns/keys; `seed`
  pre-populates `QUERY_KEYS.notebook` from the list item so the title renders instantly. Wired into
  `NotebookCard` (hover/focus + seed-on-click) and `NotebookRow` (row hover, `<Link>` focus, seed on
  both clicks). All prefetches set `meta:{silent:true}` per the C1 convention so speculative warm-ups
  don't toast. Typecheck + lint clean.
- **2026-06-23 — A1 done (Track A):** First `onMutate` optimistic mutation in the app. `createSessionMutation`
  now inserts a `temp-session-*` card into `notebookChatSessions` AND seeds `notebookChatSession(tempId)`
  (fresh under the 5-min staleTime → no 404 fetch against the not-yet-real id), reconciles temp→real in
  `onSuccess`, rolls back + toasts in `onError`. Removed the create success toast. New hook export
  `createMainChat(title)→{tempId, promise}` for the gallery's instant path; `createSession` kept its
  `Promise<session|null>` contract so **ChatDock** (awaits the real id before sending — not a Track A file)
  is untouched. `ChatGallery.startNewMainChat` navigates to `tempId` at once then `router.replace`s to the
  real id on success / `/notebooks/{id}` on failure; dropped the blocking `creating` gate + `Loader2`.
  Files: `useNotebookChat.ts`, `ChatGallery.tsx` (both Track-A-owned). Typecheck + lint clean; manual
  throttle/500 browser check left to the user (services run as systemd units).

## Context — why
Audit of the notebook workspace (branch `feature/multipanelchat`) found the two flows the user cares
most about — **moving between notebooks** and **spawning chats** — are blocking round-trips, and that
the app is **almost entirely invalidate-and-refetch** (0 `onMutate` optimistic mutations; the only
optimistic surface is the user's own chat bubble). Separately, **query failures are silent** (no
global error handler, almost nothing reads `isError`), so a failed notebook-open renders as
"Notebook not found" with no retry.

**Build-now scope (this plan):** P0 optimistic flows + frontend-only error core + P2 rendering/
animation polish + P3 cache hygiene. **Deferred (documented, not built):** SSE assistant streaming +
waterfall collapse; backend `chat.py` `classify_error()`; comprehensive gallery/sources error
branches; list virtualization. See each track's Deferred notes and Open Questions.

## Decisions log (shared)
| # | Question | Decision |
|--:|----------|----------|
| 1 | How much to build now? | P0 (optimistic + errors) + P2 (render/anim) + P3 (cache hygiene). |
| 2 | Stream the assistant reply (SSE) + collapse waterfalls? | **Deferred** to a follow-up plan — large FE+BE change. Documented in Track A Deferred. |
| 3 | Error-handling depth? | **Frontend-only core**: global query error toast + notebook-open retry + dataError fix + restore-draft-on-fail. Backend `chat.py` classify_error() deferred; gallery/sources error branches deferred. |
| 4 | Single doc or parallel tracks? | 4 concurrent tracks — file-disjoint + dependency-free. |

### Decision Register (shared)
> Severity & gating per `~/.claude/skills/severity-model.md`. Gate: S3+ surfaced to the user.
| ID | Decision | Severity (why) | Status | Chosen / default |
|----|----------|----------------|--------|------------------|
| P-track-split | Decompose into 4 disjoint concurrent tracks | S3 (boundary, all later work hangs off it) | resolved | A/B/C/D as in matrix |
| P-streaming-defer | Defer SSE streaming + waterfall collapse | S3 (large FE+BE, genuine tradeoff) | resolved | Deferred (user) |
| P-error-depth | Frontend-only error core; backend classify_error deferred | S2 (reversible, contained) | resolved | Frontend-only (user) |
| P-optimistic-create | `createSessionMutation` → `onMutate` optimistic temp card | S3 (changes the spawn flow contract) | resolved | Temp-id card + reconcile + rollback (Track A1) |
| P-global-error-handler | Add `QueryCache.onError` to the singleton client | S3 (cross-cutting; affects every query's error surfacing) | resolved | Queries-only toast; mutations keep own onError (Track C1) |
| P-source-key-unify | Collapse two source query keys to one canonical | S3 (shared query-key contract; B depends) | resolved | Keep `sourcesInfinite`, remove redundant `sources` (Track C2) |
| P-drawer-transform | How to de-jank the width-animated drawer/sidebar | S2 (reversible CSS; but may change push semantics) | resolved (D1, default) | CSS `contain:layout paint` + `will-change`, push layout kept; overlay not adopted. Reversible if user prefers overlay. |

## Conventions / translation notes (shared)
- **Path alias** `@/` → `frontend/src/`. **State**: Zustand (UI/prefs) + TanStack Query (server state).
- **Query keys** are centralized in `frontend/src/lib/api/query-client.ts` (`QUERY_KEYS`). Always use
  the map, never inline arrays.
- **Singleton QueryClient** lives in `query-client.ts:3` (module-level `queryClient`), provided once in
  `QueryProvider.tsx`. Cache persists across all client navigations. Do not recreate it.
- **Toasts**: `sonner` — two coexisting styles: direct `import { toast } from 'sonner'` and the
  `use-toast.ts` wrapper (`variant: 'destructive'`). Match the surrounding file's style.
- **Error messages**: resolve via `getApiErrorMessage(err, '<i18n.key>')` in
  `frontend/src/lib/utils/error-handler.ts` (maps known backend strings via `ERROR_MAP`, else shows
  backend `detail`). Reuse existing `apiErrors.*` keys; only add new keys to `en-US` + structure for
  other locales when a genuinely new string is introduced.
- **i18n**: 14 locale dirs under `frontend/src/lib/locales/`. New user-facing strings need an `en-US`
  key at minimum; mirror the key into the other locales (English fallback acceptable) — do not hardcode.
- **No new deps**: everything here reuses existing libs (TanStack Query, sonner, tw-animate-css,
  @dnd-kit). Do not add an animation library.

## Reference index (shared)
- Primitives to reuse: `QUERY_KEYS` (query-client.ts:17-35), `queryClient` singleton (query-client.ts:3),
  `getApiErrorMessage`/`ERROR_MAP` (lib/utils/error-handler.ts), `patchSessionMessages`
  (useNotebookChat.ts:208-220), `LoadingSpinner`, existing Radix/Skeleton UI in `components/ui/`.
- Deps available: `@tanstack/react-query`, `sonner`, `tw-animate-css`, `@dnd-kit/*`, `react-markdown`
  + remark/rehype plugins.
### Post-exploration refinements (confirmed APIs)
- `QUERY_KEYS.sources(nbId)=['sources',nbId]`, `QUERY_KEYS.sourcesInfinite(nbId)=['sources','infinite',nbId]`,
  `QUERY_KEYS.notebook(id)=['notebooks',id]`, `QUERY_KEYS.notebookChatSessions(nbId)=['notebook-chat',nbId,'sessions']`,
  `QUERY_KEYS.notebookChatSession(sessionId)=['notebook-chat','sessions',sessionId]` (query-client.ts:17-35).
- `queryClient` = `new QueryClient({ defaultOptions: { queries: {staleTime:5m, gcTime:10m, retry:2,
  refetchOnWindowFocus:false}, mutations:{retry:1} } })` — **no QueryCache/MutationCache** yet (query-client.ts:3-15).
- Root providers order (app/layout.tsx): ErrorBoundary → ThemeProvider → QueryProvider → I18nProvider
  → ConnectionGuard → Toaster.

## Completion & archival
The track that marks the **last** chunk ☑ (sees every track complete in the Global status table)
appends a final Changelog line and moves the **whole feature directory** to
`.claude/plans/archived/notebook-flow-optimization/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/notebook-flow-optimization .claude/plans/archived/`),
then tells the user the plan is complete and archived.
