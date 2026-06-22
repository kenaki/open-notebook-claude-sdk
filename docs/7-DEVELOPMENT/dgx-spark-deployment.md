# DGX Spark Deployment & Hybrid AI Runbook

This document describes how Open Notebook is deployed on an **NVIDIA DGX Spark** (GB10 Grace-Blackwell, 128 GB unified memory, DGX OS = Ubuntu/aarch64 + CUDA) as an always-on dev/inference box, with a **hybrid AI** configuration:

- **Chat** runs on **Claude** (via the logged-in Claude Code CLI / subscription — no API key).
- **Everything else** (embeddings, transformations, large-context, tools) runs **locally on Ollama**.

It is both a record of the current setup and a runbook for rebuilding it. Companion to the root [`DGX-SPARK-MIGRATION.md`](../../DGX-SPARK-MIGRATION.md) planning doc.

---

## 1. Architecture at a glance

| Concern | Service | Port | Notes |
|---|---|---|---|
| Database | SurrealDB (Docker) | 8000 | `docker compose up -d surrealdb` |
| API | FastAPI (`run_api.py`) | 5055 | systemd user service `on-api` |
| Job worker | surreal-commands worker | — | systemd user service `on-worker` |
| Frontend | Next.js dev | 3000 | systemd user service `on-frontend` |
| Local LLM/embeddings | Ollama (systemd system service) | 11434 | co-located; `OLLAMA_API_BASE=http://localhost:11434` |

Remote access is over **Tailscale** → `http://<spark-tailscale-ip>:3000`. The frontend auto-detects the API at `:5055` from the browser host. (`.env` sets `API_HOST=0.0.0.0`; `frontend/next.config.ts` sets `allowedDevOrigins`.)

---

## 2. Hybrid AI model configuration

Three models, three jobs:

| Default slot | Model | Provider | Why |
|---|---|---|---|
| `default_chat_model` | `claude-agent` | claude_agent | Interactive chat via Claude Code subscription |
| `default_embedding_model` | `qwen3-embedding:8b` | ollama | Vectorizes sources/notes → SurrealDB `source_embedding` (powers semantic search) |
| `default_transformation_model` | `qwen3.6:35b` | ollama | Source summaries/insights |
| `large_context_model` | `qwen3.6:35b` | ollama | Jobs >105k tokens (`open_notebook/ai/provision.py`) |
| `default_tools_model` | `qwen3.6:35b` | ollama | Tool-calling / structured tasks |

**Why these models**

- **`qwen3-embedding:8b`** — official Ollama library model, text-only, ranks #1 on the MTEB multilingual leaderboard. Outputs **4096 dims natively** (the dimension we store; chosen over 1024 since the corpus is fresh and the Spark has memory to spare — no truncation code needed).
- **`qwen3.6:35b`** — a 35B-A3B **mixture-of-experts** model: 35B total but only ~3B active per token, so it runs fast on the Spark's bandwidth-bound GB10 while keeping a 256K context window. Chosen over the older `qwen2.5:32b-instruct` (dense, all params active).
- **Multimodal embedding (`Qwen3-VL-Embedding`) was evaluated and intentionally skipped:** it is community-only on Ollama (no first-party tag; native multimodal-embedding support is still pending upstream), and Open Notebook has no code path that sends images to an embedder. PDFs are already converted to text by the content-core pipeline (`open_notebook/graphs/source.py` → `Source.vectorize()`) before embedding, so a text embedder covers current needs.

**This configuration fixes two bugs** with zero code — purely config:
- the `default for type=transformation` source-summary crash (a non-chat slot pointed at the chat-only `claude_agent`), and
- the `No embedding model configured` semantic-search failure (`default_embedding_model` was null).

---

## 3. Rebuild from scratch

### 3.1 Pull the models

```bash
ollama pull qwen3-embedding:8b
ollama pull qwen3.6:35b
```

> **Ollama version matters.** `qwen3.6` requires a recent Ollama (≥ 0.30.x). An older binary fails with `unable to load model`. Upgrade with:
> ```bash
> curl -fsSL https://ollama.com/install.sh | sh
> ```
> Models persist across the upgrade (content-addressed blobs under `/usr/share/ollama/.ollama`).

Verify both respond:

```bash
ollama run qwen3.6:35b "Say OK"
curl -s http://localhost:11434/api/embed -d '{"model":"qwen3-embedding:8b","input":"test"}' \
  | python3 -c "import sys,json;print(len(json.load(sys.stdin)['embeddings'][0]))"   # -> 4096
```

### 3.2 Register the models + repoint defaults

The Ollama models need no API key — Esperanto reads `OLLAMA_API_BASE` from `.env`. Run the idempotent script (safe to re-run; it never duplicates records and leaves `default_chat_model` alone):

```bash
uv run python scripts/register_ollama_models.py
```

It creates two `provider="ollama"` Model records (`qwen3.6:35b` language, `qwen3-embedding:8b` embedding) and repoints the four non-chat default slots.

### 3.3 Verify end-to-end (through the app's own code path)

```bash
curl -s http://localhost:5055/api/models/defaults   # embedding + transformation/large/tools = ollama ids; chat = claude-agent
```

In the UI: generate a source summary (→ succeeds), re-add/retry a source (→ embedded chunks > 0), run a semantic search (→ returns hits), send a chat message (→ still Claude).

---

## 4. Running the services persistently (systemd)

The API, worker, and frontend run as **systemd user services** so they survive SSH disconnect, a closed laptop, and reboots, and auto-restart on crash. Unit files live in `~/.config/systemd/user/`:

- `on-api.service` — `uv run --env-file .env run_api.py` (WorkingDirectory = repo root)
- `on-worker.service` — `uv run --env-file .env surreal-commands-worker --import-modules commands`
- `on-frontend.service` — `npm run dev` (WorkingDirectory = `frontend/`)

Each uses `Restart=always` and an explicit `PATH` including `/home/itz_kenaki/.local/bin` (where `uv`/`node`/`npm` live).

### Enable + start (one-time)

```bash
# Let user services run with no active login session (survives logout/SSH-close):
sudo loginctl enable-linger "$USER"

systemctl --user daemon-reload
systemctl --user enable --now on-api on-worker on-frontend
```

### Day-to-day management

```bash
systemctl --user status on-api on-worker on-frontend   # health at a glance
journalctl --user -u on-api -f                          # live logs (swap unit name)
systemctl --user restart on-frontend                    # after a code change
systemctl --user stop on-api on-worker on-frontend      # stop all
```

### SurrealDB reboot-survival (optional)

The DB runs in Docker, which survives SSH-close on its own. To bring it back automatically after a **full Spark reboot**, give the container a restart policy — add under `surrealdb:` in [`docker-compose.yml`](../../docker-compose.yml):

```yaml
    restart: unless-stopped
```

then re-create it once: `make database`. (The Docker daemon auto-starts on boot, so the container then returns by itself.)

> **Note:** These units run the **dev** servers (`run_api.py`, `npm run dev`) — appropriate for an always-on dev box. For a leaner frontend you would switch `on-frontend` to `npm run build && npm start` (separate change).

---

## 5. Notes, gotchas & future work

- **`make start-all` is broken** (references a non-existent compose file). Use individual targets: `make database` / `make api` / `make worker` / `make frontend`, or the systemd units above.
- **`gpt-oss:120b`** (~65 GB) may be present from earlier experiments. Open Notebook does not use it; remove with `ollama rm gpt-oss:120b` to reclaim space.
- **Unified-memory budget.** The Spark shares 128 GB between CPU and GPU. Ollama auto-unloads idle models (~5 min `keep_alive`), so they aren't all resident at once. The `qwen3.6:35b` Q4 (~23 GB) + `qwen3-embedding:8b` (~5 GB) leave ample headroom once `gpt-oss` is gone.
- **Embedding dimension is locked in once chosen.** We store 4096 dims. Changing the dimension or embedding model requires re-embedding the entire corpus (all vectors must share one space).
- **Retrieval polish (future, needs code):** `open_notebook/utils/embedding.py` embeds queries and passages identically. Qwen3 embeddings benefit from an instruction prefix on the *query* only; adding it would modestly improve search quality. Not yet implemented.
- **Security caveat:** auth is off (`OPEN_NOTEBOOK_PASSWORD` unset) and the API binds `0.0.0.0` for Tailscale access — fine on a trusted network, but reachable beyond Tailscale on an untrusted LAN. See [`docs/5-CONFIGURATION/security.md`](../5-CONFIGURATION/security.md) before exposing it.
