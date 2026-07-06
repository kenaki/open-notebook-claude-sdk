# Auto-Illustrate AI Chat — Track S: Spikes (R3 vision + R4 relevance)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first. This track is
> **throwaway investigation** — it writes only scratch scripts and a findings note, no production files.
> Its purpose is the **decision gate (P-1)** that authorizes Track B's image chunks (B2, B3).
> **Location:** `.claude/plans/auto-illustrate-chat/s-spikes.md` → archived with the directory when all tracks ☑.

## SESSION HANDOFF — resume here
**Track deps:** none — run immediately, concurrently with Track A.
**Concurrent with:** Track A (A is production foundation; S is scratch — fully disjoint).
**Gates:** Track B chunks **B2 and B3** (the image pipeline). Track B's **B1 (diagram)** does NOT need S.
**State at handoff (2026-06-23):** planning complete; spikes not run.
**Paste-able resume prompt (run in a fresh chat):**
> Continue auto-illustrate-chat Track S (Spikes). Read `.claude/plans/auto-illustrate-chat/coordinator.md`
> then `.claude/plans/auto-illustrate-chat/s-spikes.md` in full. Run chunk S1 (the R3 + R4 spikes),
> record the findings + the go/no-go decision in BOTH this file and the coordinator's Decision Register
> (a new `S-gate` row) + Global status table, then STOP for me to review the gate before Track B's image
> chunks proceed. Safe to clear context after.

## This track's file ownership
Scratch only — does not touch any production file:
- `scratch/spikes/illustrate_r3_vision.py`, `scratch/spikes/illustrate_r4_relevance.py` (or a `tests/`
  scratch location — anything clearly throwaway; do NOT wire into the app).
- Findings recorded in THIS file's "S1 findings" section + the coordinator's Decision Register.
Shared files I must NOT touch: all production files (owned by other tracks).

## Per-chunk workflow
Run the spike → record observations → write the go/no-go gate decision into this file AND the coordinator
→ STOP for user review. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| S1 | R3 vision spike + R4 relevance spike → decision gate | ☐ todo | | |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk S1 — R3 vision + R4 relevance spikes → decision gate
- **Goal:** Cheaply de-risk the entire **image** half before it is built. Prove (R3) qwen3.6 accepts
  `image_url` data-URI blocks via Ollama and returns a parseable JSON verdict, and (R4) that
  query-expansion + Wikimedia/Openverse + a VLM judge produces an **acceptable hit rate** on real study
  concepts — especially abstract ones. Output a clear **go / no-go / go-with-adjustments** gate.
- **Read first:** `open_notebook/graphs/chat.py:70-105` (`_attach_media_blocks` / `_media_to_data_uri` —
  the exact `image_url` data-URI block shape qwen3.6 already receives); `graphs/chat.py:127-134`
  (`provision_langchain_model(text, model_id, "chat", …)` usage); `scripts/register_ollama_models.py`
  (the qwen3.6 model record id + that `OLLAMA_API_BASE` is configured). Coordinator → Decisions D2/D3/D4
  and Q-modelid.
- **Spec / exact values:**
  - **R3:** build a small `[{type:text},{type:image_url, image_url:{url:"data:image/...;base64,..."}}]`
    payload (reuse the `_media_to_data_uri` shape) and send it to qwen3.6 via the Esperanto/LangChain path
    (or a direct Ollama OpenAI-compat call to `OLLAMA_API_BASE`). Ask for a strict JSON verdict
    (`{"relevant": true/false, "confidence": 0-1}`) and confirm it parses. Confirm `OLLAMA_API_BASE`.
  - **R4:** pick ~10 real study concepts — mix **concrete** (e.g. "Rosetta Stone", "mitochondrion
    diagram", "Eiffel Tower") and **abstract** (e.g. "supply and demand", "cognitive dissonance",
    "recursion", "inflation"). For each: (1) qwen3.6 query-expansion → concrete visual proxy search terms;
    (2) hit **Wikipedia PageImages** + **Wikimedia Commons** `generator=search` + **Openverse** (no key;
    send a descriptive User-Agent); (3) feed the top candidate(s) to the qwen3.6 VLM yes/no+confidence
    judge with an **abstain** option. Eyeball: for how many concepts did it surface a genuinely relevant
    image vs correctly abstain vs attach something wrong (the failure mode)?
- **Reuse:** `_media_to_data_uri`; `provision_langchain_model`; `httpx` (already a dep). These are scratch
  scripts — copy shapes from the codebase, don't refactor production code.
- **Steps:**
  1. R3 script → confirm vision round-trip + parseable JSON. Record latency per call (feeds Q-R5).
  2. R4 script → run the ~10 concepts; tabulate hit / abstain / wrong-attach per concept.
  3. Decide the gate and write it down (see below).
- **Decision gate (write into BOTH this file and the coordinator Decision Register as `S-gate`):**
  - **GO** — R3 works and R4 hit rate is acceptable with few wrong-attaches → Track B builds B2/B3 as planned.
  - **GO-WITH-ADJUSTMENTS** — relevance weak on abstractions → lean harder on **Wikipedia PageImages** as
    the primary source and raise the abstain threshold; note the specific knobs for B2.
  - **NO-GO (image)** — vision path broken or hit rate poor even after adjustment → **defer the image half**
    (B2/B3 → ⊘ deferred); ship **diagram-only** (B1 + Track C still deliver value). Record why.
- **Verify:** A written findings table (concept → outcome) + a one-line gate verdict + measured per-call
  latency. No production code changed. **STOP and let the user review the gate** before B's image chunks run.

## S1 findings (fill in when run)
- R3 (vision round-trip): _pending_
- R4 (relevance table): _pending_
- Per-call latency (Q-R5 input): _pending_
- **Gate verdict (S-gate):** _pending_

## Open Questions (this track)
- **Q-R4-threshold** — the abstain confidence threshold τ (tech-scout suggests ≈0.6). *Default: start at
  0.6; tune from the R4 table and hand the chosen value to B2.*