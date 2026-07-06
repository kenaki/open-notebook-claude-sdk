# Chat Foundation — Worker & Spikes chunk specs (B7, W1–W3)

> Chunk detail for the enrichment worker (all-new files) and the throwaway spikes. Read `coordinator.md`
> first (frozen contracts, qwen3.6 reuse conventions, worker/command pattern, reference index).
> After any command change: `systemctl --user restart on-worker`.

---

## B7 — SPIKES: R3 vision + R4 relevance → S-gate (human gate)
- **Owns:** scratch scripts only (no production files). **Deps:** none. Runs in Wave 1.
- **Goal:** De-risk the headline product risk (false-positive illustrations) before committing the image
  build. Two throwaway spikes, then a **decision gate**.
  - **R3 (vision):** confirm the local **qwen3.6 VLM** can take an `image_url` data-URI block (reuse the
    `_attach_media_blocks`/`_media_to_data_uri` shape) and return a usable yes/no+confidence on whether an
    image matches a subject — and a fail-closed safety verdict (nudity/violence). Confirm `OLLAMA_API_BASE`
    is set and the model id resolves.
  - **R4 (relevance):** end-to-end scratch of query-expansion → search (Wikipedia PageImages + Wikimedia
    Commons + Openverse) → VLM relevance judge with **abstain**, on ~5 sample subjects (concrete + abstract).
    Record hit quality, a workable threshold τ (start ≈0.6), and rough latency (Q-R5).
- **S-gate verdict (needs-user):** **GO** (image pipeline viable as specced) / **GO-WITH-ADJUSTMENTS**
  (record the deltas: PageImages-first, τ value, top-K) / **NO-GO** (mark W2/W3 ⊘ deferred; diagram-only v1).
  Record the chosen τ and any adjustments here for W2/W3 to consume.
- **Verify:** the scratch scripts run and produce the verdict + numbers. No production files changed.

---

## W1 — WORKER: trigger + command skeleton → gate → route → diagram → sidecar *(revised 2026-07-02)*
- **Owns:** `commands/illustrate_commands.py` (NEW), `open_notebook/graphs/illustrate.py` (NEW),
  `prompts/illustrate/` (NEW prompt templates), **`commands/chat_commands.py` (the trigger — see below)**.
  **Deps:** B2 (ChatMessageMedia), B3 (stable AI message id), B5 (hydrate, for end-to-end verify).
- **Goal:** Stand up the `illustrate_message` surreal-command end-to-end for the **diagram** path (no
  external fetch) — INCLUDING its trigger. Load the message, two-stage gate, route; for `diagram` emit one
  strict Mermaid block from qwen3.6 and write a sidecar row. For `none`, write `mode='none'` (or nothing).
  Makes diagrams ship once F4's renderer lands.
- **Trigger (contract #6 v2 — W1 owns this; the v1 plan pointed at bg Track C2, which landed without it):**
  in `chat_completion_command` (`commands/chat_commands.py`), after the graph run + `session.save()`
  succeed and **before returning**: if `input_data.kind == "notebook"`, load the notebook, and if
  `auto_illustrate ?? true` and the invoke result contains a new AI message with a stable `.id` (B3),
  `submit_command("open_notebook", "illustrate_message", {session_id, message_id, notebook_id,
  model_id: <the resolved model_override>, label: <short subject/notebook label for the tray>})`.
  Wrap the whole trigger in try/except — a trigger failure logs and is swallowed; it must NEVER fail the
  chat job. Submitting before return means the active-jobs poller sees the illustration job in the same
  window as the completing chat job (no discovery gap).
- **Heavy lane (coordinator P-6):** every LLM/VLM call in `graphs/illustrate.py` acquires `heavy_lane`
  when `await is_heavy_model(model_id)` (import from `commands/_heavy_lane.py`) — qwen3.6 is local, so
  enrichment serializes BEHIND interactive chat turns instead of contending for the GPU.
- **Read first:** `commands/chat_commands.py` (the landed command — where the trigger slots in);
  `commands/podcast_commands.py:51-72` (`CommandInput`/`CommandOutput` + `@command`);
  `api/podcast_service.py:95-133`; coordinator frozen contracts + "AI calls in the worker". Read the AI
  message content from the checkpoint like the session read path does
  (`chat_graph.get_state(config={"configurable":{"thread_id":session_id}})`, graph handle
  `graphs/chat.py:188-198`); find the message by `.id == message_id`.
- **Spec:**
  - `IllustrateInput(CommandInput)`: `session_id: str`, `message_id: str`, `notebook_id: str`,
    `model_id: Optional[str] = None`, `label: str = ""` (tray display — mirrors
    `ChatCompletionInput.label`). `IllustrateOutput(CommandOutput)`: `success: bool`, `mode: str`,
    `message_id: str`, `error_message: Optional[str] = None`, `processing_time: float`.
    `@command("illustrate_message", app="open_notebook", retry={"max_attempts": 1})`.
  - **Two-stage gate:** (1) cheap heuristic — skip greetings/meta/very short replies (length + simple
    patterns); optional qwen3-embedding pre-filter. (2) constrained qwen3.6 JSON-schema decision →
    `{illustrate: bool, mode: 'diagram'|'image'|'none', confidence: float, subject: str}`. Gate ON only if
    `illustrate && confidence ≥ τ` (τ≈0.6, or B7's value). **Bias hard toward `none`.**
  - **Diagram mode:** prompt qwen3.6 for ONE fenced ` ```mermaid ` block (flowchart/sequence/ER only, no
    `click`/HTML labels). Strip the fence; minimal server sanity check (non-empty, known diagram keyword;
    strict render + DOMPurify + parse-or-fallback is client-side, F4). Write
    `ChatMessageMedia(message_id, session_id, mode='diagram', diagram=<source>).save()` (upsert on `message_id`).
  - **Never raise:** wrap LLM calls with `classify_error`; on any failure write `mode='none'` (or skip).
- **Verify:** restart `on-worker`. Send a diagram-worthy message ("explain the TCP handshake step by step")
  with toggle ON → the chat job completes AND an `illustrate_message` job appears in
  `GET /commands/jobs?status_filter=active` (trigger fired) → terminal `completed`; a `chat_message_media`
  row `mode='diagram'` with plausible mermaid; `GET /chat/sessions/{id}` shows the fence (B5 hydrate).
  Send "hi" → gate `none`. Toggle OFF (B6) → no illustration job submitted. Source chat turn → no
  illustration job (kind guard). A forced trigger error (e.g. bad notebook id) does NOT fail the chat job.
  `journalctl --user -u on-worker` shows no tracebacks.

## W2 — WORKER: image pipeline → expand → search → VLM relevance/abstain
- **Owns:** same files as W1. **Deps:** W1, **B7 S-gate = GO / GO-WITH-ADJUSTMENTS** (skip if NO-GO).
- **Goal:** The candidate→judge half: qwen3.6 query-expansion → search → qwen3.6 VLM yes/no+confidence
  judge that can **abstain**. Produces a chosen image URL or abstains (`mode='none'`). No download yet (W3).
- **Read first:** B7 findings + the S-gate verdict + chosen τ; coordinator D2/D4; the R4 scratch script
  (promote its working code).
- **Spec:**
  - **Query-expansion:** qwen3.6 turns the gate's `subject` into 1–3 concrete visual proxy search terms.
  - **Search (v1, D4):** Wikipedia **PageImages** (canonical per-concept image — the abstract shortcut),
    Wikimedia Commons `generator=search`, Openverse API. No API key; descriptive **User-Agent**. Cap
    candidates at **top-K≈3** (Q-R5).
  - **Relevance judge:** per candidate send `[{text: subject+context},{image_url: <candidate>}]` to qwen3.6
    (reuse `_attach_media_blocks` shape) → `{relevant, confidence}`. Rank+threshold (not absolute score).
    **Abstain** (→ `mode='none'`) if nothing clears τ; else pick the highest-confidence relevant URL.
  - Output: the chosen external URL handed to W3 (or abstain). Do NOT fetch/store yet.
- **Verify:** "tell me about the Rosetta Stone" → logs show expansion terms, candidates, judge verdicts, a
  chosen URL; a vague prompt → deliberate abstain. Confirm top-K cap. Measure latency (Q-R5).

## W3 — WORKER: image safety (fail-closed) + SSRF fetch → WebP → store → sidecar
- **Owns:** same files as W1. **Deps:** W2.
- **Goal:** Turn a chosen URL into a safe, same-origin `MediaItem`: qwen3.6-VL safety judge (fail-closed),
  SSRF-guarded byte-capped fetch, Pillow→WebP re-encode (strip EXIF), hash-dedupe store under
  `CHAT_MEDIA_FOLDER`, mint `/api/chat/media/{filename}`, write the `mode='image'` sidecar row.
- **Read first:** `api/routers/chat/media.py` (`CHAT_MEDIA_FOLDER` imported from `open_notebook.config`,
  `save_uploaded_file`/`resolve_within` from `api.upload_utils`, how a
  `MediaItem.url=/api/chat/media/{filename}` is minted/served ~:38-58); coordinator D3;
  `routers/credentials.py` `_validate_url` (mirror the SSRF posture but **invert** it — search URLs must
  NOT reach private ranges).
- **Spec:**
  - **Safety FIRST, fail-closed:** send the candidate to qwen3.6-VL with a broad policy prompt
    (nudity + violence/gore). Unsafe **or any error/timeout/parse failure → reject** and abstain
    (`mode='none'`).
  - **SSRF-guarded fetch:** scheme allowlist (http/https); resolve DNS and block private/loopback/
    link-local/reserved via `ipaddress`; **pin the validated IP** and **re-validate every redirect hop**
    (defeat DNS rebinding); `httpx` streaming with a **hard byte cap** (do NOT trust `Content-Length`).
  - **Normalize:** Pillow decode (keep default decompression-bomb limit), **re-encode to WebP** (strips
    EXIF); hash bytes → dedupe filename; run decode in a thread/process pool (don't block the worker loop).
  - **Store + record:** write under `CHAT_MEDIA_FOLDER`; build `MediaItem{type:'image',
    url:'/api/chat/media/<hash>.webp', label:<subject or source title>}` (B writes a plain dict into the
    sidecar; A's hydrate constructs the `MediaItem`); `ChatMessageMedia(message_id, session_id, mode='image',
    media=<dict>).save()` (upsert). Set `IllustrateOutput.success=True, mode='image'`.
- **Verify:** concrete-thing prompt → job `completed`, a `.webp` in `CHAT_MEDIA_FOLDER`, a `mode='image'`
  row → `GET /chat/sessions/{id}` (B5 hydrate) shows `.media` populated. SSRF: a URL resolving to
  `127.0.0.1`/`169.254.169.254` → rejected. Oversized/non-image → rejected (byte cap / Pillow). Unsafe
  image (or simulated safety-judge error) → fail-closed abstain. `journalctl --user -u on-worker` clean.

## Open Questions (worker)
- **Q-B-msgload** — cleanest way to read one message by id from the checkpoint in the worker. *Default:
  `chat_graph.get_state(thread_id=session_id)` then `.id == message_id`; the graph handle is definitely
  importable here (`chat_commands.py` already imports it). Fallback: the trigger holds the invoke result
  in-process — pass the message content in the job args from the trigger in `chat_commands.py`.*
- **Q-B-structured** — exact Ollama JSON-schema/structured-output call for the gate. *Default: model-layer
  structured-output path; confirm against existing qwen3.6 constraint usage.*
- **Q-B-openverse-ua** — Openverse/Wikimedia rate limits + required User-Agent. *Default: descriptive UA;
  cache nothing beyond the stored image for v1.*
