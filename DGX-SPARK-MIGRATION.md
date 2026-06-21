# DGX Spark migration + local AI — TODO / plan

> **Living to-do for moving Open Notebook development onto the user's NVIDIA DGX Spark and turning on
> local AI (embeddings + transformations) while keeping Claude Code (subscription) for agentic chat.**
> Created 2026-06-21. Self-contained so a fresh session can execute it. Companion to
> `HANDOFF-claude-agent.md` (Track B has the deepest detail on the AI-wiring step) and
> `.claude/plans/claude-agent-integration.md` (the chat integration, near-complete).

---

## Goal & shape
- **Migrate dev** from the Mac to the **DGX Spark** (GB10 Grace-Blackwell, 128 GB unified memory, DGX OS
  = Ubuntu/ARM64 + CUDA). The Spark becomes the always-on Open Notebook dev/inference box.
- **Hybrid AI:** keep **Claude Agent** (Claude Code subscription) as `default_chat_model`; run **Ollama on
  the Spark** for everything non-chat (embeddings + transformations + ask + large-context). Co-located, so
  `OLLAMA_API_BASE=http://localhost:11434` on the Spark.
- This **also fixes** the current `default for type=transformation` summary crash AND the
  `No embedding model configured` search failure — with **zero code**, purely config.

## Status
| # | Track | Status | Notes |
|--:|-------|--------|-------|
| 1 | Migrate dev environment to the Spark | ☐ todo | toolchain, repo, Claude Code login, DB, bring-up |
| 2 | Local AI: Ollama models + repoint defaults (fixes summary + search) | ☐ todo | BLOCKED on Track 1 + Ollama reachable |
| 3 | Highlight/annotation feature ("saved references") | ⊘ future | larger; graph ~80% there, PDF-viewer is the lift |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ future.

---

## Track 1 — Migrate dev environment to the DGX Spark
**Platform note:** DGX OS is Ubuntu on **ARM64** (aarch64). Most things "just work" but confirm arm64
images/binaries. The Spark replaces the Mac as the host that runs the API → so **Claude Code must be
installed and logged in ON the Spark** (the Agent SDK rides on that login via `cli_path`).

**Steps:**
1. **Toolchain on the Spark:**
   - `git` + clone this repo (branch `claude-agent-integration` until merged).
   - **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`), Python 3.12.
   - **Node** (v24-ish, for the Next.js frontend).
   - **Docker** (for SurrealDB) — use the arm64 `surrealdb/surrealdb` image (it has arm64).
   - **Ollama** (native install — see Track 2).
   - **Claude Code CLI** — install AND `claude login` (subscription). Confirm the binary path; the Agent
     default is `~/.claude/local/claude` (env `CLAUDE_AGENT_CLI_PATH` to override if it differs on Linux).
2. **Python deps:** `uv sync --extra dev` (the dev tools — ruff/mypy — live under the `dev` EXTRA, NOT a
   group; `uv sync --group dev` is a no-op).
3. **`.env`** (gitignored; recreate on the Spark):
   - `SURREAL_URL=ws://localhost:8000/rpc`, `SURREAL_NAMESPACE=open_notebook`,
     `SURREAL_DATABASE=open_notebook`, creds `root`/`root`.
   - `OPEN_NOTEBOOK_ENCRYPTION_KEY=<generate a new one>` (needed for credentials).
   - Leave `OPEN_NOTEBOOK_PASSWORD` unset → auth OFF for local dev.
   - `OLLAMA_API_BASE=http://localhost:11434` (Ollama co-located on the Spark).
4. **Data decision (Open Question Q-data):** start fresh, or copy existing SurrealDB data
   (`./surreal_data/mydatabase.db`, bind-mounted) + checkpoints (`./data/sqlite-db/checkpoints.sqlite`)
   from the Mac? The existing `claude-agent` model id is `model:q9itqn4k3m9zt77shisq`; if starting fresh,
   re-run `scripts/register_claude_agent_model.py`.
5. **Bring-up (individual targets — `make start-all` is BROKEN, references a non-existent
   `docker-compose.dev.yml`):** `make database` → `make api` → `make worker` → `make frontend`.
6. **Verify:** API `/health` healthy; `GET /api/models?type=language` shows the `claude_agent` model;
   frontend on `:3000`; send a chat message → Claude responds (subscription auth works on the Spark).

## Track 2 — Local AI: Ollama models + repoint defaults  (fixes summary crash + semantic search)
**Blocked on:** Track 1 done + Ollama running/reachable. **Full detail: `HANDOFF-claude-agent.md` → Track B.**

**Models (researched 2026-06-21):**
- **Embeddings → `qwen3-embedding:8b`** — #1 open-source MTEB (70.58), Apache-2.0, 32K context, 4.7 GB.
  Use **1024 dims** (Matryoshka-truncate + renormalize) for storage/speed; 4096 for max quality.
- **Transformations + large-context → `qwen2.5:32b-instruct`** — 128K context. (`:72b`/`llama3.3:70b` for
  more muscle, slower on the Spark's ~270 GB/s bandwidth.)

**Steps:**
1. `ollama pull qwen3-embedding:8b` + `ollama pull qwen2.5:32b-instruct` on the Spark.
2. Register an Ollama **credential**, an **embedding** model (`qwen3-embedding:8b`), and a **language**
   model (`qwen2.5:32b-instruct`) — via Credentials/Models UI or `/api/credentials` + `/api/models`.
3. Repoint defaults (`/api/models/defaults`), keeping chat on Claude:
   - `default_chat_model` = `claude_agent` **(UNCHANGED)**
   - `default_embedding_model` = qwen3-embedding model
   - `default_transformation_model` = qwen2.5 model  ← stops the summary crash
   - `large_context_model` = qwen2.5 model  ← ⚠️ a >105k-token transformation routes here (provision.py:23)
     and would otherwise re-hit the `claude_agent` sentinel and crash again
   - `default_tools_model` = qwen2.5 model
4. **Verify:** generate a source summary (transformation) → succeeds; `POST /api/sources/<id>/retry` →
   embedded chunks > 0, status = done; run a semantic search → returns hits.

**Footguns (do NOT skip):**
- **Query/passage asymmetry:** Qwen3 (like bge/e5/nomic) wants an instruction prefix on the QUERY, not on
  stored documents. Verify `open_notebook/utils/embedding.py` embeds query vs. passage correctly — wrong =
  silently worse retrieval.
- **Dimension lock-in:** pick the dim ONCE. Changing dim or model = re-embed the WHOLE corpus (vectors must
  share one space). SurrealDB stores `array<float>` so it's not schema-fixed, but must be consistent.

**Phase-2 (future):** `bge-m3` for native dense+sparse hybrid (pairs with ON's full-text + vector search,
but sparse half needs code); add a **Qwen3-Reranker** stage on top of `vector_search` (highest-ROI
retrieval upgrade after embeddings; stays local).

## Track 3 — Highlight / annotation feature ("saved references")  ⊘ future
Brainstormed 2026-06-21. Link a highlighted span in a source to the note/insight/chat it spawned, with a
"saved references" directory. **Graph model is ~80% there** (SurrealDB edges: `reference`/`artifact`/
`refers_to`; `ChatSession.relate_to_source` already exists; `SourceInsight` via `add_insight`). **New
primitive needed:** an `Annotation` record with `source` + `quote` + `locator` (page/rects/prefix/suffix),
plus edges `Annotation → Source/Note/SourceInsight/ChatSession`. **Hard parts:** (1) a PDF viewer with a
selectable text layer (none exists today — ON extracts text and discards the render) and (2) durable anchor
re-matching (W3C text-quote anchor + position hints). Semantic recall over highlights depends on Track 2
(embeddings). **MVP:** start with text/markdown sources (reliable char-offset anchoring), backend records +
edges + the references view first; PDF viewer + coordinate anchoring last. Turn into its own plan doc when
prioritized.

---

## Open Questions (surface; don't guess)
- **Q-spark-addr** — Ollama running on the Spark and reachable? (If app also runs on the Spark, base URL is
  `http://localhost:11434`.) BLOCKS Track 2.
- **Q-data** — fresh DB on the Spark, or migrate the Mac's SurrealDB data + chat checkpoints? (See Track 1
  step 4.)
- **Q-clipath** — confirm the Claude Code CLI path on DGX OS/Linux (default `~/.claude/local/claude`).
- **Q-embed-dim** — 1024 (recommended) vs 4096 for `qwen3-embedding:8b`. Locked in once chosen.

## References
- Deep AI-wiring detail: `HANDOFF-claude-agent.md` → **Track B** (updated 2026-06-21).
- Chat integration (near-complete): `.claude/plans/claude-agent-integration.md`.
- Embedding research (2026-06-21): Morph "Best Ollama Embedding Models 2026"; Ollama
  `ollama.com/library/qwen3-embedding`; MTEB leaderboard Mar 2026 (awesomeagents.ai); Milvus "Best
  Embedding Model for RAG 2026"; BentoML open-source embeddings guide.
- Make targets: `make database | api | worker | frontend` (NOT `make start-all`).
