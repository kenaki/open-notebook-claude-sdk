# Plan A — Theme + App Shell (Notebook Multi-Chat Workspace)

> **One of 5 parallel plans.** Read `.claude/plans/notebook-chat-workspace.md` (the COORDINATOR) first
> for shared law: Decisions, the **Token mapping** table (your authority for Chunk 0), conventions,
> and the cross-plan status table you must update when you finish.
> **Chunks:** 0 (design tokens + Inter), 1 (app shell reskin). Frontend-only.
> **Dependencies:** none — **start immediately**. Runs concurrently with **Plan B** (backend); you
> share **zero files** with it.
> **Input artifact:** `design_handoff_notebook_chat/README.md` (Design Tokens + Layout/Interactions).

## Coordination (same working tree, sequential landing)
- **Files you own outright while active:** `frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`,
  `frontend/tailwind.config.ts`, `frontend/src/components/layout/AppSidebar.tsx`, `AppShell.tsx`.
- **Land before Plan C and Plan E start** — C needs your Chunk 0 token swap; E later adds keyframes to
  `globals.css` and mobile tweaks (so finish your `globals.css` edits first).
- **`lib/locales/*`:** append nav-label keys only; never remove keys (Plans D/E also append).
- When done: update the **Cross-plan status** row "A — theme-shell" → ☑ and add a Changelog line in the
  coordinator.

## Resume prompt (fresh chat)
> Execute Plan A (Theme + App Shell) of the Notebook Multi-Chat Workspace. Read
> `.claude/plans/ncw-a-theme-shell.md` and the coordinator `.claude/plans/notebook-chat-workspace.md`
> in full (plus `design_handoff_notebook_chat/README.md`). Do the next unstarted chunk (0 then 1),
> verify it, update this plan's Status table + the coordinator's Cross-plan status/Changelog, and tell
> me when it's safe to clear context. One chunk per session unless I say otherwise.

## Status
| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| 0 | Design token system + Inter font (app-wide reskin foundation) | ☑ done | Token swap + Inter var; `npm run build` green (2026-06-22) |
| 1 | App shell reskin — sidebar 236px + WORKSPACE/SYSTEM + header | ☑ done | Sidebar reskinned (236px, WORKSPACE+SYSTEM groups, handoff eyebrows/active-state, removed Separator); `workspace`/`system` nav keys appended to all 14 locales; `npm run build` green, test+lint pass (2026-06-22). Page header (title·badge·counts) **deferred to Plan C** — it lives in `notebooks/[id]/page.tsx` (C/E own it); AppShell wraps every page so a notebook-titled global header there would be wrong. |

---

### Chunk 0 — Design token system + Inter font (app-wide reskin foundation)
- **Goal:** The whole app renders in the handoff's warm-paper/indigo palette (light + dark) with Inter,
  via a value-only swap of the existing semantic tokens plus new handoff-only tokens. No component
  logic changes.
- **Read first:** `design_handoff_notebook_chat/README.md` (Design Tokens, lines 154–211);
  `frontend/src/app/globals.css` (`@theme inline` 4–42, `:root` 44–77, `.dark` 79–111);
  `frontend/src/app/layout.tsx` (2,13,30); `frontend/tailwind.config.ts`; the coordinator's **Token
  mapping** table (your authority).
- **Spec / exact values:** the README Color tables (Light + Dark) and the coordinator's Token mapping
  table. Decision 7 (use exact hex). `--radius: 0.75rem`.
- **Reuse:** the existing semantic token names + `@theme inline` plumbing — only values change for
  mapped tokens; add new `--color-*` lines for the handoff-only tokens.
- **Steps:**
  1. In `:root`, set every mapped token to its handoff **light** hex; in `.dark`, to its handoff
     **dark** value. Set `--shadow` (two-layer) in both.
  2. Add new custom props (`--text-3`, `--border-2`, `--accent-soft`, `--accent-soft-2`, `--ready`,
     `--processing`, `--failed`, `--panel-2` if distinct) to both blocks; expose each in `@theme
     inline` as `--color-<name>` so `bg-panel-2`/`text-ready`/etc. utilities exist.
  3. Fix the font: ensure `--font-sans` resolves to Inter (set `--font-sans: var(--font-inter)` with
     the `next/font` variable, or map directly to the imported `inter`); remove the `geist-sans`
     mismatch at `globals.css:7`.
  4. Set `--radius: 0.75rem`. Spot-check the `.sidebar-menu-item` / `.card-hover` shadow rules still
     read sensibly against the new shadow.
- **Verify:** `cd frontend && npm run dev`; every page (notebooks, sources, search, settings, login)
  shows the paper/indigo theme; toggle light/dark via the sidebar ThemeToggle — no broken contrast,
  no hardcoded-color regressions. `npm run build` passes.

### Chunk 1 — App shell reskin (sidebar 236px + WORKSPACE/SYSTEM, header)
- **Goal:** The sidebar matches the handoff (236px; brand + "New"; **WORKSPACE** nav: Sources,
  Notebooks, Ask & Search, Podcasts; **SYSTEM** nav: Models, Settings; collapsible) and the page
  header matches the handoff (title · "Notebook" badge · counts · theme toggle).
- **Read first:** `frontend/src/components/layout/AppSidebar.tsx` (full), `AppShell.tsx`;
  handoff README "Layout (top level)" (24–46) + "Interactions" (136–145).
- **Spec / exact values:** width 236px; section eyebrows 10.5px/600 letter-spacing .07em; nav active
  highlight; SYSTEM = Models + Settings (map current MANAGE group's Transformations/Advanced under
  SYSTEM or keep — see Open Q-nav in coordinator).
- **Reuse:** existing `useSidebarStore` collapse state, `ThemeToggle`, lucide icons (match handoff
  metaphors: sources, notebooks, ask, podcast, models, settings, plus, menu, sun/moon).
- **Steps:** retag nav groups to WORKSPACE/SYSTEM; set width 236px (collapsed unchanged); restyle
  section eyebrows + active state with new tokens; ensure header bar (where notebook title/counts live)
  matches; keep i18n keys for nav labels.
- **Verify:** sidebar is 236px, two labeled groups, active highlight, collapse works; header shows
  title + badge + counts + toggle; all routes still navigate. `npm run build` passes.

## Completion
When both chunks are ☑: update the coordinator's Cross-plan status (row A → ☑) + Changelog, announce
"✅ Plan A complete — safe to clear context. Plan C can now start (Chunk 0 token swap landed)." then stop.
