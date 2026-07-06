> ⚠️ **SUPERSEDED (2026-06-23)** by the merged plan at `.claude/plans/chat-foundation/coordinator.md`,
> which combines this feature with per-chat-context (shared files + single migration 18, worktree
> orchestrator). Execute from there, not here. `brief.md` + `tech-scout.md` in this dir remain the
> reference inputs the merged plan points to. Delete this dir when chat-foundation is archived.

# Auto-Illustrate AI Chat — Coordinator / Index

> **Shared source of truth for a multi-track plan.** This file holds everything common to all tracks.
> Each track is executed from its own file (`<track>.md` in this directory) by its own chat.
> A track chat reads THIS file first, then owns exactly one track file.
> **Location:** `.claude/plans/auto-illustrate-chat/coordinator.md` → the whole directory is archived to
> `.claude/plans/archived/auto-illustrate-chat/` once every track is ☑.
> **Spec inputs (read for context):** `brief.md` (validated goal, all S3+ scope forks resolved) and
> `tech-scout.md` (chosen tech stack D1–D6) in this directory. The brief is authoritative for *what & why*.

## How to run this plan (read first)
1. Pick a track whose deps are ☑ in the Global status table below and whose row is **runnable now**.
2. Open its file `<track>.md` (this directory) in a fresh chat; that file is self-contained.
3. You may run every **concurrent** track (see the matrix) at the same time in separate chats.
4. One chunk per session. On each chunk completion, update BOTH the track file's status AND the Global
   status table here, then announce "safe to clear context" and stop.
5. **Services run as systemd --user units** (`on-api`, `on-worker`, `on-frontend`); do NOT launch them.
   After backend code changes, `systemctl --user restart on-api` (and `on-worker` for command changes)
   to apply. Logs via `journalctl --user -u on-api` etc.

## Concurrency matrix
| Track | File | Depends on (must be ☑) | Concurrent with | Sequential after | Why |
|-------|------|------------------------|-----------------|------------------|-----|
| A — Foundation (data model + contracts) | `a-foundation.md` | — | S | — | Foundation; owns the shared chat/DB files |
| S — Spikes (R3 vision, R4 relevance) | `s-spikes.md` | — | A | — | Throwaway scratch scripts; no production files |
| B — Backend enrichment worker | `b-backend.md` | A (B1); **A + S** (B2, B3) | C | A | B1 needs A's contracts; image chunks gated on S |
| C — Frontend (render + poll + toggle) | `c-frontend.md` | A | B | A | Reads A's response contract + notebook field |
> Read as: `A ‖ S` run together first. Once **A is ☑**, `B ‖ C` run together (disjoint files: Python
> backend/commands vs `frontend/`). B's **image** chunks (B2, B3) additionally wait for **S ☑** and the
> spike decision gate (P-1). B's **diagram** chunk (B1) needs only A.

## Shared-file ownership (conflict map)
No file is touched by more than one track *concurrently*. The foundation files below are all owned by
**Track A** and frozen for A's duration; B and C only start after A ☑ and never edit A's files.
| File | Owning track | Other tracks must wait for | Note |
|------|--------------|----------------------------|------|
| `open_notebook/graphs/chat.py` | A | — (B/C never touch) | stable AIMessage id only |
| `api/routers/chat.py` | A | — (B/C never touch) | hydrate-merge + job submit + response contract |
| `open_notebook/domain/notebook.py` | A | — | `ChatMessageMedia` model + `Notebook.auto_illustrate` |
| `open_notebook/database/migrations/18.surrealql` (+ `_down`) | A | — | sidecar table + notebook field |
| `open_notebook/database/async_migrate.py` | A | — | register migration 18 |
| `commands/illustrate_commands.py` (NEW) | B | — | the enrichment `@command` |
| `open_notebook/graphs/illustrate.py` (NEW, or `open_notebook/illustrate/`) | B | — | gate/route/diagram/image logic |
| `frontend/**` | C | — | render, poll, toggle, types |

## Global status table
| Track | Chunk | Title | Status | Owner / session | Notes |
|-------|------:|-------|--------|-----------------|-------|
| A | A1 | Stable AIMessage id + response contract (`illustration_job_id`) | ☐ todo | | head of critical path |
| A | A2 | Migration 18 (sidecar table + `auto_illustrate`) + `ChatMessageMedia` model + notebook field | ☐ todo | | |
| A | A3 | Hydrate-merge sidecar + submit enrichment job (toggle-gated) + notebook-update passthrough | ☐ todo | | unblocks B & C |
| S | S1 | R3 vision spike + R4 relevance spike → decision gate | ☐ todo | | gates B2/B3 |
| B | B1 | Enrichment command skeleton: gate → route → **diagram** → write sidecar | ☐ todo | | needs A ☑ |
| B | B2 | **Image** pipeline: query-expansion → search → VLM relevance/abstain | ☐ todo | | needs A ☑ + S ☑ + gate |
| B | B3 | **Image** safety (fail-closed) + SSRF fetch → WebP → store → sidecar | ☐ todo | | needs B2 |
| C | C1 | Mermaid renderer in react-markdown (strict + DOMPurify + parse-or-fallback) | ☐ todo | | needs A ☑ |
| C | C2 | Job polling → invalidate session on completion (hydrate merges) | ☐ todo | | needs A ☑ |
| C | C3 | Per-notebook auto-illustrate toggle in dock-header dropdown + types | ☐ todo | | needs A ☑ |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (cross-track)
- _(none yet — planning complete 2026-06-23)_

## Context — why
See `brief.md` (full). In one line: **the notebook-chat AI's teaching messages should auto-acquire the
right visual** — a Mermaid **diagram** for processes/structures, a **searched real image** for concrete
things, **nothing** otherwise — delivered as an **async progressive-enhancement job** that never delays
the answer and **survives reload**. Single local self-hosted user (DGX Spark); all AI on the already-loaded
**qwen3.6** VLM (zero new models); only free external image HTTP sources added. False positives are the
failure mode → gating biases hard toward "none" and the image judge can **abstain**.

## Decisions log (shared)
Carried verbatim from `brief.md` (G-*) + `tech-scout.md` (D1–D6), plus planning forks resolved here (P-*).
| # | Question | Decision |
|--:|----------|----------|
| G-persist | Where does late-arriving media live? | **New SurrealDB `chat_message_media` sidecar** keyed by stable message id, merged in at hydrate — NOT a checkpoint patch |
| G-msgid | Message→job correlation | Assign a **deterministic stable `.id`** to the AIMessage at creation (`graphs/chat.py:178`) |
| G-scope-modes | What ships in v1? | **Both modes** (diagram + image), routed per message |
| G-control | Noise control | **Per-notebook toggle, default ON** (new notebook field) |
| G-transport | Which chat? | **Notebook chat only** (sync `POST /chat/execute`); source-chat (SSE) deferred |
| D1 | Diagram render | **Mermaid via react-markdown** code-block renderer; `securityLevel:'strict'` + DOMPurify on SVG + `mermaid.parse()` guard + **fallback-to-codeblock** |
| D2 | Relevance | **qwen3.6 query-expansion + qwen3.6 VLM yes/no + abstain** (rank+threshold, not absolute score) |
| D3 | Safety | **qwen3.6-VL zero-shot judge, fail-closed** (no new model in v1) |
| D4 | Image sources v1 | **Wikipedia/Wikimedia Commons (incl. PageImages) + Openverse** (Smithsonian/Met/Pixabay later) |
| D5 | Delivery | **surreal-commands job + frontend polling + persistence** |
| D6 | AI models | **Reuse qwen3.6 for ALL AI steps** (gate, expansion, relevance, safety); no new models |
| **P-1** | Spike sequencing | **Gate the image build on the spike result.** R3+R4 run as the first chunk (Track S); image chunks B2/B3 are committed only after the gate clears. Diagram mode + shared infra proceed regardless. |
| **P-2** | Toggle UI location | **Chat dock-header dropdown**, mirroring `SideChatDefaultMenu`'s Settings dropdown. |
| **P-3** | Diagram carrier | Sidecar stores the **mermaid source**; hydrate **appends a fenced ` ```mermaid ` block** to the AI message content (no new `ChatMessage` field). Frontend renders it via the C1 code-block renderer. Image mode stores a `MediaItem` merged into `.media[]`. |
| **P-4** | Frontend illustration delivery | On job completion the frontend **invalidates the session query** so the merged illustration hydrates from the backend (single source of truth), rather than hand-patching content/media client-side. |
| **P-5** | One migration | Migration **18** carries BOTH the sidecar table AND the `notebook.auto_illustrate` field (one feature, one version bump). |

### Decision Register (shared)
> Severity & gating per `~/.claude/skills/severity-model.md`. Gate: S3+ surfaced to the user. All S3+
> forks were resolved in `brief.md`/`tech-scout.md` or at this skill's scope gate (P-1, P-2).
| ID | Decision | Severity (why) | Status | Chosen / default |
|----|----------|----------------|--------|------------------|
| P-1 | Gate image build on spike result | S3 (sequencing + de-risk; carries the headline product risk) | resolved (user) | Spike-first decision gate before B2/B3 |
| P-2 | Toggle in dock-header dropdown | S3 (product/UX placement) | resolved (user) | Mirror `SideChatDefaultMenu` |
| P-3 | Diagram = appended mermaid fence (no new field) | S2 (read-path shape; reversible) | auto-decided | content-append, reuse markdown pipeline |
| P-4 | Invalidate-on-complete vs client patch | S2 (FE robustness) | auto-decided | invalidate session query |
| P-5 | Single migration 18 for both schema changes | S1 | auto-decided | one migration |
| G-persist | Sidecar (not checkpoint patch) | S4 (foundational data-model) | resolved (brief) | `chat_message_media` sidecar |
| G-msgid | Deterministic stable AIMessage id | S3 (shared chat graph; correlation prereq) | resolved (brief) | set `.id` at `graphs/chat.py:178` |
| D6 | Reuse qwen3.6 for all AI steps | S4 (foundational) | resolved (tech-scout) | no new models |

### Reconciliation (brief/tech-scout → codebase)
Confirmed during Phase-1 implementation analysis (exact signatures in **Reference index** below):
| Contract from brief/tech-scout | Codebase reality (confirmed) | Drift / note |
|---|---|---|
| Async job pattern | `@command(name, app="open_notebook", retry=…)` → `submit_command("open_notebook", name, args)` → poll `GET /commands/jobs/{id}` | none — reuse exactly (podcast pattern) |
| Media display | `MediaItem{type,url,label,duration?}`; `MessageMedia.tsx`; served via `GET /api/chat/media/{file}` (no auth) | none — Q-mediaauth accepted for v1 |
| Vision blocks | `_attach_media_blocks()` / `_media_to_data_uri()` build `image_url` data-URI blocks (`graphs/chat.py:70-105`) | reuse for relevance + safety judge |
| Messages persist only in LangGraph SQLite checkpoint | confirmed; `chat_session` table is schemaless metadata only; **no `chat_message` table** | sidecar is greenfield (G-persist) |
| Unstable message id (`msg_{index}`) | `_build_chat_message(..., fallback_index)` uses `getattr(msg,"id",f"msg_{fallback_index}")` (`chat.py:307`) | A1 assigns a real `.id` so the fallback is never hit for AI msgs |
| Frontend job polling | `RebuildEmbeddings.tsx:45-66` (5s interval, stop on terminal status) | reuse pattern |
| Cache patch | `patchSessionMessages()` (`useNotebookChat.ts:276-287`); query key `notebookChatSession(sessionId)` | C2 uses `invalidateQueries` on this key (P-4) |
| Migration numbering | latest registered = **17** (`async_migrate.py:127`); files are `N.surrealql` (+ `N_down`) | next = **18** |
| Notebook field precedent | `chat_tag_colors` added in migration 17 as `FLEXIBLE TYPE object DEFAULT {}`; `notebook` table is SCHEMAFULL | mirror for `auto_illustrate option<bool> DEFAULT true` |

## Conventions / translation notes (shared)
- **Migrations:** create `18.surrealql` + `18_down.surrealql`; register BOTH in `async_migrate.py`
  (`up_migrations` after line 129, `down_migrations` after line 182). Runs automatically on API startup.
  `notebook` is SCHEMAFULL — undeclared fields are dropped on save, so the field MUST be in the migration.
- **i18n:** every new user-facing string needs a key in `frontend/src/lib/locales/en-US/index.ts` (+ the
  other 14 locales at least stubbed with the English fallback). Toggle label/help (C3) and any error copy.
- **Domain models:** subclass `ObjectModel` (`open_notebook/domain/base.py`); set `table_name`; use
  `repo_query/repo_create/repo_upsert`; `nullable_fields` ClassVar for fields that may be null.
- **AI calls in the worker:** reuse `provision_langchain_model(context, model_id, "chat", max_tokens=…)`
  (async; the `_generate_ai_message` path at `graphs/chat.py:127-134` is the template). For
  image→model judging, reuse `_attach_media_blocks()` / `_media_to_data_uri()` to build `image_url` blocks.
- **Error handling:** wrap LLM calls with `classify_error()` (see `graphs/CLAUDE.md`). The enrichment job
  must **never** raise into the chat turn — it runs in the separate worker process; on any failure it
  writes a `mode='none'` sidecar row (or nothing) and the message simply stays text-only.
- **Model id:** the enrichment uses the already-registered local **qwen3.6** language model. Confirm its
  exact model record id from `scripts/register_ollama_models.py` / `DefaultModels` at build time (it is a
  lookup, not a fork). `OLLAMA_API_BASE` must be set (verified in S1).

## Reference index (shared)
**Primitives to reuse (exact, confirmed):**
- `_attach_media_blocks(payload: list) -> list` & `_media_to_data_uri(...)` — `open_notebook/graphs/chat.py:70-105`
- `call_model_with_messages` AIMessage return — `open_notebook/graphs/chat.py:175-180` (A1 edits line 178)
- `provision_langchain_model(text, model_id, "chat", max_tokens=8192)` — `graphs/chat.py:131`
- `_build_chat_message(msg, fallback_index) -> ChatMessage` — `api/routers/chat.py:284-315` (A3 merges sidecar; id fallback at :307)
- `execute_chat` — `api/routers/chat.py:569-648`; invoke at :630, `await session.save()` at :641, return at :648 (A1 adds `illustration_job_id`, A3 submits job after :641)
- `ExecuteChatResponse` (:166), `ChatMessage` (:104), `MediaItem` (:95) — all in `api/routers/chat.py`
- `POST /chat/media` + `GET /chat/media/{filename}` + `CHAT_MEDIA_FOLDER` + `save_uploaded_file` / `resolve_within` — `api/routers/chat.py:786-825`
- `@command` / `submit_command` / `get_command_status` — `commands/podcast_commands.py:69`, `api/podcast_service.py:96,118`, `api/routers/commands.py:74-85`; worker: `make worker-start` → `surreal-commands-worker --import-modules commands`
- `ObjectModel` base + repo fns — `open_notebook/domain/base.py:31-237`, `open_notebook/database/repository.py`
- `Notebook` model — `open_notebook/domain/notebook.py:16-24`; table schema `migrations/1.surrealql:44-52`; latest field added in `migrations/17.surrealql`
- FE: `patchSessionMessages` `useNotebookChat.ts:276-287`; query keys `query-client.ts:41-42`; `AIMessageContent` + react-markdown `components` map `ChatPanel.tsx:735-784`; `MarkdownCodeBlock` `components/source/MarkdownCodeBlock.tsx`; `MessageMedia` `components/source/MessageMedia.tsx:86-101`; job-poll `RebuildEmbeddings.tsx:45-66`; types `lib/types/api.ts` (`MediaItem` 165-170, `NotebookChatMessage` 255-270); `chatApi`/`notebooksApi` `lib/api/chat.ts`,`lib/api/notebooks.ts`; toggle pattern `SideChatDefaultMenu.tsx`

**The shared data contract (all tracks depend on this):**
- **Stable id:** every AI message returned by `/chat/execute` and `/chat/sessions/{id}` carries a real
  `.id` (assigned A1). The enrichment job is submitted with `(session_id, message_id=that id, notebook_id, model_id)`.
- **`ExecuteChatResponse.illustration_job_id: Optional[str]`** — present when an enrichment job was
  submitted (toggle ON + an AI message produced). The frontend polls it (C2).
- **Sidecar row `chat_message_media`:** `{ message_id, session_id, mode: 'image'|'diagram'|'none',
  media: MediaItem|null, diagram: string|null, created }`, one per illustrated message, keyed/indexed on
  `message_id`. Written by Track B. Read & merged by Track A's hydrate (`_build_chat_message`):
  `mode='image'` → append `media` to `ChatMessage.media`; `mode='diagram'` → append a fenced
  ` ```mermaid\n{diagram}\n``` ` block to `ChatMessage.content` (P-3); `mode='none'` → nothing.
- **Job output (CommandOutput):** `{ success, mode, message_id, error_message?, processing_time }` — C2
  only needs the terminal status; on success it invalidates the session query and the merged result
  hydrates from the backend (P-4).

### Post-exploration refinements (confirmed APIs)
- AIMessage return is via `ai_message.model_copy(update={...})` at `graphs/chat.py:178` — add `"id"` to
  the update dict (LangChain `AIMessage.id` is a first-class optional field; it persists in the checkpoint).
- `submit_command(...)` returns a `RecordID` → must be `str(...)`-ified (see `podcast_service.py:96`).
- `get_state` is sync (`SqliteSaver`) → called via `asyncio.to_thread` in `execute_chat`.
- `notebook` table is **SCHEMAFULL**; migration 17 used `FLEXIBLE TYPE object DEFAULT {}` for an object
  field — for a bool use `TYPE option<bool> DEFAULT true` (mirror `archived` in `migrations/1.surrealql:47`).

## Completion & archival
The track that marks the **last** chunk ☑ (sees every track complete in the Global status table) appends
a final Changelog line and moves the **whole feature directory** to
`.claude/plans/archived/auto-illustrate-chat/`
(`mkdir -p .claude/plans/archived && mv .claude/plans/auto-illustrate-chat .claude/plans/archived/`),
then tells the user the plan is complete and archived. Likely the last to finish is **B3** or **C3**.

## Open Questions (shared — defaults chosen, surface if they bite)
- **Q-R5 (perf)** — End-to-end job latency + GPU contention on the single qwen3.6 (gate + judge + safety
  all share it with live chat). *Default: cap candidates judged (top-K≈3); measure in B; reconsider the
  deferred SigLIP2/Falconsai pre-filters (D2/D3) only if it hurts.*
- **Q-mediaauth** — `GET /api/chat/media/{file}` has no auth. *Default: accept for the local single-user
  deploy; flag for any future multi-user/prod.*
- **Q-modelid** — exact qwen3.6 model record id for `provision_langchain_model`. *Default: look it up from
  `register_ollama_models.py`/`DefaultModels` at build; not a fork.*