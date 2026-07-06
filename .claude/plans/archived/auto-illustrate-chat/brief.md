# Auto-Illustrate AI Chat — Goal Brief

> **Discovery output & the validated goal.** Written so the framing survives a context reset and so
> `chunk-plan` can consume it as its spec input. The "what & why", decided and grounded in the
> architecture — not the "how it's decomposed".
> **Location:** `.claude/plans/auto-illustrate-chat/brief.md` → whole dir archived to
> `.claude/plans/archived/auto-illustrate-chat/` when done.
> **Slug:** `auto-illustrate-chat` (shared with the plan in this dir). Companion: `tech-scout.md`
> (chosen tech stack — treated as decided input; not re-litigated here).

---

## Problem / real need
When the notebook-chat AI explains a concept, the answer is **text-only**. For a study/research tool,
a relevant visual (a diagram of a process, or a real image of a concrete thing) materially improves
comprehension and retention — the same reason NotebookLM-style tools and good textbooks illustrate.
Today the user has to leave the chat and search for an image themselves, breaking the study flow.

The need: **the AI's teaching messages should come with the right visual, automatically**, without
the user asking and without slowing the answer down. The visual must be *relevant* (a wrong or generic
image is worse than none — false positives are the failure mode) and must **persist across reload** so
a notebook's chat history stays illustrated.

Who it's for: the single, local, self-hosted user studying inside a notebook (the DGX-Spark stack).

## Success criteria
- After an AI chat answer that warrants it, a relevant visual **appears on that message a beat later**
  (async), without the answer itself being delayed or blocked.
- The system **picks the right mode per message**: a **Mermaid diagram** for processes/relationships/
  structures; a **searched real image** for concrete, visually-identifiable things; **nothing** for
  greetings/meta/short-facts (and when nothing clears the relevance bar — it abstains rather than
  attaching a weak image).
- The attached visual **survives page reload** and reopening the session (persisted, hydrated back onto
  the message).
- **No bad-illustration noise**: conservative gating biased toward "none"; a user who still finds it
  noisy can turn it off via a **per-notebook toggle** (default ON).
- **Zero new AI models** and **zero new always-on services**: all AI steps (gate, query-expansion,
  relevance judge, safety judge) run on the already-loaded local **qwen3.6** VLM; only free external
  image HTTP sources are added.
- Diagrams never render a raw error: invalid Mermaid **falls back to a code block**, never a red box.
- Fetched images are **safe and same-origin**: NSFW/gore screened (fail-closed), SSRF-guarded fetch,
  re-encoded to WebP, served via the existing `/api/chat/media/{file}` path.

## Constraints & non-goals
- **Constraints (hard rails, from `tech-scout.md`):**
  - Local-first/privacy: self-hosted; AI on the DGX Spark via Ollama. Reuse **qwen3.6** (VL-capable)
    for *all* AI steps — no new models. Free external image APIs are OK (server fetches + caches
    locally). Licensing not a concern for v1 (optimize for relevance).
  - **Notebook chat is synchronous** (`POST /chat/execute` returns a complete AIMessage; no token
    stream) — so enrichment must be an out-of-band async job, not part of the answer turn.
  - **Reuse the existing async stack**: surreal-commands `@command` + `submit_command` + `GET
    /commands/jobs/{id}` polling; frontend job-polling + `patchSessionMessages()` cache patch.
  - **Reuse the existing media display**: `MessageMedia` + `MediaItem{type,url,label}` + same-origin
    `/api/chat/media/{file}`; no external-domain hotlinking.
  - Chosen stack is **decided** (see `tech-scout.md` Decision Register D1–D6) and out of scope to
    re-open here: Mermaid via react-markdown plugin (strict + DOMPurify + parse-or-fallback);
    Wikimedia Commons/Wikipedia PageImages + Openverse; qwen3.6 query-expansion + VLM judge/abstain;
    two-stage local gate; qwen3.6-VL safety; httpx(byte-capped)+Pillow→WebP+SSRF guards.
- **Non-goals:**
  - **Image generation** (SDXL/diffusion) — out. We *search* for real images and *draw* diagrams; we
    never synthesize photos.
  - **Source chat** (the SSE transport) — v1 targets **notebook chat only**. Extending to source chat
    is a later follow-on.
  - **User-initiated / manual "illustrate this" actions**, editing/replacing the chosen visual,
    captions/attribution UI, multi-image galleries per message — not v1.
  - **Licensing/attribution enforcement**, museum-source cascade (Smithsonian/Met/Pixabay), and any
    second relevance model (SigLIP2) or NSFW pre-filter (Falconsai) — explicitly deferred per
    tech-scout D2/D3/D4.
  - Re-running illustration on **historical** messages — only messages produced after the feature is on
    get illustrated (no backfill).

## Assumptions (surfaced)
- **[unconfirmed — spike] qwen3.6 vision works via this path.** qwen3.6 is registered as a `language`
  model; sending `[{text},{image_url}]` data-URI blocks via Ollama's OpenAI-compat API is *expected* to
  work (the chat graph already builds such blocks at `open_notebook/graphs/chat.py:70-105`) but is
  **untested here**. → tech-scout **R3 spike** before building the relevance/safety services.
- **[unconfirmed — spike] Relevance is good enough on abstract concepts.** The headline product risk.
  → tech-scout **R4 spike**: query-expansion + Wikimedia/Openverse + VLM-judge on ~10 real study
  concepts, eyeball hit rate before committing the full image pipeline.
- **[confirmed] The async job + frontend polling + cache-patch stack is reusable as-is** (see findings).
- **[confirmed] A SurrealDB sidecar is greenfield** — no `chat_message` record exists today.
- **[assumed] additional_kwargs is not fed back to the LLM as prompt content** — only `.content` is, so
  attaching media via the sidecar (not the checkpoint) keeps illustration data out of conversational
  state cleanly. (Sidecar choice sidesteps this entirely.)

## Architectural findings (decision-axis depth)
> Confirmed facts that SHAPE the goal/data-model. Paths are evidence. File/signature enumeration is
> chunk-plan's job.

- **Already exists (reuse):**
  - **Media display end-to-end.** `_build_chat_message` hydrates `additional_kwargs['media']` →
    `MediaItem[]` (`api/routers/chat.py:303-304`); `MessageMedia.tsx` renders them; a backend job can
    mint a `/api/chat/media/{filename}` item exactly like `POST /chat/media`
    (`api/routers/chat.py:786-825`). **Note:** that GET has **no auth** today (prod caveat).
  - **Vision block builder.** `_attach_media_blocks()` already builds `image_url` data-URI blocks for
    vision models (`open_notebook/graphs/chat.py:70-105`) — reusable to send a candidate image to
    qwen3.6 for relevance/safety judging.
  - **Async job pattern, fully reusable.** `@command(...)` auto-registers on import; `submit_command`
    is fire-and-forget returning a `job_id`; status via `GET /commands/jobs/{id}` →
    `{status, result, error_message, progress}` (`commands/podcast_commands.py`,
    `api/podcast_service.py:95`, `api/routers/commands.py:74-85`). The **command worker is a separate
    process** with normal DB access.
  - **Frontend job polling already exists** (`RebuildEmbeddings.tsx:45-66`, 5s interval, stop on
    terminal status) and **`patchSessionMessages()`** mutates the TanStack cache by message id
    (`useNotebookChat.ts:209-291`) with optimistic-update machinery alongside.
- **Where the relevant state lives — the load-bearing fact:**
  - **Chat messages persist ONLY in the LangGraph SQLite checkpoint**, keyed by `thread_id` =
    session id (`open_notebook/graphs/chat.py:188-192`; state read via `chat_graph.get_state(...)` at
    `api/routers/chat.py:425-428`). The **`chat_session` SurrealDB table is SCHEMALESS metadata only**
    (title/model_override/parent_session_id/quote/tags); **there is no `chat_message` table or
    `ChatMessage` domain model** — a per-message store is greenfield.
- **Load-bearing constraints that decided the data model:**
  - **Message ids are not stable.** Messages default `id=None` → API falls back to `msg_{index}`
    recomputed per response (`api/routers/chat.py:307`) — unusable for job→message correlation. A
    **deterministic `.id` must be assigned at AIMessage creation** (`open_notebook/graphs/chat.py:180`).
    This is required in *any* persistence design, so it is a foundational sub-task, not a fork.
  - **The enrichment runs in a separate worker process.** Patching the checkpoint from there means
    cross-process SQLite writes against the same file the API writes, plus editing a *past* message in
    thread history (no first-class "update one past message" op). A SurrealDB write from the worker is
    the natural concurrency-safe fit. → **decided the persistence fork toward a sidecar.**
- **Feasibility:** Feasible and largely **assembly of existing parts** — display, vision-block builder,
  async job, polling, and cache-patch all exist. The genuinely new build is: the per-message gate/route,
  the diagram + image pipelines (qwen3.6 + external search + safety/fetch), the **media sidecar table +
  stable id + hydrate-merge**, and the **per-notebook toggle**. Two spikes (R3 vision, R4 relevance)
  gate the image half.

## Solution direction
- **Chosen:** Build auto-illustration as an **async progressive-enhancement job** layered on the
  existing chat + media + command infrastructure, with the chosen tech-scout stack. After a notebook
  chat answer is produced (and the AIMessage gets a **deterministic stable id**), the API submits a
  surreal-commands enrichment job and returns the answer immediately (plus an `illustration_job_id`).
  The worker: **gates** the message (heuristic + qwen3-embedding pre-filter → qwen3.6 JSON-schema
  decision), **routes** to *diagram* (qwen3.6 emits a single strict Mermaid block) or *image* (qwen3.6
  query-expansion → Wikimedia/Openverse search → qwen3.6 VLM relevance judge with **abstain** →
  qwen3.6-VL safety, fail-closed → SSRF-guarded httpx fetch → Pillow→WebP → store under
  `CHAT_MEDIA_FOLDER`), or **none**. The result (a `MediaItem`) is written to a **new SurrealDB
  `chat_message_media` sidecar keyed by the stable message id**; the chat hydrate path
  (`_build_chat_message`) **merges sidecar media** into the response so it survives reload. Diagrams
  render client-side via the react-markdown Mermaid plugin (strict + DOMPurify + **fallback-to-code-block**).
  The frontend **polls the job** and **patches the message in cache** when it completes. A
  **per-notebook toggle (default ON)** gates whether the job runs at all; gating biases hard toward
  "none".
  - **v1 ships BOTH modes** (diagram + image), routed per message — the gate/route/job/persistence/
    toggle infra is shared, so most of the build is common either way and this delivers the full vision.
- **Rejected alternatives:**
  - **Persistence by patching the LangGraph checkpoint** (mutate `additional_kwargs['media']` and
    re-save) — rejected: cross-process SQLite contention with live chat, fragile editing of past
    checkpoint state, no first-class single-message update, and it injects illustration data into
    conversational state. The sidecar gives clean separation and a worker-friendly write path.
    *(Cost paid: a migration + small domain model + a merge step in the hydrate read path.)*
  - **Diagram-only v1, image as fast-follow** — considered (lower risk: no external fetch/relevance/
    safety in v1). Rejected because the shared infra is the bulk of the work and the user wants the full
    per-message-routed vision; the image-specific risk is contained behind the R3/R4 spikes and the
    abstain gate instead of behind a phase boundary.
  - **Always-on / global setting for control** — rejected in favor of **per-notebook toggle** so noise
    can be silenced per study context without a code change and without an app-wide switch.
  - **Image generation, source-chat support, second relevance/NSFW models, museum cascade** — out of
    v1 scope (see Non-goals); deferred per tech-scout.

## Decision Register
> Severity & gating per `~/.claude/skills/severity-model.md`. S3+ surfaced to the user.
| ID | Decision | Severity (why) | Status | Chosen / default |
|----|----------|----------------|--------|------------------|
| G-persist | Late-arriving media stored in a **new SurrealDB `chat_message_media` sidecar** keyed by stable message id, merged in at hydrate | S4 (foundational data-model; blast radius across read path; commitment) | resolved (user) | Sidecar — *not* checkpoint patch |
| G-msgid | Assign a **deterministic stable `.id`** to the AIMessage at creation | S3 (touches shared chat graph; prerequisite for correlation) | resolved | Required in any path; do it at `graphs/chat.py:180` |
| G-scope-modes | **v1 = both modes** (diagram + image), routed per message | S3 (scope + carries image-relevance/safety risk in v1) | resolved (user) | Both; image half gated by R3/R4 spikes + abstain |
| G-control | **Per-notebook toggle, default ON** | S3 (product/UX; genuine fork) | resolved (user) | Per-notebook toggle (new notebook field) |
| G-transport | v1 targets **notebook chat only** (sync); source chat (SSE) deferred | S2 (scope boundary) | resolved | Notebook chat only |
| G-stack | Tech stack from `tech-scout.md` (Mermaid/Wikimedia+Openverse/qwen3.6 all-AI/surreal-commands/VLM-safety) | S3–S4 | resolved (tech-scout D1–D6) | As decided there; not re-opened |

## Open Questions (surface; don't guess)
- **Q-R3 (spike, gating)** — Does qwen3.6 accept `image_url` data-URI blocks via Ollama and return a
  parseable JSON verdict? Confirm `OLLAMA_API_BASE`. *Run before building relevance/safety.*
- **Q-R4 (spike, product)** — Is relevance acceptable on **abstract** concepts (query-expansion +
  Wikimedia PageImages/Openverse + VLM-judge/abstain on ~10 real concepts)? *Eyeball hit-rate before
  committing the full image pipeline; if poor, lean harder on abstain / Wikipedia PageImages.*
- **Q-R5 (perf)** — End-to-end job latency and GPU contention with live chat on the single local
  qwen3.6 (gate + judge + safety all share it). Cap candidates judged (top-K); reconsider the deferred
  SigLIP2/Falconsai pre-filters if it hurts. *Measure during build.*
- **Q-mediaauth** — `GET /api/chat/media/{file}` has no auth today; acceptable for the local single-user
  deploy, flag for any future multi-user/prod. *Default: accept for v1.*
- **Q-toggle-grain** — Confirm the toggle lives on the **notebook** (vs chat session). *Default:
  notebook-level field, inherited by its sessions.*

## Handoff → chunk-plan
Goal is framed and all S3+ forks are resolved. Next: run **`chunk-plan` on `auto-illustrate-chat`**. It
will detect this brief as the spec input, do the implementation-depth analysis (exact files,
signatures, reuse handles, file-ownership), and decompose into (parallelized) chunks in this same
`.claude/plans/auto-illustrate-chat/` directory. **Recommend scheduling the R3 (qwen3.6 vision) and R4
(relevance-on-abstractions) spikes as the first chunks** — they de-risk the entire image half before
the bulk of the pipeline is built.
