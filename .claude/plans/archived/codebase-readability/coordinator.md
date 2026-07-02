# Codebase Readability Refactor — Coordinator

> **Goal:** Make Open Notebook easier to read. Two disciplines, in strict order: **(1) collapse duplicated mechanics into shared primitives, then (2) split the monster files into small, concern-focused, reusable files.**
> **Status:** All build-now chunks landed (BE A1–C5 + FE A4–C9). **Frontend track COMPLETE** (C7 was last, 72888f7). Backend track shows all chunks done in the table. Ready to archive once both chats confirm — not archived yet (cross-track decision). Optional/deferred dedup below remains out of scope.
> **Branch:** feature/multipanelchat
> **Companion:** broader duplication inventory at `.claude/plans/codebase-cleanup-audit.md` (slice citations referenced as `T#-x`). This plan adds the **split** dimension and reorders everything around readability.

This is the **coordinator** doc — the single source of truth for the shared status table, dependency model, decisions, and verification. The per-track work lives in:
- **[backend.md](backend.md)** — `api/` + `open_notebook/` (Chat 1)
- **[frontend.md](frontend.md)** — `frontend/` (Chat 2)

---

## Why this change

The codebase works but reads as "big slops of code": the same four-line snippets are copy-pasted across dozens of files, and a handful of files have grown to 800–1100 lines doing 4–5 unrelated jobs each.

**Dedup MUST come before split.** If we split first, copy-pasted boilerplate gets scattered into the new files and the duplication gets *worse*. Collapse repetition first → each concern is already lean when moved into its own file.

## Resolved decisions

- **Error resolver (FE):** standardize on `getApiErrorMessage` (i18n key → translated, else raw backend string). All new error helpers use this.
- **Scope:** **behavior-preserving structural splits only.** The fetch-in-`useEffect` → TanStack migration (audit `T3-g`) is **out of scope**, deferred to a separate behavioral plan.
- **400-vs-404 (BE):** "model not found" standardizes on **404** (matches `NotFoundError`→404 in `api/main.py`).

---

## Tracks & dependency model

Backend and Frontend are **file-disjoint → two parallel tracks**, each safe in its own chat. Within a track the order is strict: **Phase A (primitives) → Phase B (apply dedup) → Phase C (split files)**. A file is split (C) only after its dedup (B) has landed; B depends on A's primitives existing.

```
            ┌── BACKEND (backend.md) ─────────────────────┐
A1,A2,A3 ─▶ B1,B2,B3 ─▶ C1,C2,C3,C4,C5
            └─────────────────────────────────────────────┘
            ┌── FRONTEND (frontend.md) ───────────────────┐
A4,A5,A6 ─▶ B5,B6,B7,B8,B9 ─▶ C6,C7,C8,C9
            └─────────────────────────────────────────────┘
```

**Parallelism rule:** parallelize *across* tracks (BE chat ‖ FE chat), not *within* a track's phases (B imports A; C needs B). **One chunk = one reviewable commit.**

**⚠️ Two parallel chats must NOT share one checkout on one branch** — they'll clobber each other's git state even with disjoint files. Use either:
- separate git worktrees of `feature/multipanelchat`, or
- separate branches `cleanup/backend` + `cleanup/frontend`, merged at the end.

---

## Status (single source of truth — update here as chunks land)

| ID | Phase | Track | Chunk | Risk | Status |
|----|-------|-------|-------|------|--------|
| A1 | Primitives | BE | `_helpers.py`: `get_or_404` + `ensure_prefix` | LOW | done (827bf48) |
| A2 | Primitives | BE | `service_utils.py`: `_unwrap` + `_as_list` | LOW | done (4a61071) |
| A3 | Primitives | BE | domain `refers_to` methods + `session_to_response`/`episode_to_response` | LOW | done (91622cb) |
| A4 | Primitives | FE | `client.ts`: `get/post/put/del` + `getAuthToken`/`streamFetch` | LOW | done (a54c1e3) |
| A5 | Primitives | FE | `lib/utils/format.ts`: compact-number + relative/absolute date | LOW | done (94d44fb) |
| A6 | Primitives | FE | error toast: `useErrorToast()` + `toastApiError()` (on `getApiErrorMessage`) | LOW | done (a67ff58) |
| B1 | Apply dedup | BE | routers adopt `get_or_404` + `ensure_prefix` | LOW | done (6e833b0) |
| B2 | Apply dedup | BE | services adopt `_unwrap` | LOW | done (57e817c) |
| B3 | Apply dedup | BE | routers: raw `refers_to` → domain; adopt response serializers | MED | done (aec0878) |
| B5 | Apply dedup | FE | api modules use `get/post/put/del` | LOW | done (44448f2) |
| B6 | Apply dedup | FE | hooks adopt error toast helpers | LOW | done (9404f10 — bundled with BE C1) |
| B7 | Apply dedup | FE | adopt `format.ts` (number + date sites) | LOW–MED | done (76cc428 — bundled with BE C3) |
| B8 | Apply dedup | FE | adopt `LoadingSpinner`/`EmptyState`/`ConfirmDialog` (site-by-site) | MED | done (a0b767e — LoadingSpinner 18 sites; EmptyState ChatGallery shadow; ConfirmDialog deferred to post-C6/C8) |
| B9 | Apply dedup | FE | SSE `streamFetch` adoption (search.ts, source-chat.ts) | MED | done (cc70e9b — bundled with BE C4) |
| C1 | Split | BE | `chat.py` → package (pilot) | MED | done (9404f10) |
| C2 | Split | BE | `sources.py` → package + service extraction | HIGH | done (a0b767e + 1425043) |
| C3 | Split | BE | `models.py` → extract provider logic to service | MED | done (76cc428) |
| C4 | Split | BE | `source_chat.py` → extract streaming/graph to service | MED | done (cc70e9b) |
| C5 | Split | BE | `podcasts.py` → response-mapping helper | LOW–MED | done (952b785) |
| C6 | Split | FE | `ChatGallery.tsx` → ChatCard/ChatRow/TagEditor + hook (pilot) | MED | done (f521070) |
| C7 | Split | FE | `SourceDetailContent.tsx` → tab panels + `useSourceDetail` | HIGH | done (72888f7 — 854→258 orchestrator; useSourceDetail hook moved AS-IS; 3 tab panels; insight-delete → ConfirmDialog) |
| C8 | Split | FE | `ChatPanel.tsx` → MessageList/Composer + scroll hook | MED | done (ddf939e) |
| C9 | Split | FE | `useNotebookChat.ts` → sessions + context + send hooks | MED | done (a81a217) |

**Optional/deferred dedup** (MED risk, not readability-critical — only if time allows): audit `T2-e` (surreal-commands skeleton — raise/return semantics load-bearing), `T2-f` (model_discovery helper — per-provider field handling), `T2-k` (credential migration twins), backend small-wins `T1-g`. **Deferred entirely:** `T3-g` (fetch→TanStack migration).

---

## Verification (run per chunk, for that track)

**Backend** (see backend.md for per-chunk specifics):
- `uv run pytest tests/` after every BE chunk.
- `uv run mypy open_notebook/ api/`.
- Smoke: `uv run uvicorn api.main:app --port 5055` boots; `/docs` lists the same routes after each C-split.

**Frontend** (see frontend.md):
- `cd frontend && npx tsc --noEmit`.
- `cd frontend && npm run lint` (eslint) and `npm run test` (vitest, jsdom).
- Manual: affected screens render identically — structural splits must be visually/behaviorally invisible.

**Per-chunk gate:** user-facing behavior unchanged · call sites actually collapsed (B) or file smaller + concerns separated (C) · tests + typecheck green · diff is one focused slice.

---

## Recommended execution order

1. **Backend chat:** A1·A2·A3 → B1·B2·B3 → C1 (pilot) → C5·C3·C4 → **C2 last** (highest risk).
2. **Frontend chat (parallel):** A4·A5·A6 → B5·B6·B7·B9 → B8 → C6 (pilot)·C8·C9 → **C7 last** (highest risk).
3. C1 and C6 first within Phase C — prove the split pattern before risky C2/C7.
4. Tracks run concurrently (separate worktrees) or sequentially; they never touch the same files.

## How to run a track in a fresh chat

> "Execute the **backend** track of the codebase readability refactor. Read `.claude/plans/codebase-readability/coordinator.md` for shared rules + status, then `.claude/plans/codebase-readability/backend.md` for your chunks. Do one chunk = one commit, run the verify command between chunks, and update the Status table in coordinator.md as each chunk lands."

(Swap "backend"/`backend.md` for "frontend"/`frontend.md` in the other chat.)
