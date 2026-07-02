# Plan E — Polish (Notebook Multi-Chat Workspace)

> **One of 5 parallel plans (the last).** Read `.claude/plans/notebook-chat-workspace.md` (the
> COORDINATOR) first for shared law: Decisions, Conventions, cross-plan status, Open Q-mobile.
> **Chunk:** 13 (prompt-pin, animations, citation→source flash, mobile, i18n sweep). Frontend.
> **Dependencies:** **Plans A, B, C, D** must all be ☑ landed (this is the final pass over the finished
> surfaces). This plan is a single chunk.
> **Input artifact:** `design_handoff_notebook_chat/README.md` (Composer behavior, Interactions,
> Sources & Notes panels).

## Coordination (same working tree, sequential landing)
- **Wait for:** Plans A, B, C, D all ☑ in coordinator. Check before starting.
- **Shared files (you go LAST, so just extend):** `frontend/src/app/globals.css` (add keyframes — A's
  token swap already landed), `app/(dashboard)/notebooks/[id]/page.tsx` (add mobile — C built the
  track), `components/source/ChatPanel.tsx` (D's surfaces already in), the source-card component (flash
  target), `lib/locales/*` (final i18n sweep — reconcile all keys A/D added).
- **This is the archival trigger.** When Chunk 13 is ☑ and all other rows are ☑, perform the
  Completion & archival step in the coordinator (move all `ncw-*.md` + coordinator to
  `.claude/plans/archived/`).
- When done: update coordinator Cross-plan status row "E" → ☑ + Changelog, then archive.

## Resume prompt (fresh chat)
> Execute Plan E (Polish) of the Notebook Multi-Chat Workspace. First confirm Plans A–D are all ☑ in
> the coordinator. Read `.claude/plans/ncw-e-polish.md` and the coordinator
> `.claude/plans/notebook-chat-workspace.md` in full (plus the handoff README). Implement Chunk 13,
> verify it, update the coordinator's Cross-plan status/Changelog, and — since this is the last plan —
> perform the archival step. Tell me when it's done.

## Status
| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| 13 | Polish — prompt-pin, animations, citation→source flash, mobile, i18n sweep | ☑ done | Landed on claude-agent-integration |

---

### Chunk 13 — Polish (prompt-pin, animations, citation→source flash, mobile, i18n sweep)
- **Goal:** The remaining handoff interactions/feel: prompt pins to top on send; processing-dot pulse,
  dropdown rise-in, chevron rotate; citation click **flashes** the source card (accent ring 1.7s);
  a coherent mobile strategy for the track; a final i18n sweep.
- **Read first:** handoff README "Composer behavior" (115–119), "Interactions & Behavior" (136–145),
  "Sources & Notes panels" (129–132); the source-card component for the flash target; the mobile
  branch in `notebooks/[id]/page.tsx`.
- **Spec / exact values:** `onb-pulse` 1.3s, `onb-up` .14s, chevron .18s; source-card flash = accent
  ring for 1.7s; prompt-pin grows a tail spacer + smooth-scrolls the prompt near top (re-run on a few
  timers per `pinPrompt`).
- **Reuse:** `tw-animate-css` (already imported in globals.css) for keyframes; the citation
  `handleReferenceClick` to trigger the flash on the matching source card.
- **Steps:** (1) prompt-pin technique on send; (2) the three animations; (3) citation→source-card
  flash; (4) Sources card status indicators (Ready/Processing pulse/Failed) + 3-way context toggle
  styling per handoff; (5) mobile: horizontal track scroll (or a documented reduced layout — Open
  Q-mobile); (6) i18n sweep for all new strings across the 5 locales.
- **Verify:** send pins the prompt to top; processing dots pulse; clicking a citation flashes the right
  source card; dropdowns/chevrons animate; mobile is usable; no missing-translation-key warnings.
  `npm run build` passes.

## End-to-end verification (whole feature — run once everything lands)
- **Backend:** `uv run uvicorn api.main:app --port 5055` boots, migration logged once; `uv run pytest
  tests/test_domain.py tests/test_graphs.py` green. Manual via `/docs`: sub-chat session (parent+quote)
  round-trips; `/chat/execute` returns `citations[]`+`followups[]`+`tool_uses[]` (agent path) + accepts
  `media[]`; `/chat/media` upload returns a fetchable url.
- **Frontend:** `cd frontend && npm run build` passes. Manual: app-wide paper/indigo theme (light+dark);
  236px sidebar; resizable panel track with maximize; dock tabs + pop-out/dock-back + drag-reorder;
  in-dock model picker; citation cards + follow-up chips + source-card flash; tool-use disclosure;
  sub-chat via text selection anchored next to parent; media attach → tiles.
- **Known baseline noise to ignore:** pre-existing lint warnings unrelated to touched files; the
  positional message-id fallback (deferred); Docker-only checkpoint path differences (run from source);
  agent-path features require the local Claude CLI to be configured.

## Completion & archival (this plan triggers it)
When Chunk 13 is ☑ AND coordinator rows A–D are all ☑:
1. Update coordinator Cross-plan status row "E" → ☑ and append "All plans complete — archived <date>".
2. `mkdir -p .claude/plans/archived && mv .claude/plans/ncw-*.md .claude/plans/notebook-chat-workspace.md .claude/plans/archived/`
3. Tell the user the feature is complete and the plans are archived.