# Tech-Scout — Auto-Illustrate AI Chat

- **Feature slug:** `auto-illustrate-chat`
- **Doc:** `.claude/plans/auto-illustrate-chat/tech-scout.md` (technology landscape + chosen direction)
- **Status:** FRESH — landscape complete, stack chosen, deep-compat checked. Ready for `frame-goal`.
- **Date:** 2026-06-23

---

## Feature → capabilities

When the notebook-chat AI teaches something, automatically attach a relevant visual to its message — chosen **per message** between two modes:

1. **Diagram mode** — the model draws a diagram (processes / relationships / structures), rendered client-side in the chat message.
2. **Image-search mode** — find a real-world image for concrete things (artifacts, maps, manuscripts, charts), via web search + local relevance judging, downloaded and served same-origin.

Delivered as **async progressive enhancement**: the answer streams/returns immediately; the visual appears a beat later on the already-rendered message, and survives reload.

Capabilities required: per-message **gating + mode routing** · **diagram generation + safe client render** · **image search** · **image↔text relevance** (the hard part, esp. abstract concepts) · **image safety screening** · **async delivery + persistence** of the late-arriving media.

---

## Constraints (rails)

| Rail | Value | Source |
|---|---|---|
| Local-first / privacy posture | Self-hosted; AI runs on a DGX Spark via Ollama | CLAUDE.md (privacy-first) |
| Reusable local model | **qwen3.6 is vision-language capable** — reuse it for ALL AI steps (gating, query-expansion, relevance, safety). No new models. | User |
| Model layer | Esperanto via `provision_langchain_model()`; qwen3.6 registered as `ollama` language model (`scripts/register_ollama_models.py`) | Codebase |
| External egress | **Free external image APIs OK** (server fetches + caches locally) | User |
| Licensing bar | Not a concern now — optimize for relevance | User |
| Chat transport | **Notebook chat is SYNCHRONOUS** (`POST /chat/execute` returns a complete AIMessage; no token stream). Source chat uses SSE. | Codebase (`api/routers/chat.py:569`) |
| Async job queue | **surreal-commands** exists (podcasts) and is reusable: `submit_command` → poll `GET /commands/jobs/{id}` | Codebase (`api/podcast_service.py`, `commands/podcast_commands.py`) |
| Message storage | **Messages persist ONLY in LangGraph SQLite checkpoint, NOT SurrealDB.** Hydrate reads `additional_kwargs['media']` → `MediaItem[]`. | Codebase (`api/routers/chat.py:284-315,425-428`) |
| Media display | Reuse `MessageMedia`; `MediaItem = {type:'image'|'video', url, label}`; only same-origin `/api/chat/media/{file}` served (no external-domain allowlist; `next/image` disabled) | Codebase (`MessageMedia.tsx`, `api/routers/chat.py:786-825`) |
| Frontend | Next.js 16 / React 19, TanStack Query; chat in `useNotebookChat.ts` with `patchSessionMessages()` cache patch + optimistic updates | Codebase |

---

## Technology categories

Diagram render+generate · Image-search sources · Image↔text relevance · Per-message gating/routing · Async delivery+persistence · Image safety + fetch/cache pipeline.

---

## Per-category options (top picks; ⭐ = chosen)

### 1. Diagram render + generate
| Option | Notes | License | Flag |
|---|---|---|---|
| ⭐ **Mermaid via react-markdown plugin** (`react-markdown-mermaid` / `rehype-mermaid`) | Mermaid is the DSL LLMs emit best; integrates into the existing react-markdown pipeline | MIT | ✅ low churn |
| Streamdown + `@streamdown/mermaid` | Vercel renderer purpose-built for *streaming* AI markdown; solves token-flicker | MIT | ⚠ benefit moot — our chat isn't token-streamed; means swapping the renderer |
| Graphviz (`d3-graphviz` + `@hpcc-js/wasm`) | Sturdier layout for big graphs; DOT emitted less reliably by LLMs | MIT/EPL | ⚠ more work |
| PlantUML (server) | Needs a Java server | GPL | ❌ breaks local-first |

**Generation/validation:** prompt qwen3.6 for a single fenced ` ```mermaid ` block (restricted to flowchart/sequence/ER, no `click`/HTML labels). Render with `securityLevel:'strict'` + **DOMPurify on the SVG** (2025 Mermaid XSS CVEs), `mermaid.parse()` guard, and **fallback-to-codeblock** on invalid syntax (never show a red error). Optional one-shot LLM repair loop. Plan for invalid output as the norm on a local model.

### 2. Image-search sources
| Source | Best for | License | Flag |
|---|---|---|---|
| ⭐ **Wikimedia Commons / Wikipedia (MediaWiki API)** — Commons `generator=search` + **Wikipedia PageImages** | Concrete + **best abstract handler** (PageImages = canonical human-chosen image per concept) | mixed CC/PD | ✅ widest educational coverage, no key (send UA) |
| ⭐ **Openverse API** | 800M+ CC images aggregating Commons/Flickr/museums; single endpoint | CC/PD | ✅ great aggregator/fallback |
| Smithsonian Open Access | CC0 science/history/artifacts | CC0 | ✅ later (concrete gem) |
| Met Museum API | CC0 art/artifacts, no key | CC0 | ✅ later |
| Pixabay | metaphor/illustration fallback for abstractions | Pixabay (no attrib) | ⚠ later |
| Unsplash | — | Unsplash | ⚠ ToS requires hotlink+attrib (conflicts w/ same-origin store) |
| Google CSE / SerpAPI / Bing / DDG | raw web relevance | unclear | ❌ paid / retired / ToS-fragile |

### 3. Image↔text relevance (the hard part)
| Approach | Notes | Flag |
|---|---|---|
| ⭐ **qwen3.6 VLM-judge** (yes/no + confidence, **abstain** below threshold) | "VLM judges can *rank* but not *score*" → use as rank+threshold, not absolute score; reasons about abstract relevance; can say "none fit" | ✅ pure reuse |
| ⭐ **LLM query-expansion** (abstract→concrete visual proxies *before* search) | Single biggest accuracy lever for abstractions; fixes the candidate pool at retrieval time | ✅ qwen3.6, near-free |
| SigLIP 2 (So400m, Apache-2.0) pre-filter | Cheap one-pass pre-rank to cap VLM calls if candidate sets grow | ⚠ optional later (adds a model) |
| JINA-CLIP v2 / MetaCLIP | strong but **CC-BY-NC** (non-commercial) | ⚠ license |
| Cloud embedders (Cohere Embed v4) | — | ❌ breaks local-first |

**Abstract-concept play (combine):** (1) query-expansion to concrete proxies; (2) Wikipedia PageImages as the canonical-image shortcut; (3) caption-then-match in text space (cacheable); (4) yes/no + **abstain** when nothing clears the bar.

### 4. Per-message gating + routing
| Approach | Notes | Flag |
|---|---|---|
| ⭐ **Two-stage local gate**: heuristic + qwen3-embedding pre-filter → separate **Ollama JSON-schema** call on qwen3.6 | Kills greetings/short replies for free, then a constrained `{illustrate, mode, confidence, subject}` decision; runs *after* the answer → no perceived latency | ✅ |
| Gate IN the answer turn (trailing JSON / tool-call) | zero extra call but co-emitting prose+strict-JSON is brittle, can corrupt the answer | ⚠ |
| Cloud media classifier (Perplexity) | prior-art reference only | ❌ cloud |

**Routing rubric:** `none` for greetings/meta/short-fact (bias hard toward none — false positives are the failure mode); `diagram` for processes/sequences/hierarchies/causal structure (≥3 connected concepts, ordered steps); `image` for a concrete visually-identifiable thing. Tie-break to primary intent verb; avoid `both`. Gate on `illustrate && confidence ≥ τ` (start τ≈0.6).

### 5. Async delivery + persistence
| Mechanism | Notes | Flag |
|---|---|---|
| ⭐ **surreal-commands job + TanStack polling + persistence** | Reuses podcast pattern exactly; enrichment off the sync request; worker persists on completion | ✅ |
| Second sync request | reintroduces the long-blocking-request problem the queue exists to avoid | ⚠ |
| SSE / WebSocket push | adds a 2nd async paradigm; still needs persistence; dies on reload | ⚠ / ❌ |

**Persistence is mandatory** (image must survive reload). See Risk R1 — the storage location is an open design fork because messages live only in the LangGraph checkpoint.

### 6. Image safety + fetch/cache pipeline
| Option | Notes | License | Flag |
|---|---|---|---|
| ⭐ **qwen3.6-VL zero-shot safety judge** (policy prompt, fail-closed) | No new model; broad policy (nudity + violence/gore); slower/higher VRAM per image | reuse | ✅ chosen (no new model) |
| Falconsai NSFW ViT first-gate + VLM escalation | tiny/CPU-fast; nudity-only, so still needs VLM for gore | Apache-2.0 | ⚠ deferred (was a strong rec; user chose VLM-only for v1) |
| NudeNet | AGPL + nudity-only | AGPL | ⚠ license |
| Google SafeSearch / AWS Rekognition | — | paid | ❌ cloud |

**Fetch/cache/normalize:** `httpx` streaming with a **hard byte cap** (don't trust Content-Length); `Pillow` decode with default decompression-bomb limit, **re-encode to WebP to strip EXIF**, hash-dedupe store. **SSRF is the top risk** (URLs come from search): scheme allowlist (http/https), resolve DNS and block private/loopback/link-local ranges via `ipaddress`, **pin the validated IP** and re-validate on every redirect hop (defeat DNS rebinding). Run decode in a thread/process pool.

---

## Innovative / non-obvious options
- **Wikipedia PageImages** as the abstract-concept illustrator — a human already picked the canonical image per topic. The single best lever for abstractions.
- **Museum Open-Access APIs** (Smithsonian CC0 1k req/hr, Met CC0 no-key) — authoritative captioned imagery generic stock lacks.
- **qwen3.6 as the whole AI brain** — gating, query-expansion, relevance judge, AND safety judge, all on one already-loaded local VLM. Zero new model infra.
- **Caption-then-match** — move abstract matching out of brittle cross-modal space into text space (and cache captions).

---

## Chosen stack

| Category | Choice |
|---|---|
| Diagram render | **Mermaid + react-markdown plugin**, strict security + DOMPurify + parse-or-fallback |
| Image sources (v1) | **Wikipedia/Wikimedia Commons + Openverse** (lean start; Smithsonian/Met/Pixabay later) |
| Relevance | **Hybrid: qwen3.6 query-expansion + qwen3.6 VLM yes/no+abstain judge** |
| Gating/routing | **Two-stage local**: heuristic + qwen3-embedding pre-filter → qwen3.6 Ollama JSON-schema decision (post-answer) |
| Async delivery | **surreal-commands job + TanStack polling + persistence** |
| Safety | **qwen3.6-VL zero-shot judge, fail-closed** (no new model in v1) |
| Fetch pipeline | **httpx (byte-capped) + Pillow→WebP + SSRF guards + hash-dedupe**, stored under `CHAT_MEDIA_FOLDER`, served via existing `/api/chat/media/{file}` |

**Net: zero new AI models, two external HTTP sources, one new diagram dep + DOMPurify.**

---

## Decision Register

| # | Decision | Severity | Status | Rejected alternatives (why) |
|---|---|---|---|---|
| D1 | Mermaid via react-markdown plugin | S3 (new dep, touches shared chat render) | DECIDED | Streamdown (renderer swap; anti-flicker moot on sync chat); Graphviz (weaker LLM DSL fit); PlantUML (server breaks local-first) |
| D2 | Relevance = qwen3.6 query-expansion + VLM judge/abstain | S3 (core quality risk) | DECIDED | VLM-judge-only (weaker abstract pool); +SigLIP2 now (extra model, premature) |
| D3 | Safety = qwen3.6-VL only for v1 | S3 (safety + perf) | DECIDED | Falconsai+VLM (deferred — adds model; revisit if VLM latency/contention hurts); cloud APIs (privacy) |
| D4 | Image sources v1 = Wikimedia + Openverse | S2 | DECIDED | Full cascade now (more surface up front); Unsplash (ToS); paid/DDG |
| D5 | Delivery = surreal-commands + polling + persistence | S3 (architecture) | DECIDED | 2nd sync request (blocking); SSE/WS (extra paradigm) |
| D6 | Reuse qwen3.6 for all AI steps, no new models | S4 (foundational) | DECIDED | Dedicated CLIP/reranker/NSFW models (user opted to reuse the local VLM) |

---

## Deep compatibility findings + risks / spikes

**What's confirmed reusable:**
- `MessageMedia` already renders AI `media[]` below a message; hydrate already surfaces `additional_kwargs['media']` as `MediaItem[]` (`api/routers/chat.py:298-304`).
- File store: a backend job can write into `CHAT_MEDIA_FOLDER` and mint a `/api/chat/media/{filename}` MediaItem exactly like `POST /chat/media` (`api/routers/chat.py:786-825`). GET has **no auth** today (note for prod).
- Vision path exists: `_attach_media_blocks()` already builds `image_url` data-URI blocks for vision models (`open_notebook/graphs/chat.py:70-105`) — a relevance/safety service can reuse this to send a candidate image to qwen3.6.
- Job pattern: `@command(...)` auto-registers on import; `submit_command` → poll `GET /commands/jobs/{id}` (`commands/podcast_commands.py`, `api/routers/commands.py:74-85`).
- Frontend patch: `patchSessionMessages()` mutates the TanStack cache by message `id`; optimistic-update machinery exists (`useNotebookChat.ts:209-220,260-291`).

**RISKS / spikes (carry into frame-goal / chunk-plan):**

- **R1 — Persistence design fork (HIGH, blocker).** Messages live **only in the LangGraph SQLite checkpoint**, not SurrealDB — there is no existing sidecar field. Two paths, must be settled in frame-goal:
  - (a) **Patch the checkpoint** — mutate the AIMessage's `additional_kwargs['media']` and re-save (reuses the existing hydrate read path) — but editing past checkpoint state is fragile, and it injects illustration data into conversational state the LLM re-reads.
  - (b) **New SurrealDB sidecar** keyed by message id that the hydrate path merges in — cleaner separation, but new schema + a stable message-id contract + merge logic.
  - **Spike:** prove a checkpoint round-trip update (save → fetch → patch one message's media → re-save → re-fetch persists) OR design the sidecar table.
- **R2 — Stable AI message id (HIGH).** LangGraph messages lack stable ids; `_build_chat_message` falls back to `msg_{index}` (`api/routers/chat.py:307`). The job result must correlate back to a specific message. **Spike/decide:** assign a deterministic id when the AIMessage is created (`graphs/chat.py:180`).
- **R3 — qwen3.6 vision via this path (MEDIUM).** qwen3.6 is registered as a `language` model; vision via Ollama's OpenAI-compat `image_url` blocks is expected but **untested here**. **Spike:** send `[{text},{image_url}]` to qwen3.6 on the Spark and confirm a parseable JSON verdict; confirm `OLLAMA_API_BASE`.
- **R4 — Relevance quality on abstractions (MEDIUM, product risk).** The headline open question. **Spike:** run query-expansion + Wikimedia/Openverse + VLM-judge on ~10 real study concepts (concrete + abstract) and eyeball hit rate before building the full pipeline.
- **R5 — VLM latency/GPU contention (MEDIUM).** Per-image VLM judge + safety + gating all share the single local qwen3.6 with live chat. **Spike:** measure end-to-end job latency; cap candidates judged (top-K); consider the deferred SigLIP2/Falconsai pre-filters (D2/D3) if it hurts.
- **R6 — `execute_chat` returns no job handle (LOW).** Add an optional `illustration_job_id` to `ExecuteChatResponse` (`api/routers/chat.py:166`) for the frontend to poll; submit the job after session save (~line 641), before message conversion.
- **Correction to research:** the job does image **search + judge**, NOT image **generation** (one sub-agent's example mentioned SDXL — out of scope; generation was explicitly not chosen).

---

## Handoff

Landscape is complete and the stack is chosen.

> Run `frame-goal` on `auto-illustrate-chat`. It will read `.claude/plans/auto-illustrate-chat/tech-scout.md` as the chosen tech direction and frame the goal/architecture around it — resolving the **R1 persistence fork** and **R2 message-id contract** first, since those shape the data model. Then `chunk-plan` decomposes. Consider running the **R3/R4 spikes** (qwen3.6 vision + relevance-on-abstractions) early, as they de-risk the whole feature.
