# Auto-Illustrate AI Chat — Track B: Backend enrichment worker

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — the data contract,
> the qwen3.6 reuse conventions, and the worker/command pattern live there. Execute this track's chunks
> here, one per session.
> **Location:** `.claude/plans/auto-illustrate-chat/b-backend.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** **Track A must be ☑** (check the coordinator Global status table) for ALL B chunks — B
relies on the stable message id, the `chat_message_media` sidecar + `ChatMessageMedia` model, and the
`illustrate_message` job being submitted by `execute_chat`. **B2 and B3 additionally require Track S ☑ and
its `S-gate` = GO / GO-WITH-ADJUSTMENTS** (if `S-gate` = NO-GO, mark B2/B3 ⊘ deferred and stop after B1).
**Concurrent with:** Track C (frontend) — file-disjoint, safe to run at the same time in another chat.
**State at handoff (2026-06-23):** planning complete; no code written.
**Paste-able resume prompt (run in a fresh chat):**
> Continue auto-illustrate-chat Track B (Backend worker). Read `.claude/plans/auto-illustrate-chat/coordinator.md`
> then `.claude/plans/auto-illustrate-chat/b-backend.md` in full. Confirm Track A is ☑ in the coordinator
> (and for B2/B3, that Track S's `S-gate` is GO). Implement the next unstarted chunk (one only), verify it,
> then update BOTH this file's Status table AND the coordinator's Global status table + Changelog, and tell
> me when it's safe to clear context. After any command change, restart the worker
> (`systemctl --user restart on-worker`). If that was the last chunk of the last track, archive per the
> coordinator's Completion section.

## This track's file ownership
Files this track creates/modifies (disjoint from Track C's `frontend/**`):
- `commands/illustrate_commands.py` — NEW (`@command("illustrate_message", app="open_notebook", …)`)
- `open_notebook/graphs/illustrate.py` — NEW (gate/route/diagram/image logic; or a small
  `open_notebook/illustrate/` package if it grows)
- prompt templates for gate/expansion/judge/safety (wherever `ai_prompter` templates live, e.g. a
  `prompts/illustrate/` dir mirroring `chat/system`)
Shared files I must NOT touch: `api/routers/chat.py`, `open_notebook/graphs/chat.py`,
`open_notebook/domain/notebook.py`, the migrations — **all owned by Track A**. B only *reads* the
`ChatMessageMedia` model and *writes* sidecar rows via it.

## Per-chunk workflow
read referenced files → implement → verify (restart `on-worker`, trigger a real job, inspect the sidecar
row + `journalctl --user -u on-worker`) → mark ☑ here AND in the coordinator → announce "safe to clear
context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| B1 | Command skeleton: gate → route → **diagram** → write sidecar | ☐ todo | | needs A ☑ |
| B2 | **Image** pipeline: query-expansion → search → VLM relevance/abstain | ☐ todo | | needs A ☑ + S-gate GO |
| B3 | **Image** safety (fail-closed) + SSRF fetch → WebP → store → sidecar | ☐ todo | | needs B2 |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk B1 — Enrichment command skeleton: gate → route → diagram → sidecar
- **Goal:** Stand up the `illustrate_message` surreal-command end-to-end for the **diagram** path (no
  external fetch yet). It loads the message, runs the two-stage gate, routes, and for `diagram` mode emits
  a single strict Mermaid block from qwen3.6 and writes a `chat_message_media` row. For `none` it writes a
  `mode='none'` row (or nothing). This alone makes diagrams ship once Track C's renderer lands.
- **Read first:** `commands/podcast_commands.py:51-72` (`CommandInput`/`CommandOutput` + `@command`
  signature); `api/podcast_service.py:95-133` (`submit_command` + status shape); coordinator → data
  contract + "AI calls in the worker" + Reference index. The job is submitted by A3 with args
  `{session_id, message_id, notebook_id, model_id}`. Read the AI message's content from the LangGraph
  checkpoint the same way `execute_chat` does (`chat_graph.get_state(config={"configurable":{"thread_id":session_id}})`,
  `graphs/chat.py:188-198` for the graph handle) — find the message by `.id == message_id`.
- **Spec / exact values:**
  - `IllustrateInput(CommandInput)`: `session_id: str`, `message_id: str`, `notebook_id: str`,
    `model_id: Optional[str] = None`. `IllustrateOutput(CommandOutput)`: `success: bool`,
    `mode: str` ('image'|'diagram'|'none'), `message_id: str`, `error_message: Optional[str] = None`,
    `processing_time: float`. `@command("illustrate_message", app="open_notebook", retry={"max_attempts": 1})`.
  - **Two-stage gate** (coordinator D-gate rubric): (1) cheap heuristic — skip greetings/meta/very short
    replies (length + simple patterns); optional qwen3-embedding pre-filter. (2) a constrained qwen3.6
    Ollama **JSON-schema** decision returning `{illustrate: bool, mode: 'diagram'|'image'|'none',
    confidence: float, subject: str}`. Gate ON only if `illustrate && confidence ≥ τ` (start τ≈0.6).
    Bias hard toward `none`.
  - **Diagram mode:** prompt qwen3.6 for ONE fenced ` ```mermaid ` block restricted to
    flowchart/sequence/ER, **no `click`/HTML labels**. Extract the mermaid source (strip the fence). Do a
    minimal server-side sanity check (non-empty, starts with a known diagram keyword); the strict render +
    DOMPurify + parse-or-fallback happens client-side (Track C). Write
    `ChatMessageMedia(message_id, session_id, mode='diagram', diagram=<source>).save()` (upsert on
    `message_id`).
  - **Never raise into anything:** the worker process is isolated, but still wrap LLM calls with
    `classify_error` and on any failure write `mode='none'` (or skip) so the message stays text-only.
- **Reuse:** `provision_langchain_model`; `@command`/`CommandOutput`; `ChatMessageMedia` (A2); Ollama
  JSON-schema / structured-output via the model layer; `ai_prompter.Prompter` for the gate/diagram prompts.
- **Steps:**
  1. Create `commands/illustrate_commands.py` with the input/output models + `@command`.
  2. Implement message-load-from-checkpoint + the two-stage gate in `open_notebook/graphs/illustrate.py`.
  3. Implement diagram generation + sidecar write.
  4. Ensure the worker imports it (it auto-discovers files in `commands/` via `--import-modules commands`).
- **Verify:** `systemctl --user restart on-worker`. Send a chat message that warrants a diagram (e.g. "explain
  the TCP handshake step by step") with the notebook toggle ON. Poll `GET /commands/jobs/{id}` → terminal
  `completed`. Confirm a `chat_message_media` row with `mode='diagram'` and a plausible mermaid `diagram`.
  Send a greeting ("hi") → gate returns `none` (row `mode='none'` or absent). Check
  `journalctl --user -u on-worker` for no tracebacks.

### Chunk B2 — Image pipeline: query-expansion → search → VLM relevance/abstain
- **Goal:** For `mode='image'` messages, build the **candidate→judge** half: qwen3.6 query-expansion to
  concrete visual proxies, search Wikipedia PageImages + Wikimedia Commons + Openverse, then a qwen3.6 VLM
  yes/no+confidence judge that can **abstain**. Produces a chosen image URL (or abstains → `mode='none'`).
  **No download/safety yet** (B3). **Gated on Track S `S-gate`** — apply its adjustments (e.g. PageImages-first,
  τ value) if `GO-WITH-ADJUSTMENTS`; skip this chunk if `NO-GO`.
- **Read first:** Track S `s-spikes.md` findings + the `S-gate` verdict and `Q-R4-threshold`; coordinator
  D2/D4; the R4 scratch script (reuse its working search/expansion/judge code, promoted into production).
- **Spec / exact values:**
  - **Query-expansion:** qwen3.6 turns the gate's `subject` (abstract or concrete) into 1–3 concrete visual
    proxy search terms (the single biggest accuracy lever for abstractions).
  - **Search sources (v1, D4):** Wikipedia **PageImages** (canonical human-chosen image per concept — the
    abstract-concept shortcut), Wikimedia Commons `generator=search`, Openverse API. No API key; send a
    descriptive **User-Agent**. Cap candidates at **top-K≈3** (Q-R5 perf).
  - **Relevance judge:** for each candidate, send `[{text: subject+context},{image_url: <candidate>}]` to
    qwen3.6 (reuse the `_attach_media_blocks` block shape) for `{relevant, confidence}`. Use rank+threshold,
    not absolute score. **Abstain** (→ `mode='none'`) if nothing clears τ. Pick the highest-confidence
    relevant candidate's source URL.
  - Output of this chunk: the chosen external image URL handed to B3 (or abstain). Do NOT yet fetch/store.
- **Reuse:** R4 scratch code; `httpx`; `_media_to_data_uri`/`_attach_media_blocks` shape;
  `provision_langchain_model`; `ai_prompter` for expansion/judge prompts.
- **Steps:**
  1. Promote the R4 expansion + search + judge code into `open_notebook/graphs/illustrate.py` (functions
     `expand_query`, `search_candidates`, `judge_relevance`).
  2. Wire the `image` branch of the router (from B1) to call them, ending at "chosen URL | abstain".
  3. For now, on a chosen URL, write a temporary `mode='none'` (or log only) until B3 stores it — OR
     proceed straight into B3 in the same session if time allows (they share the command file).
- **Verify:** Send a message about a concrete thing ("tell me about the Rosetta Stone") → logs show
  expansion terms, candidates, judge verdicts, and a chosen URL (or a deliberate abstain on a vague prompt).
  Confirm top-K cap and that abstain triggers `mode='none'`. Measure latency (Q-R5).

### Chunk B3 — Image safety (fail-closed) + SSRF fetch → WebP → store → sidecar
- **Goal:** Turn a chosen external image URL into a safe, same-origin `MediaItem`: qwen3.6-VL safety judge
  (fail-closed), SSRF-guarded byte-capped fetch, Pillow→WebP re-encode (strip EXIF), hash-dedupe store
  under `CHAT_MEDIA_FOLDER`, mint `/api/chat/media/{filename}`, write the `mode='image'` sidecar row.
- **Read first:** `api/routers/chat.py:786-825` (`CHAT_MEDIA_FOLDER`, `save_uploaded_file`/`resolve_within`,
  how a `MediaItem.url = /api/chat/media/{filename}` is minted, how `GET` serves it); coordinator D3 + the
  SSRF/fetch requirements; Track S latency notes.
- **Spec / exact values:**
  - **Safety FIRST, fail-closed:** before storing, send the candidate image to qwen3.6-VL with a broad
    policy prompt (nudity + violence/gore). On unsafe **or any error/timeout/parse failure → reject**
    (fail-closed) and abstain (`mode='none'`).
  - **SSRF-guarded fetch** (URLs come from search — top risk): scheme allowlist (http/https); resolve DNS
    and block private/loopback/link-local/reserved ranges via `ipaddress`; **pin the validated IP** and
    **re-validate on every redirect hop** (defeat DNS rebinding). `httpx` streaming with a **hard byte cap**
    (do NOT trust `Content-Length`).
  - **Normalize:** `Pillow` decode (keep default decompression-bomb limit), **re-encode to WebP** (strips
    EXIF). Hash the bytes → dedupe filename. Run decode in a thread/process pool (don't block the worker loop).
  - **Store + record:** write under `CHAT_MEDIA_FOLDER`; build `MediaItem{type:'image',
    url:'/api/chat/media/<hash>.webp', label:<subject or source title>}`; write
    `ChatMessageMedia(message_id, session_id, mode='image', media=<MediaItem dict>).save()` (upsert).
  - Set `IllustrateOutput.success=True, mode='image'`.
- **Reuse:** `CHAT_MEDIA_FOLDER` + `resolve_within`; `MediaItem` (read its shape from `api/routers/chat.py`,
  but B writes a plain dict into the sidecar — A's hydrate constructs the `MediaItem`); `httpx`, `Pillow`,
  `ipaddress`, `hashlib`. Mirror the SSRF allow-private posture from `routers/credentials.py` `_validate_url`
  but **invert** it (search-sourced URLs must NOT reach private ranges).
- **Steps:**
  1. Implement the safety judge (`judge_safety`, fail-closed).
  2. Implement the SSRF-guarded fetcher (`safe_fetch_image` with pinned-IP + per-redirect re-validation +
     byte cap).
  3. Implement WebP normalize + hash store + sidecar write; wire into the `image` branch after B2's chosen URL.
- **Verify:** End-to-end: a concrete-thing prompt → job `completed`, a `.webp` file appears in
  `CHAT_MEDIA_FOLDER`, a `mode='image'` sidecar row points at `/api/chat/media/<hash>.webp`, and
  `GET /chat/sessions/{id}` (A's hydrate) shows the message `.media` populated. Force-test SSRF: feed a URL
  resolving to `127.0.0.1`/`169.254.169.254` → rejected. Feed an oversized/non-image URL → rejected by byte
  cap / Pillow. Force an unsafe image (or simulate a safety-judge error) → fail-closed abstain. Check
  `journalctl --user -u on-worker` clean.

## Open Questions (this track)
- **Q-B-msgload** — cleanest way to read one message's content by id from the checkpoint in the worker
  process. *Default: `chat_graph.get_state(thread_id=session_id)` then find `.id == message_id`; if the
  checkpoint handle isn't easily importable in the worker, pass the message content in the job args from A3
  instead (revisit A3 if so — coordinate via the coordinator).*
- **Q-B-structured** — exact Ollama JSON-schema/structured-output call for the gate. *Default: use the
  model layer's structured-output path; confirm against how other code constrains qwen3.6 output.*
- **Q-B-openverse-ua** — Openverse/Wikimedia rate limits + required User-Agent string. *Default: send a
  descriptive UA identifying the app; cache nothing beyond the stored image for v1.*
