# Voice Chat (Speech-to-Speech Study Conversations) — Goal Brief

> **Discovery output & the validated goal.** Written so the framing survives a context reset and so
> `chunk-plan` can consume it as its spec input. This is the "what & why", decided and grounded in the
> architecture — NOT the "how it's decomposed" (that's the plan).
> **Location:** `.claude/plans/voice-chat/brief.md` → archived to `.claude/plans/archived/voice-chat/` when done.
> **Slug:** `voice-chat` (plan will live at `.claude/plans/voice-chat/plan.md`).

---

## Problem / real need

Today the only way to interact with the AI while studying in Open Notebook is **typing in chat and
reading replies**. The user wants a **spoken interface** — talk to the AI, hear it answer — as a
distinct way of working through material, so studying feels like a back-and-forth dialogue rather than
reading and typing. The real need is a **lower-friction, more natural study loop** ("just conversing
with the AI"), not a literal feature called TTS/STT. Voice is the means; conversational studying is the
end.

Who it's for: the user (self-hosted, privacy-conscious, runs local AI on a DGX Spark). Primary use is
solo study sessions against their own notebook sources.

What breaks without it: studying stays a keyboard-and-screen activity — can't study while pacing,
away from the keyboard, or in a hands-free flow; the "talk it through out loud" learning mode is
unavailable.

## Success criteria

- From a notebook chat, the user can enter a **voice mode** and have a spoken conversation grounded in
  their notebook sources: speak a question → hear the AI's spoken answer → continue.
- **Two interaction modes both work:**
  - **Push-to-talk** — explicit start/stop of recording; reliable, the baseline.
  - **Hands-free continuous** — listens, auto-detects end of speech, sends, plays the reply, and
    resumes listening, with no button presses between turns.
- Speech processing runs through the **local/server Esperanto pipeline** (STT → existing chat brain →
  TTS); no dependency on a cloud realtime voice API, and it works with local models on the Spark.
- The spoken answers are the **same source-grounded answers** the text chat produces (same model
  routing, same notebook context) — voice is an I/O layer, not a separate brain.
- A transcript of the spoken exchange remains visible/readable in the chat (voice augments, doesn't
  replace, the text record).
- Reasonable per-turn latency for study use (target: a few seconds, not tens of seconds), and graceful
  failure (STT/TTS errors surface clearly and fall back to text).

## Constraints & non-goals

- **Constraints:**
  - **Must reuse** the existing Esperanto model layer (`text_to_speech` + `speech_to_text` model types,
    `ModelManager`), credential system, and the audio file serving pattern — do not introduce a parallel
    audio stack.
  - **Local-first / privacy-first:** must be runnable entirely with local providers (e.g. local
    Whisper-style STT + local TTS via Ollama / configured providers) so no audio need leave the Spark.
    Cloud providers remain an option via the existing credential system but must not be required.
  - **Built on the current synchronous request/response chat** (LangGraph + SQLite checkpoint). v1 does
    not require a streaming refactor.
  - **i18n:** any new UI strings must add translation keys across all locales (project rule).
  - Must coexist with the in-progress **multi-chat workspace** (ChatDock / columns store) rather than
    fight it.
- **Non-goals (v1):**
  - **True barge-in** (interrupting the AI mid-utterance) — deferred; it needs streaming TTS + cancel.
  - **Cloud realtime voice APIs** (OpenAI Realtime / Gemini Live) — explicitly not the v1 path.
  - **Dedicated study modes** (Socratic tutor, quiz-me, flashcard drills, recap) — deferred to a later
    phase; v1 is mode-agnostic voice I/O over normal chat.
  - **Streaming token-by-token TTS** — deferred (tied to barge-in).
  - **Voice input as a source-ingestion path** (transcribing uploaded audio into sources) — separate
    concern, not part of this feature.

## Assumptions (surfaced)

- **[unconfirmed]** A local TTS provider with acceptable voice quality + latency is available/configurable
  on the Spark via Esperanto (TTS quality varies a lot by provider). STT (local Whisper) is lower risk.
- **[unconfirmed]** Browser-side audio capture + voice-activity detection is acceptable to the user
  (mic permission prompt, runs in-browser). This is the planned mechanism for hands-free turn-taking.
- **[confirmed]** Existing chat is synchronous (no streaming) — see findings.
- **[confirmed]** Esperanto exposes both STT and TTS and supports local (Ollama) among other providers.
- **[assumed]** "Both interaction modes" means both should exist in v1, with push-to-talk as the
  reliable baseline and hands-free continuous via VAD auto-turn-taking (not true realtime barge-in).

## Architectural findings (the decision-axis depth)

- **Already exists (TTS, fully built):** Esperanto `TextToSpeechModel`, a `text_to_speech` model type
  in the registry, `ModelManager.get_text_to_speech()`, credential-based provider/key resolution, and
  an audio-file-serving pattern. Used today for podcast generation.
  - `open_notebook/ai/models.py` (ModelManager, model types), `commands/podcast_commands.py` (TTS
    synthesis via `podcast-creator`), `api/routers/podcasts.py` (FileResponse audio serving).
  - A media serve/upload endpoint already exists on chat: `POST /chat/media`, `GET /chat/media/{filename}`
    (`api/routers/chat.py`) — reusable for chat audio.
- **Already exists (STT, half-built — plumbing only):** `speech_to_text` model type,
  `ModelManager.get_speech_to_text()`, default model field `DefaultModels.default_speech_to_text_model`,
  and a dormant content-core transcription hookup in `open_notebook/graphs/source.py`. The registry +
  factory exist; nothing currently drives live transcription.
- **Esperanto = unified 4 model types** (`LanguageModel`, `EmbeddingModel`, `SpeechToTextModel`,
  `TextToSpeechModel`), each created via `AIFactory.create_*()`, with credential→config resolution and
  env-var fallback (`open_notebook/ai/models.py`, `open_notebook/ai/key_provider.py`). **STT and TTS
  both support local (Ollama) providers** — so a fully local pipeline is feasible.
- **Load-bearing constraint — chat is synchronous request/response, NOT streaming.** A message goes
  `POST /chat/execute` → LangGraph `chat.py` graph runs to completion → full response returned. The
  Claude Agent SDK path (`open_notebook/ai/claude_agent.py`) also completes before returning.
  - `api/routers/chat.py` (execute endpoint), `open_notebook/graphs/chat.py` (single-node graph, model
    routing in `_generate_ai_message()`).
  - **Implication:** TTS can only start after the full reply exists → true barge-in / speak-as-it-thinks
    is out of reach without a streaming refactor. Turn-based and VAD-driven hands-free ARE reachable now.
- **Where chat state lives:** message history is persisted in a **LangGraph SQLite checkpoint** keyed by
  `thread_id == session_id`, NOT in SurrealDB. The `ChatSession` domain record
  (`open_notebook/domain/notebook.py`) holds only metadata (title, `model_override`,
  `parent_session_id`, `quote`). **There is no `mode` concept on a session today** — adding voice as a
  mode is an additive metadata change, not a data-model upheaval.
- **Frontend chat surface:** `useNotebookChat.ts` owns session + message state and `sendMessage()`
  (with optimistic updates). UI lives in `ChatPanel.tsx` (standalone) and the newer `ChatDock.tsx` /
  `PanelCard.tsx` (multi-chat dock) with `notebook-columns-store` / chat-workspace store. The composer
  is a plain textarea — a **mic button / voice-mode toggle attaches here**, and STT output flows through
  the existing `sendMessage()` path unchanged.
- **Feasibility:** High. STT-in feeds the existing message path; TTS-out consumes the existing response
  and serves audio via the existing media endpoint. The feature is **additive** (no rewrite). The only
  capability genuinely missing for v1 is **browser audio capture + VAD** and the **glue** that wires
  STT→chat→TTS into a turn loop.

## Solution direction

- **Chosen — Local Esperanto speech-to-speech pipeline layered on the existing chat, with two
  interaction modes:**
  1. **STT in (server-side, local-capable):** browser captures mic audio → sent to a new chat audio
     endpoint → `ModelManager.get_speech_to_text()` transcribes (local Whisper-capable) → transcript
     enters the **existing `sendMessage` / `/chat/execute` path** unchanged, so answers stay
     source-grounded with current model routing.
  2. **TTS out (server-side, local-capable):** the completed chat reply is synthesized via
     `ModelManager.get_text_to_speech()` and served through the existing chat media endpoint; the
     frontend plays it and keeps the text transcript visible.
  3. **Push-to-talk mode:** explicit record start/stop; the reliable baseline.
  4. **Hands-free continuous mode:** **browser voice-activity detection** drives auto-turn-taking
     (listen → detect end-of-speech → auto-send → play reply → resume listening). Gives a genuine
     hands-free conversational feel **without** needing streaming/realtime.
  - Voice is modeled as an **I/O layer over normal chat** (mode-agnostic), keeping the door open to
    study modes later as prompt/behavior presets.
  - Rationale, grounded in findings: reuses fully/partly-built TTS+STT registry, credential system, and
    media serving; honors privacy-first + local-on-Spark; avoids a streaming refactor; survives
    alongside the multi-chat workspace.

- **Rejected alternatives:**
  - **Cloud realtime voice API (OpenAI Realtime / Gemini Live):** lowest latency + native barge-in, but
    cloud-only (breaks local/privacy-first), costs money, and introduces a **separate voice brain**
    detached from the source-grounded notebook chat — undercutting the core "study against my sources"
    value. User chose the local pipeline.
  - **Browser-native Web Speech API (client STT+TTS):** zero backend, but Chrome-dependent, robotic
    voices, and routes audio to Google — violates privacy-first. Useful only as a throwaway prototype.
  - **True streaming / barge-in in v1:** ruled out by the load-bearing constraint (synchronous chat +
    SQLite checkpoint). Deferred to a later phase as an explicit stretch goal.

## Open Questions (surface to human; don't guess)

- **Q-tts-local** — Which concrete **local TTS provider/voice** do we target on the Spark, and is its
  quality/latency acceptable? (Default: pick a local Esperanto-supported TTS; fall back to a configured
  cloud TTS via credentials if local quality is poor. Needs a quick spike.)
- **Q-stt-model** — Which **STT model** (e.g. local Whisper variant) and is `default_speech_to_text_model`
  expected to be set, or chosen per session? (Default: use `default_speech_to_text_model`, local Whisper.)
- **Q-vad** — Acceptable to do **voice-activity detection in the browser** (in-browser library) for
  hands-free, vs server-side? (Default: browser-side VAD for v1 — keeps the loop responsive and audio
  local until a turn is finalized.)
- **Q-session-mode** — Should voice be a **per-session mode** (a `mode`/flag on `ChatSession`) or a
  transient **UI toggle** on any existing chat? (Default: UI toggle on existing chat for v1; persist a
  session mode flag only if it proves needed.)
- **Q-both-in-v1** — Confirm "both interaction modes" means **both ship in v1** (assumed yes), vs
  push-to-talk first and hands-free as a fast-follow.

## Handoff → chunk-plan

Goal is framed. Next: run `chunk-plan` on `voice-chat`. It will detect this brief as the spec input, do
the implementation-depth codebase analysis (exact files, signatures, reuse handles, file ownership), and
decompose into (parallelized) chunks in this same `.claude/plans/voice-chat/` directory.
