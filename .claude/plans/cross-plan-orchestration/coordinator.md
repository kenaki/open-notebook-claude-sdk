# Cross-Plan Orchestration — Meta-Coordinator

> **Canonical location:** `.claude/plans/cross-plan-orchestration/coordinator.md`
> **Type:** META-orchestration plan. It does **not** re-specify chunks — it *schedules* the
> already-decomposed per-plan coordinators into waves of **≤4 file-disjoint chunks** (you run 4
> agents at a time and want to minimize context clears).
> **Authoritative chunk specs live in the per-plan track files** referenced below. This doc owns
> only: the lane model, the wave schedule, the cross-lane shared-file rules, the global status
> table, and the model (Opus/Sonnet) per chunk.
> **Scope:** everything EXCEPT voice-chat (stays brief-only — see Follow-ons).

---

## SESSION HANDOFF (read first)

**State (2026-06-29, resumed orchestrator — reconciled):** Wave 0 ☑. **Wave 1 ☑.** **Wave 2 ☑ COMPLETE**
(bg A4 484ef18, bg A5 831aede, df A2 7e13d72, df Phase1 1608053). **Wave 3 partial:** bg B1 ☑ (82257ae),
bg C2 ☑ (5171514). Still ☐ in W3: **bg C3** (source-chat job-tracked), **df A3** (chaptering/section tree).
> ⚠ Reconciliation note: df A2, df Phase1, bg B1, bg C2 were all committed by prior sessions AFTER the
> last doc-update commit (d053b8f) but never recorded in any status table. Verified against `git log`
> (file sets match chunk specs) + tree-health (backend imports clean, SourceSection live, docling imports).
> Manual spot-checks still owed: df A2 GPU extraction on a real textbook, df Phase1 in-browser PDF render.
**Wave 3 ☑ COMPLETE** (bg B1 82257ae, bg C2 5171514, bg C3 e9bcafe, df A3 6ba9f40). Merged-tree verify:
backend pytest test_domain 31 pass + worker 16 cmds + api clean; frontend tsc clean (only pre-existing
`@testing-library` test-file noise). **Track A (document-foundation) FULLY ☑; bg Track A + Track C FULLY ☑.**

**Next runnable wave = Wave 4 (≤4):**
- **bg B2** — JobTray + JobTrayItem + JobStatusBadge + mount (dep B1✓) — FE, Track-B files
- **bg B3** — completion/failure toasts + job-origin helper (dep B1✓) — FE, Track-B files
- **df C1** — GET /sources/{id}/sections + schemas + has_sections (dep A3✓) — BE api/routers/sources + FE-disjoint
- **df B1 🚧 HUMAN GATE** — vision-verifier plumbing + is-Qwen-vision pilot (dep A1✓+A3✓). ⚠ Spike needs
  the live Spark + Ollama; STOPS for GO/NO-GO before df B2. Will PARK at its gate; bg B2/B3 + df C1 proceed.
> ⚠ bg B2 + bg B3 both edit `(dashboard)/layout.tsx` (mount) and may both add to `components/jobs/*` — they
> are the SAME track (B), sequential, NOT file-disjoint → run B2 then B3 (one worktree), not concurrently.
> Concurrency this wave: { bg B2→B3 } ‖ { df C1 } ‖ { df B1 pilot, parks }.
⚠ **Migration-counter caveat (for chatF B1 executor):** the version counter is **positional** (= list length), not filename-derived. df A1 appended `19.surrealql` as list position 18 → DB now at version 18. When chatF B1 adds migration **18**, it MUST be **appended at the END of both lists** (becoming the highest position), NOT inserted between 17 and 19 — inserting positionally would re-run 19 and skip the new 18. Filenames are labels only.
📐 **Design revision 2026-07-02 (integration audit):** (1) chat-foundation's illustration-delivery
contract rewritten for the 202-async world — trigger now owned by chatF **W1** in
`commands/chat_commands.py` (the old plan assigned it to bg C2, which landed without it);
`illustration_job_id` response field DROPPED; FE discovery via the poller's auto-register (chatF F3
re-scoped to `jobs-store.ts` + `use-jobs-poller.ts`). See chat-foundation coordinator contracts #5/#6 +
P-5/P-6. (2) df Phase3 now persists `page_map` (mig 20 + `graphs/source.py` + `domain/notebook.py`) —
resolves Q-page-map-provenance but adds file collisions: **df B2 ∦ df Phase3** (Wave-5 caveat below) and
**chatF F4 → df C4** on ChatPanel.tsx (cross-lane table). No landed code affected; Waves 4–5 packing adjusted.

**Orchestrator resume prompt (paste into a fresh Opus chat to drive a wave):**

```
Read .claude/plans/cross-plan-orchestration/coordinator.md. Determine the current wave from its
Status table cross-checked against `git log --oneline -30`. For the lowest-numbered wave that is
not fully ☑: list its runnable chunks (deps satisfied, file-disjoint per the Shared-file ownership
table), confirm no human gate is blocking, then for EACH runnable chunk print the exact per-track
resume prompt to paste (from that plan's own coordinator/track file SESSION HANDOFF), the model to
use (Opus/Sonnet), and the worktree/isolation note. Do NOT implement here — this chat only schedules
and integrates. After I report a chunk landed (commit + verify green), update THIS coordinator's
Status table and Changelog, and the originating per-plan coordinator's table. Stop when the wave is
complete and announce the next wave.
```

Each **chunk** is executed in its own fresh chat — **all paste-able prompts live in
[prompts.md](prompts.md)** (Wave 0 prompts are fully written there; feature waves point to each
plan's own resume prompt).

---

## The lane model (why this order)

Two lanes run **in parallel** because their file sets are disjoint. Within Lane A the two plans are
**strictly serial** because they rewrite the same functions.

- **Lane A — chat path (STRICTLY SERIAL): `background-jobs` → `chat-foundation`.**
  Both rewrite `api/routers/chat` `execute_chat` *and* `useNotebookChat` `sendMessageTo` — a true
  semantic conflict, not worktree-mergeable. background-jobs makes the chat answer async
  (`POST → 202 {job_id}`, computed in a worker); chat-foundation builds per-chat context +
  auto-illustrate on top of that contract. So **all of background-jobs lands before any
  chat-foundation chunk starts.** (A few chat-foundation chunks look independent — B1 mig, B3
  graph, F1 types, F4 mermaid — but each shares a file with an active background-jobs/doc chunk:
  `async_migrate.py`, `types/api.ts`, `ChatPanel.tsx`. Not worth the merge risk; keep the lane serial.)

- **Lane B — doc path (PARALLEL to A): `document-foundation`** (the merge of `source-chaptering`
  + `pdf-viewer-citations`). Its files (`graphs/source.py`, `SourceSection` domain, `/sources/{id}/sections`,
  `SourceTOC`, `SourceDetailContent`, `PDFViewer`, migration 19) are disjoint from the chat lane
  except for three shared files tracked below.

- **Tail (after BOTH lanes): `T3-d`** event-loop-bridge dedup — touches `graphs/chat.py` +
  `graphs/source_chat.py`, which both lanes edit; must come last.

```
Wave 0 (prep) ─┬─ Lane A: background-jobs ............... → chat-foundation ............
               └─ Lane B: document-foundation (A→A→A, then B‖C) .......................
                                                                                   → T3-d (last)
```

Each global wave packs runnable chunks from **both lanes** up to a cap of **4**.

---

## Cross-lane shared-file ownership (the only files both lanes can collide on)

Intra-plan file-disjointness is already guaranteed by each per-plan coordinator's own ownership
table — trust it. These are the **only** files where Lane A and Lane B can collide; never put two
chunks editing the same row's file in the same wave:

| Shared file | Lane A chunks | Lane B chunks | Rule |
|---|---|---|---|
| `frontend/src/lib/types/api.ts` | bg `A2`, bg `A4`; chatF `F1` | df `C2`, df `Phase3` | One editor per wave. Order: bg A2 → bg A4 → df C2/Phase3 → chatF F1. |
| `open_notebook/database/async_migrate.py` | chatF `B1` (mig 18) | df `A1` (mig 19) | Serialize registration edits. df A1 lands first (early Lane B); chatF B1 later. Migrations stay 18 → 19 (additive, apply-order-safe). |
| `frontend/src/components/.../ChatPanel.tsx` (now `chat/ChatPanel` after refactor) | bg `C1`✓; chatF `F4` | df `C4` (extends `handleReferenceClick` ~:126 — was missing from this table until 2026-07-02) | One editor per wave. Order: bg C1✓ → chatF F4 → df C4. **Never pack chatF F4 and df C4 in the same wave** (Wave 6+ backfill risk). |
| `open_notebook/graphs/source.py` | (none) | df `A2`✓, df `A3`✓, df `B2`, df `Phase3` (persist page_map — added 2026-07-02) | Lane-B internal — but **df B2 and df Phase3 are NOT file-disjoint**; never same wave (see Wave 5 caveat). |
| `open_notebook/graphs/chat.py` + `graphs/source_chat.py` | bg A1✓, chatF B3; T3-d | (none) | T3-d runs LAST, after B3 and all graph edits. |

> ⚠ **Re-anchoring:** every per-plan doc was written against the pre-refactor layout. Wave 0
> re-anchors them. After Wave 0, executing agents can trust the doc paths. Key moved targets:
> `api/routers/chat.py`→`api/routers/chat/` package · `sources.py`→package ·
> `useNotebookChat.ts`→`sessions`/`context`/`send` hooks · `SourceDetailContent.tsx`→`useSourceDetail`
> hook + tab panels · `ChatGallery`/`ChatPanel` relocated under `chat/` folders.

---

## Wave schedule

Legend: **A**=Lane A (chat) · **B**=Lane B (doc) · **P**=prep. Model: 🟣 Opus 4.8 / 🔵 Sonnet 4.6.
🚧 = human gate. Each wave ≤ 4 concurrent chats.

### Wave 0 — Prep (4 chats) — MUST complete before any feature chunk
| # | Lane | Task | Touches | Model |
|---|---|---|---|---|
| P1 | A | Re-anchor `background-jobs/*.md` paths/anchors to post-refactor layout (A2/A3/C2/C3) — ☑ done | `.claude/plans/background-jobs/*.md` | 🔵 |
| P2 | A | Re-anchor `chat-foundation/*.md` (B4/B5 → chat package; F2/F3 → split useNotebookChat hooks; bake compat fixes: B5 illustrate trigger → worker cmd, F3 reuse bg `use-jobs-poller`) | `.claude/plans/chat-foundation/*.md` | 🔵 |
| P3 | B | **Author `document-foundation/` merged coordinator** via `/chunk-plan` over source-chaptering + pdf-viewer (re-anchored C1/C3; migration 19; folds Docling A2≡Phase2). Supersedes both source dirs. | creates `.claude/plans/document-foundation/` | 🟣 |
| P4 | A | Verify `background-jobs` A1 (`commands/chat_commands.py`, `_heavy_lane.py`, WAL pragmas) is committed & imports/heavy-lane work (pytest smoke) — ☑ verified committed (bundled in 827bf48; imports OK, 10 passed) | read-only verify | 🔵 |

> After P3, Lane B's exact per-chunk file sets are firm. The Lane-B rows in Waves 1–5 below are
> **provisional** (inferred from the source plans) and should be reconciled against
> `document-foundation/coordinator.md` once P3 lands — the *dependency shape* holds regardless.

### Wave 1 (4 chats)
| Chunk | Lane | Plan · ID | What | Dep | Model |
|---|---|---|---|---|---|
| bg A2 | A | background-jobs · A2 | `/chat/execute` → 202 submit (+chat.ts/types) | A1✓ | 🔵 |
| bg A3 | A | background-jobs · A3 | source_chat send → 202 submit | A1✓ | 🔵 |
| bg C1 | A | background-jobs · C1 | shared pending/error chat bubble + msg types | — | 🔵 |
| df A1 | B | document-foundation · A1 | migration 19 + `SourceSection` model + page fields | — | 🔵 |

### Wave 2 (4 chats)
| Chunk | Lane | Plan · ID | What | Dep | Model |
|---|---|---|---|---|---|
| bg A4 | A | background-jobs · A4 | `list_command_jobs` + `commands.ts` client | — | 🔵 |
| bg A5 | A | background-jobs · A5 | shared `jobs-store.ts` (Zustand+persist) | — | 🔵 |
| df A2 | B | document-foundation · A2 | Docling extraction + page provenance (≡ pdf Phase 2) | A1 | 🔵 |
| df P1 | B | document-foundation · (pdf Phase 1) | `PDFViewer.tsx` inline viewer (FE-only, dep-free) | — | 🔵 |

### Wave 3 (4 chats)
| Chunk | Lane | Plan · ID | What | Dep | Model |
|---|---|---|---|---|---|
| bg B1 | A | background-jobs · B1 | `use-jobs-poller` + `JobsRuntime` + mount | A4,A5 | 🔵 |
| bg C2 | A | background-jobs · C2 | notebook send/receive refactor (sendMessageTo) | A2,A5,C1 | 🔵 |
| bg C3 | A | background-jobs · C3 | source-chat → cache-backed + job-tracked | A3,A5,C1 | 🔵 |
| df A3 | B | document-foundation · A3 | section tree + `get_sections`/`get_outline` + tagged chunks | A1,A2 | 🔵 |

### Wave 4 (4 chats)
| Chunk | Lane | Plan · ID | What | Dep | Model |
|---|---|---|---|---|---|
| bg B2 | A | background-jobs · B2 | `JobTray` + items + badge + mount | B1 | 🔵 |
| bg B3 | A | background-jobs · B3 | completion/failure toasts + `job-origin` | B1 | 🔵 |
| df B1 🚧 | B | document-foundation · B1 | vision-verifier plumbing + **is-Qwen-vision gate** | A1,A3 | 🟣 |
| df C1 | B | document-foundation · C1 | `GET /sources/{id}/sections` (sources package) | A3 | 🔵 |

### Wave 5 (4 chats) — background-jobs COMPLETES here
| Chunk | Lane | Plan · ID | What | Dep | Model |
|---|---|---|---|---|---|
| bg D1 | A | background-jobs · D1 | `jobs.*` i18n across 14 locales | B✓,C✓ | 🔵 |
| df B2 | B | document-foundation · B2 | per-chapter verify-clean background command | B1(GO),A3 | 🔵 |
| df C2 | B | document-foundation · C2 | FE types + `getSections` client | C1 | 🔵 |
| df P3 | B | document-foundation · (pdf Phase 3) | page_number/bbox on source_embedding + vector_search + `#p=N` citations (mig 20) | A2 | 🔵 |

> ⚠ **Wave-5 packing caveat (2026-07-02):** df B2 and df Phase3 **both edit `graphs/source.py`** now
> (Phase3 persists `page_map` in `save_source`; Phase3 also adds `Source.page_map` to
> `domain/notebook.py`, a Track-B-owned file) — they are NOT file-disjoint and must NOT run
> concurrently as this table suggests. Run **df Phase3 ‖ df C2 ‖ bg D1** in Wave 5 (Phase3 is
> gate-free) and slide **df B2 to Wave 6** (it is gated on the df B1 GO anyway, which parks at Wave 4).
> If B1 GO'd early and B2 is ready first, invert: B2 in Wave 5, Phase3 slides.

> ✅ **background-jobs archived after Wave 5.** Lane A now switches to `chat-foundation`.

### Wave 6 — chat-foundation begins (≤4 chats; Lane B tail backfills spare slots)
chat-foundation's own waves are: W1=[B1 mig18, B3 msgid, B7 vision-spike 🚧S-GATE, F1 types, F4
mermaid] → W2=[B2 models, F2 hook-ctx, F6 toggle] → W3=[B4 ctx-crud, B5 hydrate-job, B6 nb-api,
F3 hook-poll, F5 popover] → W4=worker W1 → W5=worker W2 (gated on B7 GO) → W6=worker W3.
Cap each global wave at 4: take chat-foundation's next ≤4 runnable chunks, backfill any spare slot
with the remaining document-foundation tail (df B3 summaries → B4 tiered get_context → B5 agent
tools; df C3 TOC sidebar → C4 selection/citation). **Finalize exact packing after P3** gives
document-foundation firm file sets.

Suggested Wave 6: chatF `B1`(mig18 🔵) · chatF `B3`(msgid 🔵) · chatF `B7`(🚧 vision-spike S-gate 🟣) · df `C3`(TOC sidebar 🔵).
Then continue: chatF W2 ‖ df `B3`/`C4`; chatF W3; chatF worker W1→W2(needs B7 **GO**)→W3 (W1–W3 SSRF/safety 🟣 Opus).
> ⚠ Backfill constraints (2026-07-02): **df C4 only after chatF F4 ☑** (both edit `ChatPanel.tsx` —
> cross-lane table). chatF F3 edits bg-owned `use-jobs-poller.ts`/`jobs-store.ts` — fine, bg fully
> landed by Wave 6. chatF W1 edits bg-owned `commands/chat_commands.py` (illustration trigger —
> contract #6 v2, see chat-foundation changelog 2026-07-02) — same rule, fine after bg archives.

### Final wave
| Chunk | Lane | Plan · ID | What | Dep | Model |
|---|---|---|---|---|---|
| T3-d | — | codebase-cleanup-audit · T3-d | `run_async_in_node` event-loop-bridge dedup in `graphs/chat.py` + `graphs/source_chat.py` | ALL graph edits done (bg A1✓, chatF B3, df A2/A3) | 🟣 |
| df P4 | B | document-foundation · (pdf Phase 4) | annotations (`source_annotation`, mig 21) — **deferred/optional** | df P1 | 🔵 |

---

## Human gates (orchestrator must pause)
- **chat-foundation B7 — S-gate** (Wave 6): qwen3.6 VLM vision + relevance spike → GO / GO-WITH-ADJUSTMENTS / NO-GO. Gates worker W2/W3 (image path). Diagram path (worker W1) proceeds regardless. 🟣
- **chat-foundation W1–W3** — SSRF / fail-closed image safety review. 🟣
- **document-foundation B1** — is-Qwen-vision feasibility gate (Wave 4); gates df B2 verify-clean. 🟣
- **ds4-deepseek** (orthogonal, not scheduled) — needs your A/B/C design decision + nvcc/memory check before any chunking.

---

## Global status table (executor updates this)
Legend: ☐ todo · ◐ in-flight · ☑ done. Update the per-plan coordinator's row too.

| Wave | Chunk | Plan · ID | Model | Status |
|---:|---|---|:--:|:--:|
| 0 | P1 re-anchor bg docs | (meta) | 🔵 | ☑ |
| 0 | P2 re-anchor chatF docs | (meta) | 🔵 | ☑ |
| 0 | P3 author document-foundation | (meta/chunk-plan) | 🟣 | ☑ |
| 0 | P4 verify bg A1 | background-jobs · A1 | 🔵 | ☑ |
| 1 | A2 | background-jobs | 🔵 | ☑ |
| 1 | A3 | background-jobs | 🔵 | ☑ |
| 1 | C1 | background-jobs | 🔵 | ☑ |
| 1 | A1 | document-foundation | 🔵 | ☑ |
| 2 | A4 | background-jobs | 🔵 | ☑ |
| 2 | A5 | background-jobs | 🔵 | ☑ |
| 2 | A2 | document-foundation | 🔵 | ☑ |
| 2 | Phase1 | document-foundation | 🔵 | ☑ |
| 3 | B1 | background-jobs | 🔵 | ☑ |
| 3 | C2 | background-jobs | 🔵 | ☑ |
| 3 | C3 | background-jobs | 🔵 | ☑ |
| 3 | A3 | document-foundation | 🔵 | ☑ |
| 4 | B2 | background-jobs | 🔵 | ☐ |
| 4 | B3 | background-jobs | 🔵 | ☐ |
| 4 | B1 🚧 | document-foundation | 🟣 | ☐ |
| 4 | C1 | document-foundation | 🔵 | ☐ |
| 5 | D1 | background-jobs | 🔵 | ☐ |
| 5 | B2 | document-foundation | 🔵 | ☐ |
| 5 | C2 | document-foundation | 🔵 | ☐ |
| 5 | Phase3 | document-foundation | 🔵 | ☐ |
| 6+ | chat-foundation W1–W6 ‖ df tail (B3,B4,B5,C3,C4) | — | mixed | ☐ |
| last | T3-d | codebase-cleanup-audit | 🟣 | ☐ |
| last | Phase4 (deferred) | document-foundation | 🔵 | ☐ |

---

## How to run a chunk (per-plan resume prompts)
Each chunk runs in its **own fresh chat** with **its own plan's** resume prompt — this coordinator
does not duplicate chunk specs.
- **background-jobs:** see `.claude/plans/background-jobs/coordinator.md` → "Run a track in a fresh
  chat" (per-track prompts: a-foundation / b-jobs-runtime / c-chat-surfaces / d-i18n).
- **chat-foundation:** see `.claude/plans/chat-foundation/coordinator.md` (backend / frontend / worker tracks).
- **document-foundation:** created by Wave 0 / P3 — read its coordinator for prompts.
- **Worktree isolation:** chunks in the same wave that share *any* file must not run concurrently
  (already prevented by the schedule). Otherwise run each in an isolated worktree and integrate on green.
- **One chunk = one commit. Verify (tsc + pytest) before marking ☑.** Update both this table and the
  per-plan table.

## Completion & archival
- background-jobs archives after its D1 ☑ (end of Wave 5) — its own coordinator triggers it.
- chat-foundation and document-foundation archive when their last chunk ☑.
- This **meta-coordinator** archives (`git mv .claude/plans/cross-plan-orchestration` →
  `archived/`) when T3-d ☑ and all three feature plans are archived.

## Follow-ons (not scheduled here)
- **voice-chat** — brief-only at `.claude/plans/voice-chat/brief.md`. Run `/chunk-plan` on it
  after the chat lane lands (it assumes async chat). Then append as Lane A's third plan.
- **ds4-deepseek-v4-flash** — research/decision-gated; orthogonal.

## Changelog
- 2026-07-02 — **Integration audit → design revision (docs only, no code).** Pre-Wave-4 first-principles
  audit of how the three plans compose found and fixed: (1) **unimplementable illustration contract** —
  chatF frozen contract #6 predated the 202 pivot (`illustration_job_id` unreturnable; trigger assigned
  to bg C2 which landed as pure-FE → orphan). Rewritten as v2: W1 owns the trigger in
  `commands/chat_commands.py` (submit `illustrate_message` before the chat job returns), poller
  auto-discovers (F3 → `deriveKind`/`handleTermination`, silent kind), B5 slimmed to citations.py-only
  hydrate, B3/F1 drop the dead field; heavy-lane serialization pinned (P-6). (2) **df Phase3 page_map
  persistence** — Q-page-map-provenance resolved by persisting `source.page_map` in mig 20; Phase3 file
  set grew → df B2 ∦ df Phase3 rule + Wave-5 repack (Phase3 in W5, B2 slides to W6 behind its gate).
  (3) **ChatPanel.tsx cross-lane row added** (df C4 was missing) → chatF F4 → df C4 order. Updated docs:
  chatF coordinator/backend/frontend/worker, df coordinator/standalone, this file.
- 2026-06-29 (later, wave 3) — **Wave 3 ☑.** Fanned out bg C3 ‖ df A3 (2× Sonnet, feature-based
  worktrees). Both detected their worktree was main-based and re-seeded onto feature/multipanelchat HEAD
  (orchestrator integrated via cherry-pick — clean, file-disjoint). **bg C3 (e9bcafe)** source-chat
  cache+job-tracked; **df A3 (6ba9f40)** chaptering/section tree + commands. Merged-tree verify green
  (pytest 31; worker 14→16 cmds; api clean; tsc clean modulo pre-existing test-file noise). Doc-foundation
  Track A complete; bg Tracks A+C complete. Follow-ups filed (Q-section-delete-cleanup, Q-page-map-provenance).
  Next = Wave 4: bg B2→B3 ‖ df C1 ‖ df B1🚧 (parks at Qwen-vision gate).
- 2026-06-29 (later) — **Resumed orchestrator reconciliation.** Recorded 4 chunks that had landed in git
  but were never marked in any status table: **df A2 (7e13d72)**, **df Phase1 (1608053)**, **bg B1 (82257ae)**,
  **bg C2 (5171514)**. → **Wave 2 ☑ COMPLETE; Wave 3 half-done** (bg B1 ✓, bg C2 ✓). Updated all four
  affected docs (bg coordinator + b/c track files; df coordinator + a-foundation + standalone) and this
  meta table. Tree-health verified: backend imports clean (SourceSection live), docling imports. **Next
  wave = bg C3 ‖ df A3.**
- 2026-06-25 — Meta-coordinator authored. Readability refactor confirmed 100% landed (gate cleared).
  Scope = all plans except voice-chat. Wave 0 prep + lane model + cross-lane shared-file rules +
  global wave schedule recorded. Lane-B rows in Waves 1–5 provisional pending P3.
- 2026-06-26 — P3 ☑: document-foundation/ authored, supersedes source-chaptering/ and
  pdf-viewer-citations.md. Migration 19 (Track A1) + migration 20 (Phase3). Post-refactor layout
  confirmed: sources.py → package; SourceContentTab.tsx owns ReactMarkdown render (C3 anchor);
  PassageSelectionMenu in notebooks/workspace/ (C4 anchor). 5 files: coordinator.md +
  a-foundation.md + b-pipeline.md + c-surfaces.md + standalone.md. Wave 0 / P3 ☑.
- 2026-06-26 — Wave 0 fully ☑ (P1+P2 re-anchor commits 961d6c4/9a43913 confirmed; P3+P4 already
  marked). bg A2 ☑ (bbce67b): `/chat/execute` → 202+job_id, ExecuteChatJobResponse BE+FE,
  command_service guard-import upgraded; tsc+pytest green. Wave 1 in progress (A3, C1, df-A1 next).
- 2026-06-29 — **Orchestrated wave (chunk-plan-execute, Opus orchestrator + Sonnet chunks, 4 worktrees).**
  Landed bg A3 (1ef7325 source_chat→202), bg A4 (484ef18 list_command_jobs active + commands.ts +
  /commands/active), bg A5 (831aede jobs-store.ts), df A1 (34ec0bd mig19 + SourceSection). **Wave 1 ☑;
  Wave 2 A4/A5 ☑.** Verify on merged tree: frontend `tsc` clean; `tests/test_domain.py` 23 pass (8
  credential-config "failures" are a pre-existing numpy collection-order flake — pass in isolation, not
  a regression); import smoke clean; on-api/on-worker restart clean (no tracebacks); **migration 19
  schema verified LIVE in DB** (source_section table + source.page_offset/page_labels +
  source_embedding.section); A2/A3 routes show 202 in openapi; A4 SQL executes (0 active jobs). df A1
  integrated by hand (worktrees branch from origin/main, not the feature branch — A3/A4 self-rebased;
  df A1 didn't, so its async_migrate.py append + notebook.py edits were re-applied onto feature/multipanelchat).
  Recorded migration-counter caveat for chatF B1 (see SESSION HANDOFF).
