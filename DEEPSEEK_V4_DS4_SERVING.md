# DeepSeek-V4 local serving (ds4 / DwarfStar) — setup record & forward concerns

**Date:** 2026-06-23
**Box:** DGX Spark, GB10 Grace-Blackwell (aarch64, GPU `sm_121`), 128 GB unified memory
(~121 GiB visible), CUDA 13, driver 580.
**Goal:** expose the local DeepSeek-V4 Flash model as an OpenAI-compatible endpoint for OpenWebUI /
LangChain, that loads on demand and unloads when idle (Ollama-style), and coexists with Ollama.

---

## 1. What this is (key facts)

- The engine is **antirez's `ds4` / "DwarfStar"** (`~/apps/ds4`, remote `github.com/antirez/ds4.git`)
  — a from-scratch C inference engine for DeepSeek-V4 only. **Not llama.cpp, not Ollama.** It does
  not link GGML. (There is a *separate* antirez project, `llama.cpp-deepseek-v4-flash`, which is a
  llama.cpp fork — YouTube tutorials use that one. We are **not** using it; `ds4` is the more
  GB10-optimized path and was already built on this box.)
- `ds4-server` is natively **OpenAI- and Anthropic-compatible**:
  `GET /v1/models`, `POST /v1/chat/completions`, `/v1/completions`, `/v1/responses`, `/v1/messages`.
- **No authentication** in ds4-server — clients send any dummy key (e.g. `dsv4-local`).
- Model file: `~/models/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf` (81 GB,
  the supported 2-bit Flash quant; arch `deepseek4`, 256-expert MoE, 1M max ctx).
- Model id for clients: **`deepseek-v4-flash`** (thinking) or **`deepseek-chat`** (direct / no-think).

### Memory reality (measured, important)
- ds4 at `--ctx 100000` occupies **~103 GB effective** in the unified pool while loaded.
  (Its process RSS is only ~0.8 GB — the ~80 GB model lives in CUDA unified memory, which `free`
  counts as "used" but does not attribute to the PID.)
- ds4's RAM-shrinking **SSD streaming** *is* available on CUDA/GB10 (an earlier "Metal-only" claim
  was wrong) but we are **not** using it — lazy unload solves the footprint problem instead.
- KV **disk cache** is enabled (`~/.ds4/kv`) so re-sent long prompts skip re-prefill.

---

## 2. What we built — lazy "activator" lifecycle

ds4-server has **no native idle-unload / lazy-load** (confirmed in source). So a thin wrapper
provides it:

```
client ──> 127.0.0.1:8080  ds4-activator.service  (always-on, ~12 MB, enabled at boot)
                              │  • GET /v1/models  -> served from cache, NEVER wakes the model
                              │  • OPTIONS (CORS)  -> answered locally, never wakes
                              │  • inference POST  -> start backend, stream reply, reset idle timer
                              ▼  starts/stops on demand
           127.0.0.1:8081  ds4-backend.service     (the real ds4-server; lazy, "static" = not enabled)
                              loads ~103 GB on wake; auto-STOPPED after 5 min idle -> frees all memory
```

### Files / components
| Path | Role |
|---|---|
| `~/.local/bin/ds4-activator.py` | stdlib reverse-proxy: lazy-start + idle-stop + streaming + models cache |
| `~/.config/systemd/user/ds4-activator.service` | always-on proxy on `:8080` (enabled) |
| `~/.config/systemd/user/ds4-backend.service` | real ds4-server on `:8081` (lazy, not enabled) |
| `~/.ds4/kv` | ds4 KV disk cache |
| `~/.ds4/models-cache.json` | cached `/v1/models` body served while backend is down |

### Ports on this box (for reference)
`:8080` ds4-activator · `:8081` ds4-backend (when awake) · `:11434` Ollama ·
`:8000` SurrealDB (container) · `:3000` the `~/learn` Next.js app.
(ds4's default `:8000` was avoided because SurrealDB owns it.)

### Tunables (env in `ds4-activator.service`, then `systemctl --user restart ds4-activator`)
- `DS4_ACT_IDLE_TIMEOUT=300` — idle seconds before unloading the model (currently **5 min**).
- `DS4_ACT_READY_TIMEOUT=180` — max wait for cold model load.
- `DS4_ACT_BACKEND_PORT=8081`, `DS4_ACT_LISTEN_PORT=8080`, etc.

---

## 3. How to use it

**Client connection (OpenWebUI / LangChain / any OpenAI client):**
- Base URL: `http://127.0.0.1:8080/v1`  (localhost-only by design; see concern #2)
- API key: any non-empty string (e.g. `dsv4-local`)
- Model: `deepseek-v4-flash` (or `deepseek-chat`)

**LangChain:**
```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(base_url="http://127.0.0.1:8080/v1", api_key="dsv4-local",
                 model="deepseek-v4-flash")
```

**Ops commands:**
```sh
systemctl --user status ds4-activator        # proxy (always on)
systemctl --user status ds4-backend          # model (up only when in use)
journalctl --user -u ds4-activator -f        # see wake/idle-stop events
journalctl --user -u ds4-backend -f          # see model load
curl -s 127.0.0.1:8080/v1/models             # safe; does NOT wake the model
```

### Verified behavior (measured 2026-06-23)
- `GET /v1/models` while idle → served from cache, backend stayed stopped. ✅
- First `POST /v1/chat/completions` → cold-loaded + replied in **~12 s**; backend active. ✅
- After idle timeout → backend auto-stopped, RAM dropped **110 GB → 4 GB**. ✅

---

## 4. Forward concerns / open items

### ✅ #1 — Ollama ↔ ds4 memory overlap (RESOLVED 2026-06-23)
**Built & verified.** Big-only eviction (keep the embedder) + a cross-process heavy-slot lock +
activator preflight admission control + a symmetric **ollama-gate** (:11435) + a Qwen/DS4 **mode API**
(`POST :11435/_control/mode`). ds4 + embedder co-reside (~115 GB); heavy Qwen and ds4 swap safely
across the single heavy slot; over-commit is refused, never attempted. App repointed through the gate.
Full record: `.claude/plans/so-think-about-the-idempotent-kernighan.md`. One sudo drop-in still pending
(`OLLAMA_KEEP_ALIVE`/`MAX_LOADED_MODELS`/`NUM_PARALLEL` — see that doc). Original analysis kept below.

Lazy unload fixes the *idle* case, but **both being active at once can still over-commit memory:**

| Concurrent | Total | Fits 121 GiB? |
|---|---|---|
| ds4 + `qwen3-embedding:8b` (~12 GB) | ~115 GB | ✅ (tested OK) |
| ds4 + `qwen3.6:35b` (~23 GB) | ~126 GB | ❌ |
| ds4 + `gpt-oss:120b` (~65 GB) | ~168 GB | ❌ |

**Plan being decided (paused for input):**
- Add **eviction-on-wake** to the activator: before starting ds4-backend, call Ollama
  `GET /api/ps` and unload conflicting models via `POST /api/generate {"model":NAME,"keep_alive":0}`.
  Open choice: evict only **big** models (>~20 GB, keep the embedder so RAG coexists) **vs** strict
  evict-all (one model resident ever).
- Make **Ollama lazy** too: `OLLAMA_MAX_LOADED_MODELS=1` + short `OLLAMA_KEEP_ALIVE` (system-service
  env — needs `sudo`, see #3).
- **Reverse direction** (a big Ollama model requested *while* ds4 is mid-generation) is the hard
  case. Lightweight option: rely on ds4's 5-min idle release + Ollama's own memory pre-check
  (it should offload/refuse rather than hard-crash). Bulletproof option: a shared mutual-exclusion
  lock + small wrapper around the app's Ollama calls (follow-up build).

> **Decision needed:** eviction policy (big-only vs all) and whether to build the reverse-direction lock.

### ⚠️ #2 — OpenWebUI not connected yet; localhost-only binding
- No OpenWebUI is installed on this box (the `:3000` service is the `~/learn` Next.js app).
- ds4 is bound to **127.0.0.1 only**. Implications:
  - OpenWebUI native on this box → `http://localhost:8080/v1` works.
  - OpenWebUI in Docker on this box → recreate with `--network host`, then `http://localhost:8080/v1`.
  - OpenWebUI on **another machine** → cannot reach it; would need to rebind activator (and backend)
    to `0.0.0.0` (LAN, still **unauthenticated** — only on a trusted network).

### ⚠️ #3 — Pending `sudo` step: Ollama lazy config
Ollama is a **system** service with an existing drop-in. To make it release memory when idle (and
never stack models), add (needs sudo):
```sh
sudo tee /etc/systemd/system/ollama.service.d/10-coexist.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=2m"
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### Notes / lower-priority
- **Cold-start latency:** first message after idle waits ~12 s for the model to load (same tradeoff
  as Ollama). Tune via `DS4_ACT_IDLE_TIMEOUT` if you want it to stay warm longer.
- **Beta software:** `ds4` is days-old beta. If generation looks wrong, capture with
  `ds4-server --trace` (run the backend manually) and check against antirez/ds4 issues.
- **Embedder footprint:** `qwen3-embedding:8b` loaded at 40960 ctx shows as ~12 GB; an embedding
  model doesn't need that much context — capping its `num_ctx` would reclaim several GB if you want
  more headroom for ds4 + embedder.
- **SSD streaming (unused):** `ds4-server --ssd-streaming --ssd-streaming-cache-experts NGB` would
  cut ds4's resident footprint to ~45–60 GB (always-on, slower generation). An alternative to lazy
  unload if you ever want ds4 permanently warm while leaving room for other models.

---

## 5. Quick "is it healthy?" checklist
```sh
systemctl --user is-active ds4-activator   # -> active
systemctl --user is-enabled ds4-activator  # -> enabled
ss -tln | grep 8080                        # -> activator listening
curl -s 127.0.0.1:8080/v1/models | head    # -> lists deepseek-v4-flash (no wake)
# real test (wakes model ~12s):
curl -s 127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-v4-flash","think":false,"max_tokens":16,"messages":[{"role":"user","content":"hi"}]}'
```
