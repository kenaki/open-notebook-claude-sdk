# Cross-Plan Orchestration — Paste-able Prompts

> Companion to [coordinator.md](coordinator.md). These are the exact texts to paste into fresh chats.
> **Each parallel chat must run in its own git worktree off `feature/multipanelchat`** (concurrent
> chats on one checkout clobber each other's git state even with disjoint files). Create one with:
> `git worktree add ../on-<chunk> feature/multipanelchat` and `cd` into it; merge back on green.
>
> **One chunk = one commit. Verify (tsc + pytest) before marking ☑.** Each chunk updates its own
> per-plan status table AND the meta-coordinator's Global status table.
>
> Two execution styles below:
> - **background-jobs** + **document-foundation** → manual per-track chats (your 4-agents workflow). ✅
> - **chat-foundation** → run via `/chunk-plan-execute` (it self-parallelizes in worktrees +
>   integrates). Its lanes edit the same files in different regions and must NOT be hand-run as
>   parallel chats on one tree. ⚠

---

## Orchestrator chat (drives the whole schedule)
Paste into a fresh **Opus** chat. Keep it open; it tells you which 4 prompts to run each wave and
owns the status tables.

```
Read .claude/plans/cross-plan-orchestration/coordinator.md and prompts.md. Determine the current
wave from its Global status table cross-checked against `git log --oneline -30`. For the lowest
wave not fully ☑: list its runnable chunks (deps satisfied, file-disjoint per the Shared-file
ownership table), confirm no human gate blocks them, and hand me the exact prompt for each (from
prompts.md), the model to use, and its worktree name. Do NOT implement here. As I report each chunk
landed (commit + green verify), update this coordinator's Global status table + Changelog and the
originating per-plan coordinator's table. Announce the next wave when the current one is complete.
```

---

## WAVE 0 — Prep (run all 4 in parallel)

### P1 — Re-anchor background-jobs docs  ·  🔵 Sonnet
```
Re-anchor the background-jobs plan docs to the post-refactor codebase. Read
.claude/plans/background-jobs/coordinator.md, a-foundation.md, c-chat-surfaces.md. The readability
refactor moved things: api/routers/chat.py → api/routers/chat/ package; api/routers/sources.py →
package; source_chat streaming → api/source_chat_service.py; useNotebookChat.ts → split into
sessions/context/send hooks; ChatPanel.tsx relocated under components/.../chat/. For chunks A2, A3,
C2, C3: open the real current files, fix every stale path and line-anchor in the plan docs to match
today's layout (use grep/Read to confirm each symbol's new home). Edit ONLY the .md plan files — do
not touch source code. Commit as "docs(plan): re-anchor background-jobs to post-refactor layout".
Then update the meta Global status table row (Wave 0 / P1 → ☑) and stop.
```

### P2 — Re-anchor chat-foundation docs + bake compat fixes  ·  🔵 Sonnet
```
Re-anchor the chat-foundation plan docs to the post-refactor codebase AND bake in two compat fixes.
Read .claude/plans/chat-foundation/coordinator.md, backend.md, frontend.md, worker.md. Refactor
moved: api/routers/chat.py → api/routers/chat/ package; useNotebookChat.ts → split into
sessions/context/send hooks; ChatPanel relocated under chat/. Fix stale paths/anchors for chunks
B4, B5, F2, F3 (and any others) against the real current files (grep/Read to confirm). Then bake two
compatibility fixes required because background-jobs makes the chat answer async: (1) chunk B5's
illustration-job trigger must move into the WORKER chat-completion command, not the chat router;
(2) chunk F3 must REUSE background-jobs' use-jobs-poller, not build a second poll loop — note this in
the F3 spec. Edit ONLY the .md plan files. Commit as "docs(plan): re-anchor chat-foundation + async
compat fixes". Update the meta Global status table (Wave 0 / P2 → ☑) and stop.
```

### P3 — Author the document-foundation merged plan  ·  🟣 Opus  ·  uses /chunk-plan
```
Author a merged "document-foundation" plan that supersedes BOTH .claude/plans/source-chaptering/
and .claude/plans/pdf-viewer-citations.md. Run /chunk-plan with feature-slug "document-foundation".
Merge rationale + inventory: source-chaptering (A1 migration→use 19: source_section table +
page_offset/page_labels on source + section on source_embedding; A2 Docling extraction; A3 section
tree + get_sections/get_outline + section-tagged chunks; B1 vision-verifier GATE; B2 verify-clean
cmd; B3 summaries; B4 tiered get_context; B5 agent tools; C1 GET /sources/{id}/sections; C2 FE
types + getSections; C3 TOC sidebar; C4 selection menu + citation jump) PLUS pdf-viewer (Phase1
PDFViewer.tsx FE-only dep-free; Phase2 Docling — IDENTICAL to source-chaptering A2, fold into ONE
chunk; Phase3 page_number/bbox on source_embedding + vector_search + #p=N citations, migration 20;
Phase4 annotations, migration 21, DEFERRED). Author against the POST-REFACTOR layout: sources.py is
now a package (C1 adds the endpoint there); SourceDetailContent.tsx is split via a useSourceDetail
hook + tab panels (C3 anchors there). Migrations: 17 taken, 18 = chat-foundation; this plan uses 19
(fold all additive DEFINE FIELD IF NOT EXISTS source fields), then 20/21 for later phases. Emit a
coordinator + per-track files with paste-able resume prompts. When done, tell me the per-track
prompts so I can copy them into prompts.md. Update the meta Global status table (Wave 0 / P3 → ☑).
```

### P4 — Verify background-jobs A1  ·  🔵 Sonnet
```
Verify background-jobs chunk A1 is committed and working (it was bundled into an earlier commit, not
a separate A1 commit). Read .claude/plans/background-jobs/a-foundation.md chunk A1 spec. Confirm
commands/chat_commands.py, commands/_heavy_lane.py exist and are committed (clean in git status);
confirm the WAL pragmas on open_notebook/graphs/chat.py + source_chat.py and the commands/__init__.py
registration are present. Run a smoke check: `uv run python -c "import commands.chat_commands,
commands._heavy_lane"` and `uv run pytest tests/ -k "command or chat" -q` (report, don't fix
unrelated failures). Mark background-jobs A1 ☑ in its coordinator with note "verified committed",
and the meta Global status table (Wave 0 / P4 → ☑). Do not write feature code. Stop.
```

---

## WAVES 1+ — copy-paste track prompts (one per chat, no editing)

Each track is its own chat running **concurrently** in its own worktree. Copy the whole block as-is.
Each is re-runnable: it self-locates the next unstarted chunk from the Status table + `git log`, so
paste the same block on first run and on every resume after `/clear`. Run only the tracks whose deps
are ☑ for the current wave (see the wave schedule in coordinator.md).

### background-jobs / Track A — Foundation  (chunks A2, A3, A4, A5 · ready now, A1 ✓)
```
Continue Background-Jobs Track A in your own git worktree off feature/multipanelchat. Read
.claude/plans/cross-plan-orchestration/coordinator.md, then .claude/plans/background-jobs/coordinator.md,
then a-foundation.md. Derive the next unstarted Track-A chunk from the Status table cross-checked with
`git log --oneline -30`. Do exactly ONE chunk. Touch only Track A's owned files. Verify (tsc +
pytest; restart on-api/on-worker if backend changed) — do not commit if red. One chunk = one commit.
Update BOTH status tables (background-jobs coordinator + cross-plan-orchestration Global table) and
append a Changelog line. Announce "✅ safe to clear context — next: <chunk>" and STOP.
```

### background-jobs / Track C — Chat surfaces  (C1 ready now · C2 needs A2+A5 · C3 needs A3+A5)
```
Continue Background-Jobs Track C in your own git worktree off feature/multipanelchat. Read
.claude/plans/cross-plan-orchestration/coordinator.md, then .claude/plans/background-jobs/coordinator.md,
then c-chat-surfaces.md. Confirm this chunk's deps are ☑ (C1 is dep-free; C2 needs A2+A5; C3 needs
A3+A5) — if unmet, report and stop. Derive the next unstarted Track-C chunk from the Status table +
`git log --oneline -30`. Do exactly ONE chunk. Touch only Track C's owned files. Verify (tsc +
pytest; restart on-api/on-worker if backend changed) — do not commit if red. One chunk = one commit.
Update BOTH status tables (background-jobs coordinator + cross-plan-orchestration Global table) and
append a Changelog line. Announce "✅ safe to clear context — next: <chunk>" and STOP.
```

### background-jobs / Track B — Jobs runtime/tray  (B1 needs A4+A5 · B2,B3 need B1)
```
Continue Background-Jobs Track B in your own git worktree off feature/multipanelchat. Read
.claude/plans/cross-plan-orchestration/coordinator.md, then .claude/plans/background-jobs/coordinator.md,
then b-jobs-runtime.md. Confirm A4 + A5 are ☑ first (B2/B3 need B1) — if unmet, report and stop.
Derive the next unstarted Track-B chunk from the Status table + `git log --oneline -30`. Do exactly
ONE chunk. Touch only Track B's owned files. Verify (tsc + pytest; restart on-api/on-worker if
backend changed) — do not commit if red. One chunk = one commit. Update BOTH status tables
(background-jobs coordinator + cross-plan-orchestration Global table) and append a Changelog line.
Announce "✅ safe to clear context — next: <chunk>" and STOP.
```

### background-jobs / Track D — i18n  (Wave 5 · needs all of B and C ☑)
```
Continue Background-Jobs Track D in your own git worktree off feature/multipanelchat. Read
.claude/plans/cross-plan-orchestration/coordinator.md, then .claude/plans/background-jobs/coordinator.md,
then d-i18n.md. Confirm Tracks B and C are fully ☑ first — if unmet, report and stop. Do the i18n
chunk (jobs.* keys across all 14 locales). Touch only Track D's owned files. Verify (tsc) — do not
commit if red. One chunk = one commit. Update BOTH status tables (background-jobs coordinator +
cross-plan-orchestration Global table) and append a Changelog line. Announce "✅ safe to clear
context" and STOP.
```

> ⚠ **Same-track, same-wave (e.g. A2 + A3 both in Wave 1):** Track A is ONE track file, so two chats
> on it would both grab "the next chunk." To run them truly in parallel, give each its own worktree
> and add one sentence to the paste — `For this run do chunk A3 specifically.` (and the other `...A2
> specifically.`). Otherwise run that track's chunks one chat at a time.

### document-foundation / Track A — Foundation  (no deps · head of critical path)
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/a-foundation.md in full. Implement the next unstarted chunk (one
only, derive from the Status table + `git log --oneline -30`). Verify (API restart → migration
logs + pytest tests/test_domain.py for A1; Spark GPU spot-check for A2; pytest tests/ + section
tree for A3). Commit (one chunk = one commit). Update BOTH the track Status table AND the
coordinator Global status table + Changelog. Announce ✅ Chunk A.n complete — safe to clear context.
Then stop.
```

### document-foundation / Track B — Backend pipeline  (needs A ☑)
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/b-pipeline.md in full. Confirm Track A is fully ☑ in the
coordinator before starting. Implement the next unstarted chunk (one only). ⚠ B1 is a HUMAN GATE —
stop after the pilot and report GO/NO-GO before continuing to B2. Verify per the chunk spec. Commit.
Update BOTH status tables + Changelog. Announce ✅ Chunk B.n complete — safe to clear context. Stop.
```

### document-foundation / Track C — Surfaces  (needs A ☑ · concurrent with B)
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/c-surfaces.md in full. Confirm Track A is fully ☑ in the
coordinator before starting. Implement the next unstarted chunk (one only). Verify: uv run pytest
tests/test_models_api.py (backend); npm run build (frontend). Commit. Update BOTH status tables +
Changelog. Announce ✅ Chunk C.n complete — safe to clear context. Stop.
```

### document-foundation / Phase1 — PDF Viewer  (no deps · independent · concurrent with A/B/C)
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/standalone.md — Phase1 section only. Implement Phase1 (PDFViewer
component + tab integration). Verify: npm run build passes; PDF renders in browser for a real source
with file_available=true. Commit. Update BOTH the standalone Status table AND the coordinator Global
status table + Changelog. Announce ✅ Phase1 complete — safe to clear context. Stop.
```

### document-foundation / Phase3 — Page citations  (needs A2 ☑ + Phase1 ☑ recommended)
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/standalone.md — Phase3 section only. Confirm A2 is ☑ and Phase1
is ☑ in coordinator before starting (Phase1 needed for the citation-click→PDF-open flow). Implement
Phase3 (migration 20 + provenance-aware chunking + citation tokens + FE ref parser). Verify: API
restart → migration 20 applied; re-embed a PDF → source_embedding rows carry page_number; citation
[source:id#p=3] in chat scrolls PDFViewer to page 3. Commit. Update BOTH status tables + Changelog.
Announce ✅ Phase3 complete — safe to clear context. Stop.
```

---

## WAVE 6+ — chat-foundation (Lane A)  ‖  document-foundation tail (Lane B)

### chat-foundation — run via /chunk-plan-execute (NOT manual parallel chats)  ·  🟣 Opus orchestrator
chat-foundation is a worktree-orchestrator plan: its lanes edit the same files in different regions
and rely on isolation + integration merge. Run it as ONE orchestrator chat that fans out internally:
```
Execute the chat-foundation plan. Run /chunk-plan-execute on
.claude/plans/chat-foundation/coordinator.md. Honor its waves and worktree isolation; you are the
single writer of its status table. PAUSE at the B7 S-gate (vision/relevance spike → GO /
GO-WITH-ADJUSTMENTS / NO-GO; worker W2/W3 image path is conditional on GO) and at the W1–W3 SSRF /
fail-closed image-safety review and any needs-user Open Question — ask me, don't guess. After the
last chunk lands, update the meta-coordinator's Global status table (Wave 6+ chat-foundation → ☑)
and archive the chat-foundation directory.
```
> While chat-foundation runs, you still have spare agent slots — use them for the **document-foundation
> tail** (its B3/B4/B5 and C3/C4 per-track prompts above), since Lane B is file-disjoint from Lane A.

---

## FINAL WAVE

### T3-d — event-loop-bridge dedup  ·  🟣 Opus
Run only after ALL graph edits are done (background-jobs A1 ✓, chat-foundation B3, document-foundation
A2/A3). Timing-sensitive — preserve branch logic exactly or chat can deadlock.
```
Implement codebase-cleanup-audit item T3-d. Read .claude/plans/codebase-cleanup-audit.md (T3-d
section). Consolidate the duplicated run_in_new_loop()/get_running_loop()→ThreadPoolExecutor else
asyncio.run() dance from open_notebook/graphs/chat.py (~150-173) and graphs/source_chat.py (~62-90,
134-171) into run_async_in_node(coro) in utils/graph_utils.py (extend the existing helper). Preserve
the exact branch semantics — do not change behavior. Verify with pytest tests/test_graphs.py and a
live chat round-trip. One commit. Update the meta Global status table (T3-d → ☑). Then, if all three
feature plans are archived, archive .claude/plans/cross-plan-orchestration/ too.
```

### Phase 4 — PDF annotations (deferred/optional)  ·  🔵 Sonnet
Run only if you want annotations; spec lands with P3's document-foundation. Migration 21.
```
Continue Document-Foundation PDF track, chunk Phase 4 (annotations). Read
.claude/plans/document-foundation/coordinator.md + the PDF track file; do the annotations chunk
(source_annotation table migration 21, CRUD, highlight plugin), verify, commit, update both status
tables. Stop.
```
