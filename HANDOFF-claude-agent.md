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

**Chosen fix direction (free, no API key): local Ollama.** Steps when the user is ready:
1. Install + run Ollama (`brew install ollama` then `ollama serve`), or the user installs it.
2. `ollama pull nomic-embed-text` (embeddings) and `ollama pull llama3.2` (small LLM for transformations).
3. In Open Notebook: add an Ollama **credential**, register an **embedding** model (`nomic-embed-text`)
   and set it as `default_embedding_model`; register `llama3.2` and set `default_transformation_model`
   (so transformations stop routing to `claude-agent`). Ollama base URL defaults to
   `http://localhost:11434` (env `OLLAMA_BASE_URL` / `OLLAMA_API_BASE` if needed). The Credentials/Models
   UI or `/api/credentials` + `/api/models` endpoints can do this.
4. Re-run processing: `POST /api/sources/source:vi1zlntfr5c3yvrdswim/retry` (or re-upload). Verify
   embedded chunks > 0 and status = done.

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
