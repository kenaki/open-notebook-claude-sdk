# Notebook Flow Optimization — Track D: Animation

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, the cross-track conflict map — then execute this track's chunks here, one
> per session. You should never need to open another track's file.
> **Location:** `.claude/plans/notebook-flow-optimization/d-animation.md` → archived with the directory
> when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none. **Concurrent with:** A, B, C (run anytime).
**State at handoff (2026-06-23):** D1 ☑, D2 ☑ — **Track D COMPLETE.** No unstarted chunks remain.
**Paste-able resume prompt (run in a fresh chat):**
> Continue Notebook Flow Optimization Track D. Read
> `.claude/plans/notebook-flow-optimization/coordinator.md` then `d-animation.md` in full. Implement
> the next unstarted chunk (one only), verify it, then update BOTH this file's Status table AND the
> coordinator's Global status table + Changelog, and tell me when it's safe to clear context. If that
> was the last chunk of the last track, archive the feature directory per the coordinator's Completion
> section.

## This track's file ownership
Files this track creates/modifies:
- `frontend/src/components/notebooks/UtilityDrawer.tsx`
- `frontend/src/components/layout/AppSidebar.tsx`
- `frontend/src/components/notebooks/PanelCard.tsx`
- `frontend/src/app/globals.css`
Shared files I must NOT touch: chat files (Track A), notebook page/`AppShell.tsx`/provider (Track B —
note `AppShell.tsx` is Track B's; `AppSidebar.tsx` is yours, they're different files), cache/error
files (Track C). **Read Q-D1 + the coordinator's `P-drawer-transform` decision before starting D1** —
it carries the chosen approach for the push-vs-overlay tradeoff.

## Per-chunk workflow
read referenced files → implement → verify (build + visual check; `cd frontend && npm run typecheck`)
→ mark ☑ here AND in the coordinator → note new Open Questions → announce "✅ Chunk D.n complete —
safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| D1 | Transform-based drawer/sidebar/maximize transitions | ☑ done | claude (2026-06-23) | Push layout kept (Q-D1 default); containment+will-change, not overlay. |
| D2 | prefers-reduced-motion support | ☑ done | claude (2026-06-23) | Universal `@media (prefers-reduced-motion: reduce)` block in `globals.css`. |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- **D2 done (2026-06-23):** Added a universal `@media (prefers-reduced-motion: reduce)` block at the
  end of `globals.css` (`*, *::before, *::after` → `animation-duration: 0.01ms !important`,
  `animation-iteration-count: 1 !important`, `transition-duration: 0.01ms !important`,
  `scroll-behavior: auto !important`). One rule neutralizes the custom keyframes (`onb-pulse`,
  `onb-flash`, `chat-msg-enter`), the D1 drawer/sidebar width transitions + `PanelCard` maximize, the
  `.sidebar-menu-item`/`.card-hover` hover transitions, and Radix / `tw-animate-css` `animate-in`
  effects — all run via `animation`/`transition`, and end states still apply instantly. Lint clean
  (CSS not type-checked; no `typecheck` script — repo uses `next build`/`eslint`).
- **D1 done (2026-06-23):** Narrowed `transition-all`→`transition-[width]` on `AppSidebar` and added
  `[contain:layout_paint] will-change-[width]` to both the sidebar and `UtilityDrawer`'s width-animated
  element (push layout preserved — Q-D1 default; overlay not adopted). Added eased maximize/restore to
  `PanelCard` via a composed `flex/width 0.25s ease` transition, suppressed during resize-drag (new
  `isResizing` state) and sort-drag so dnd-kit/pointer tracking stay 1:1. Narrowed the `.sidebar-menu-item`
  and `.card-hover` `transition-all` in `globals.css` to explicit property lists. Typecheck + lint clean.

## Chunks (verbatim — do not require another track file)

### Chunk D1 — Transform-based drawer/sidebar/maximize transitions
- **Goal:** Stop per-frame layout thrash during the two `width` transitions (the highest-impact jank in
  the app), and give panel maximize a smooth transition instead of an abrupt snap. Also trim
  `transition-all` overuse.
- **Read first:** `UtilityDrawer.tsx` (`transition-[width]` :30-36, animating `w-[340px]`↔`w-0`; inner
  fixed `width:340px` :38), `AppSidebar.tsx` (`transition-all` width `w-16`↔`w-[236px]` :107-111),
  `PanelCard.tsx` (maximize toggle width/`flex:1 1 0%` with no transition :127-131; resize handle
  :81-96 — leave the drag resize untransitioned; dnd transform :121-132 — already correct).
  **Read the coordinator's `P-drawer-transform` row + Q-D1 below first** for the chosen approach.
- **Spec / exact values:** Animating `width` of a flex sibling reflows `main`/canvas every frame for
  300ms. Decision (default, see Q-D1): **keep the push layout but reduce thrash** via CSS
  `contain: layout paint` + `will-change` on the animating element, OR convert the `AppShell`-adjacent
  layout to CSS grid and animate `grid-template-columns` (cheaper, still push). Do **not** switch the
  drawer to a `translateX` overlay unless the user opts in (it changes UX: content no longer reflows
  to make room). For **maximize**, add a `transition` on the size property so it eases.
- **Reuse:** Tailwind transition utilities; existing durations (keep ~200–300ms). No new deps.
- **Steps:**
  1. Replace `transition-all` with the specific property (`transition-[width]` /
     `transition-[grid-template-columns]` / `transition-colors`) on the sidebar and any card-hover
     elements you touch — name the property, don't watch all.
  2. Apply the chosen low-thrash approach to `UtilityDrawer` and `AppSidebar` (containment +
     will-change, or grid-column animation). Keep the drawer's inner fixed-width content trick (:38).
  3. Add a transition to `PanelCard` maximize/restore so it eases instead of snapping.
  4. Audit `globals.css` for `transition-all` + `box-shadow` hover (`.sidebar-menu-item` :210-222,
     `.card-hover` :225-238) and narrow to specific properties where cheap.
- **Verify:** Open/close the utility drawer and collapse/expand the sidebar with Performance panel
  recording — fewer/no long layout tasks per frame vs. before; maximize now eases. No visual
  regression in push behavior. Typecheck passes.

### Chunk D2 — prefers-reduced-motion support
- **Goal:** Respect OS "reduce motion" — currently none of the keyframes/transitions are gated (an
  accessibility gap).
- **Read first:** `globals.css` keyframes (`onb-pulse` :256-266, `onb-flash` :268-277,
  `chat-msg-enter` :308-320) and the transition utilities edited in D1.
- **Spec / exact values:** Add a global `@media (prefers-reduced-motion: reduce)` block that disables/
  shortens animations and transitions (set `animation: none` / `transition-duration: 0.01ms` for the
  app's custom animations; keep essential opacity changes instant).
- **Reuse:** standard reduced-motion CSS pattern. No JS, no deps.
- **Steps:**
  1. Add the `@media (prefers-reduced-motion: reduce)` block to `globals.css` neutralizing the custom
     keyframes (`onb-pulse`, `onb-flash`, `chat-msg-enter`) and the drawer/sidebar transitions.
  2. Verify Radix/`tw-animate-css` driven animations are also covered (they key off the same media
     query / can be neutralized via the global rule).
- **Verify:** Toggle OS reduce-motion on — drawer/sidebar/message-enter/pulse no longer animate;
  functionality unchanged. Typecheck passes.

## Open Questions (this track)
- **Q-D1** *(S2 — surfaced in coordinator as `P-drawer-transform`, awaiting-you)* — For the drawer/
  sidebar width animation, keep the **push** layout (content reflows to make room) with containment/
  grid-column animation, or switch to a **translateX overlay** (cheaper but content no longer makes
  room)? **Default: keep push** via containment + `will-change` (or animated `grid-template-columns`).
  If the user prefers the cheaper overlay, revisit this chunk.