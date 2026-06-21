# Handoff: Claude Agent SDK chat integration (+ source-ingestion follow-up)

**For:** a fresh Claude Code session continuing this work
**Purpose:** resumable TODO so the current chat can be cleared
**Date:** 2026-06-21
**Branch:** `claude-agent-integration` (working dir `/Users/alexopoulos/learn/open-notebook-claude-sdk`)

## TL;DR
A chunked plan to let Open Notebook chat talk to Claude via the user's **Claude Max subscription**
(no API key) is **~95% done**: Chunks 0–4 are ☑ verified, Chunk 5 (docs + end-to-end) is ◐ and needs
only a **human browser walkthrough** before being marked done and the plan archived. Separately, the
user found that **PDF/source upload fails** — that is NOT part of the plan; it needs an embedding
provider (the subscription can't embed) and a fix for transformations. Chosen direction: a free local
**Ollama** embedder + transformation model.

## Background & Goal
**Open Notebook** = self-hosted NotebookLM alternative (FastAPI backend in `api/` + `open_notebook/`,
Next.js frontend in `frontend/`, SurrealDB). Goal of this work: route the chat to Claude through the
already-logged-in **Claude Code CLI** (subscription auth, no `ANTHROPIC_API_KEY`), giving Claude full
agent tools **plus** custom tools to read the user's notebooks/sources/notes. Execution is driven by
the living plan doc and the `chunk-plan-execute` skill.

**Single source of truth:** `.claude/plans/claude-agent-integration.md` — read it fully first. It has
the Status table, Decisions log (10 decisions), Conventions/gotchas, per-chunk Verify blocks, and a
full Changelog of what landed and how it was verified.

## Key decisions & conclusions so far
- **Subscription auth via `cli_path=~/.claude/local/claude`** (the `claude` binary isn't on PATH for
  subprocesses). `permission_mode="bypassPermissions"`. No API key. (Decisions #1,#2,#7)
- **Intercept the `claude_agent` provider sentinel only in the chat graph** (`graphs/chat.py`) before
  the Esperanto/ModelManager path — Esperanto has no `claude-agent` provider and errors if reached.
- **Registered model `model:q9itqn4k3m9zt77shisq`** (provider `claude_agent`, name `claude-agent`),
  set as default **chat + tools + large-context** (user choice, Decision #9).
- **Q-tool-dbloop resolved (Decision #10):** in-process MCP tool callbacks CAN hit SurrealDB directly —
  `repo_query` opens a fresh per-call connection on the current loop, so no loop-binding issue. No REST
  fallback needed. Verified live in both the main-thread loop and the node's thread+new-loop path.
- **Non-Claude regression** verified structurally + unit only (no other model/credential configured;
  user kept the subscription-only setup).

## Current state
**Plan chunks** (`.claude/plans/claude-agent-integration.md`):
- 0 Dependency + auth spike — ☑
- 1 `open_notebook/ai/claude_agent.py` (backend module) — ☑
- 2 `scripts/register_claude_agent_model.py` + `.env.example` + dev bring-up — ☑
- 3 `_generate_ai_message` hook in `open_notebook/graphs/chat.py` — ☑
- 4 `open_notebook/ai/claude_agent_tools.py` (6 in-process MCP tools) — ☑
- 5 `docs/claude-agent.md` + README pointer + end-to-end verify — ◐ **IN PROGRESS**
- D Deferred (session-resume, streaming, source_chat, true sandbox, concurrency) — not built

**Chunk 5 status:** docs written (`docs/claude-agent.md`, README pointer added), and all three message
types were proven at the **API level** through `POST /api/chat/execute`: plain (`CHAT_OK`), web tool
(WebFetch → "Example Domain"), ON-data tools (`list_notebooks` → real notebook; `search` → "Testville").
**Only remaining step:** the human picks `claude-agent` in the UI model picker at http://localhost:3000
and sends the three message types in the real browser. Then: mark Chunk 5 ☑, append final Changelog
line, and **archive** (`mkdir -p .claude/plans/archived && git mv` the plan into `archived/`).

**Running dev stack** — ⚠️ the API/worker/frontend were started as **session-scoped background
processes in the previous chat and will likely be DEAD in your new session.** SurrealDB (Docker)
persists. **Verify ports and restart what's down:**
- SurrealDB :8000 — `make database` (= `docker compose up -d surrealdb`); data persists on disk.
- API :5055 — `make api` (= `uv run --env-file .env run_api.py`); `/health` should return healthy.
- Worker — `make worker` (= `uv run --env-file .env surreal-commands-worker --import-modules commands`).
- Frontend :3000 — `make frontend` (Next.js; `npm install` already done in `frontend/`).

**Working tree:** new files `open_notebook/ai/claude_agent.py`, `open_notebook/ai/claude_agent_tools.py`,
`scripts/register_claude_agent_model.py`, `docs/claude-agent.md`; edits to `open_notebook/graphs/chat.py`,
`.env.example`, `README.md`. Local `.env` exists (gitignored; auth OFF, `SURREAL_URL=ws://localhost:8000/rpc`).
Nothing committed yet.

## Open questions / blockers
- **Chunk 5 browser walkthrough** is the only gate to finishing the plan — a human step (can't be
  automated here). API-level proof already exists if the user decides to accept that instead.
- **Source ingestion fix** (below) is awaiting the user's go on the Ollama route.

## Recommended next steps

### Track A — finish the chat plan (in scope)
1. Restart any down services (see above); confirm http://localhost:3000 loads and
   `curl -s localhost:5055/api/models?type=language` shows the `claude_agent` model.
2. Have the user do the browser walkthrough: pick **claude-agent** in the chat model picker, send
   (a) `Reply with exactly: CHAT_OK`, (b) `Use web fetch to get https://example.com and tell me its H1`,
   (c) `List my notebooks` / a search. On success → mark Chunk 5 ☑ in the plan, add the final Changelog
   line, and **archive the plan** per its "Completion & archival" section.

### Track B — source/PDF ingestion fails (OUT OF SCOPE of the plan; user requested) 
**Root cause (two independent failures, both config — the PDF itself parses fine):**
1. **Transformation step** → `Provider 'claude-agent' not supported`. Transformations use
   `default_transformation_model`, which is null → falls back to `default_chat_model` = `claude-agent`,
   which only the chat node intercepts; the transformation graph routes it into Esperanto → crash.
2. **Embedding step** → `No embedding model configured`. Semantic search needs an embedding model;
   none is set, and **the Claude subscription/Agent SDK cannot produce embeddings** (Anthropic has no
   embeddings API — they point to Voyage). So embeddings always need a separate provider.

**Important:** the uploaded PDF's text **is already saved** — `source:vi1zlntfr5c3yvrdswim`
("Modern Greek Grammar Notes.pdf", **281,733 chars**, **0 embedded chunks**). Claude can already read it
via the `get_source` tool; only *semantic vector search* is missing. The "failed" badge = the embedding
sub-job only.

**Chosen fix direction — DECIDED 2026-06-21 (free, no API key): Ollama on the user's NVIDIA DGX Spark.**
Hybrid: **keep Claude Agent as `default_chat_model`** (agentic chat, the built feature); route **all
non-chat work to a local Ollama model on the Spark**. This single config change fixes BOTH failures at
once (the transformation/summary crash AND embeddings) with **zero code** — no BaseChatModel adapter
needed. The Spark has **128 GB unified memory**, so the box is not memory-constrained — run a top-tier
embedder, not a tiny one.

**Model choices (researched 2026-06-21, see Sources):**
- **Embeddings → `qwen3-embedding:8b`** — #1 open-source on MTEB (70.58), Apache-2.0, 32K context, 4.7 GB
  (trivial on the Spark). Use it at **1024 dims** (Matryoshka-truncate + renormalize) for a good
  storage/speed/quality balance in SurrealDB; 4096 if max quality is wanted. (Chosen over the old
  `nomic-embed-text` pick — nomic only wins on size/CPU, irrelevant on a Spark.)
- **Transformations + large-context → `qwen2.5:32b-instruct`** — 128K context, strong, fast enough.
  (Replaces the old `llama3.2` pick.) `qwen2.5:72b` / `llama3.3:70b` if more muscle is wanted.

**Steps when the user is ready (Spark must be running Ollama and reachable first — BLOCKING prereq):**
1. On the Spark: `ollama pull qwen3-embedding:8b` and `ollama pull qwen2.5:32b-instruct`; expose Ollama on
   the network (`OLLAMA_HOST=0.0.0.0:11434`, restart). Confirm `curl http://<spark>:11434/api/tags`.
2. In `.env`: set `OLLAMA_API_BASE=http://<spark-address>:11434`.
3. Add an Ollama **credential**; register an **embedding** model (`qwen3-embedding:8b`) and a **language**
   model (`qwen2.5:32b-instruct`) via the Credentials/Models UI or `/api/credentials` + `/api/models`.
4. Repoint defaults (`/api/models/defaults`), keeping chat on Claude:
   - `default_chat_model` = `claude_agent` (UNCHANGED)
   - `default_embedding_model` = qwen3-embedding model
   - `default_transformation_model` = qwen2.5 model  ← stops the summary crash
   - `large_context_model` = qwen2.5 model  ← ⚠️ a >105k-token transformation routes here and would
     otherwise hit the `claude_agent` sentinel and crash again (provision.py:23)
   - `default_tools_model` = qwen2.5 model
5. Re-run processing: `POST /api/sources/source:vi1zlntfr5c3yvrdswim/retry` (or re-upload). Verify
   embedded chunks > 0 and status = done; then run a semantic search and generate a source summary.

**Implementation footguns to verify when wiring up (do NOT skip):**
- **Query/passage asymmetry:** Qwen3 (like bge/e5/nomic) expects an instruction prefix on the QUERY but
  not on stored documents. Check `open_notebook/utils/embedding.py` embeds query vs. passage correctly;
  getting this wrong silently tanks retrieval quality.
- **Dimension lock-in:** pick the embedding dimension ONCE. Changing the dim (or the model) requires
  re-embedding the ENTIRE corpus — vectors must share one space. SurrealDB stores `array<float>` so the
  dim isn't schema-fixed, but it must be consistent across all docs + queries.

**Phase-2 / future (documented, not now):** `bge-m3` if native dense+sparse hybrid is wanted (pairs with
ON's existing full-text + vector search, but the sparse half needs code); add a **Qwen3-Reranker** stage
on top of `vector_search` (highest-ROI retrieval upgrade after embeddings; stays local).

**Sources (embedding research, 2026-06-21):** Morph "Best Ollama Embedding Models 2026"
(morphllm.com/ollama-embedding-models); Ollama library (ollama.com/library/qwen3-embedding); MTEB
leaderboard Mar 2026 (awesomeagents.ai); Milvus "Best Embedding Model for RAG 2026"; BentoML
open-source embeddings guide.

Alternative the user is also considering: just accept the subscription-only limitation (chat works;
ingestion needs a real provider) and document it in `docs/claude-agent.md`.

## Reference material
- **Plan / source of truth:** `.claude/plans/claude-agent-integration.md` (resume prompt + full Changelog inside).
- **Registered model id:** `model:q9itqn4k3m9zt77shisq` (provider `claude_agent`).
- **API routing:** everything is under the **`/api`** prefix (e.g. `/api/models?type=language`,
  `/api/models/defaults`, `/api/chat/execute`). Auth is **OFF** (no `OPEN_NOTEBOOK_PASSWORD`).
- **Gotchas:** from source use `SURREAL_URL=ws://localhost:8000/rpc` (not `surrealdb:8000`). Standalone
  scripts must run from the repo root or with `uv run --env-file .env …` so `load_dotenv()` finds `.env`
  (otherwise `SURREAL_*` are unset and the DB client silently hits an empty namespace). Lint/type:
  `uv run ruff check .` and `make lint`/`uv run mypy …` (the bare `ruff`/dev-extra gotchas are documented
  in the plan); mypy baseline = 82 errors / 19 files, all pre-existing.
- **Failing source:** `source:vi1zlntfr5c3yvrdswim` in notebook `notebook:ktlv15n5623uwxx1l37o`.
- **Make targets:** `make database | api | worker | frontend` (NOT `make start-all` — it's broken,
  references a non-existent `docker-compose.dev.yml`).
