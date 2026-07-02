# Document Foundation — Track B: Backend pipeline (verify-clean → summaries → tiered context → agent tools)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, concurrency, file ownership — then execute this track's chunks here,
> one per session. **Track A must be fully ☑ before starting any B chunk.**
> **Location:** `.claude/plans/document-foundation/b-pipeline.md` → archived with the directory
> when all tracks ☑.

## SESSION HANDOFF — resume here

**Track deps:** **Track A must be fully ☑** (needs `source_section` table, `SourceSection` model,
`Source.get_sections/get_outline`, section-tagged chunks). Check the coordinator's Global status
table before starting a single chunk.

**Concurrent with:** **Track C** — safe to run at the same time. C touches only `api/*` +
`frontend/*`; B touches backend domain/graphs/commands/ai. No shared files between B and C.

**⚠ B1 is a HUMAN GATE.** Implement the pilot, report GO/NO-GO to the user, and **stop** — do NOT
proceed to B2 until the user confirms GO (or chooses a fallback).

**Paste-able resume prompt (run in a fresh chat):**
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/b-pipeline.md in full. Confirm Track A is fully ☑ in the
coordinator before starting. Implement the next unstarted chunk (one only — derive from the Status
table + `git log --oneline -30`). ⚠ B1 is a HUMAN GATE: after the pilot run, stop and report
GO/NO-GO; do not proceed to B2 without explicit user confirmation. Verify per the chunk spec. Commit
(one chunk = one commit). Update BOTH this file's Status table AND the coordinator's Global status
table + Changelog. Announce "✅ Chunk B.n complete — safe to clear context. Next: B.(n+1)" and stop.
```

**State at handoff (2026-06-26):** Plan authored; no chunks started. Track A not yet started.

---

## This track's file ownership

Creates/modifies (Track B only — do NOT touch `api/*` or `frontend/*`):

| File | Chunk | What changes |
|------|-------|-------------|
| `open_notebook/ai/models.py` | B1 | Add `default_vision_model` to DefaultModels; getter in ModelManager |
| `open_notebook/ai/provision.py` | B1 | Add vision provisioning helper |
| `open_notebook/graphs/chat.py` | B1 | Lift/share `_attach_media_blocks` as importable helper (if not already) |
| `commands/verify_commands.py` | B2 | New: `verify_clean_section` background command |
| `commands/summary_commands.py` | B3 | New: `summarize_section` + doc-abstract commands |
| `open_notebook/domain/notebook.py` | B3, B4 | B3: `Source.summarize_sections()`; B4: `Source.get_context("long")` rewrite |
| `open_notebook/graphs/source.py` | B2 | Add fire-and-forget verify+summary triggers after chaptering |
| `open_notebook/utils/context_builder.py` | B4 | Update to format abstract + outline instead of raw blob |
| `open_notebook/ai/claude_agent_tools.py` | B5 | Two new @tool functions + MCP server registration |

**Do NOT add migrations** — all schema shipped in A1 (migration 19).
**Do NOT touch `api/*` or `frontend/*`** — that is Track C's territory.
**notebook.py** is shared with Track A. B edits it ONLY after A☑ (A adds SourceSection model +
get_sections/get_outline; B adds get_context rewrite + summarize helpers).

---

## Per-chunk workflow

read coordinator + referenced files → implement → verify → mark ☑ here AND in coordinator → note
new Open Questions → commit → announce "✅ Chunk B.n complete — safe to clear context" → stop.

---

## Status table (this track)

| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| B1 🚧 | Vision-verifier plumbing + validation-gate pilot | ☑ | commit 87de266 (wave4 2026-07-02); plumbing + real pilot run. **Human-blessed GO-WITH-CAVEATS 2026-07-02.** Gate-bypass credential also fixed (Q-vision-gate-bypass resolved) — B2 unblocked |
| B2 | Per-chapter verify-clean background command | ◐ | commit 09c0fed (wave5b 2026-07-02); `verify_clean_section`+`verify_clean_source` in `commands/verify_commands.py`, fire-and-forget trigger in `submit_sections`, `commands/__init__.py` wired. PyMuPDF 2× render → `get_vision_model(max_tokens=8192)` (direct, not provision — see coord Decisions #14) → `cleaned_content` (raw immutable) + `verify_flag` insight. Static verify green (import+register, pytest 31). **LIVE quality spot-check parked** (real section: cleaned>raw, immutable raw, verify_flag, fan-out, failure isolation; math untested). Auto-decisions #14–16 in coordinator |
| B3 | Per-section summaries + doc abstract | ◐ | commit abb9444 (wave5c 2026-07-02); summary_commands.py (summarize_section + generate_source_abstract), Source.summarize_sections() fan-out, trigger after B2 verify. Static green (register, full suite 214). **LIVE run parked.** Auto-decisions coord #17–19 (abstract idempotency delete-then-add, get_sections readiness gate, retry windows) |
| B4 | Tiered get_context rewrite (the digestion fix) | ☐ | |
| B5 | Agent tools get_source_outline / get_section | ☐ | |

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked

---

## Changelog (this track)

- 2026-07-02 (wave5c) — **B3 ◐ (commit abb9444).** `commands/summary_commands.py`: `summarize_section`
  (`provision_langchain_model(text, None, "transformation", max_tokens=8192)` on `cleaned_content or
  content` → `section.summary`) + `generate_source_abstract` (roll-up from `get_outline()` →
  `add_insight("abstract", …)`, idempotent via delete-then-add). `Source.summarize_sections()` fans out one
  job/section then the abstract; fired fire-and-forget from `submit_sections` after B2's verify trigger.
  Registered via `commands/__init__.py`. Static verify: py_compile clean, both commands register, **full
  suite 214 pass**. **Left ◐** — live summary/abstract quality run parked. Auto-decisions #17–19 (coord):
  abstract idempotency, `get_sections()` readiness gate (avoids retry-forever on heading-only nodes),
  abstract retry window `max_attempts=8/exp-jitter/15–120s`. **B4 next.**
- 2026-07-02 (wave5b) — **B2 ◐ (commit 09c0fed).** `commands/verify_commands.py`: `verify_clean_section`
  renders a section's pages (PyMuPDF `get_pixmap` @2×, off-loop) → vision verifier (`get_vision_model(
  max_tokens=8192)` directly, avoiding provision's non-vision large-context auto-upgrade) → writes
  `section.cleaned_content` (raw `content`/`full_text` untouched); discrepancies → `source.add_insight(
  "verify_flag", …)`. `verify_clean_source` fans out one job/section with per-section isolation; fired
  fire-and-forget from the `submit_sections` node after `build_sections`. Registered via `commands/__init__.py`.
  Static verify: py_compile clean, registry shows both commands, `pytest tests/test_domain.py` 31 pass.
  **Left ◐** — the "cleaned visibly better than raw" deliverable + fan-out/failure-isolation + math path
  need a live worker + real PDF + vision model (parked). Three auto-decisions (coordinator Decisions
  #14–16): direct vision provisioning, real retry schema, `_MAX_VERIFY_PAGES=50` skip-with-flag. **B3 next.**
- 2026-07-02 (wave4) — **B1 ☑ plumbing (commit 87de266), pilot run, parked at human gate.**
  `default_vision_model` + `get_vision_model()` in `ai/models.py`; `ai/vision_utils.py:provision_vision_message()`;
  `_media_to_data_uri()` data_uri passthrough in `graphs/chat.py`. Live pilot against `qwen3.6:35b`
  transcribed 3 real pages of a Modern Greek grammar PDF — GO-WITH-CAVEATS recommendation, awaiting
  human bless. Surfaced a real `max_tokens` silent-failure bug (must carry into B2) and a credential
  config issue that bypasses the heavy-slot gate (Q-vision-gate-bypass, needs a decision before any real
  B2 job runs). `uv run pytest tests/test_models_api.py` 12 passed, no regression.

---

## Chunks (verbatim)

---

### Chunk B1 🚧 — Vision-verifier plumbing + validation-gate pilot

**Goal:** Make a vision/multimodal model invokable through the stack, and **prove** the deployed
local Qwen model can faithfully read a dense textbook page before any verify work depends on it.
This is a **HUMAN GATE** — after the pilot, stop and report GO / NO-GO. Do not proceed to B2
without explicit user confirmation.

**Read first:**
- `open_notebook/ai/models.py` — `DefaultModels` (62–95); `default_vision_model` is **commented out**; `ModelManager.get_default_model` (221–264)
- `open_notebook/ai/provision.py` (10–61) — `provision_langchain_model`
- `open_notebook/graphs/chat.py` — `_attach_media_blocks` (70–105; inlines images as data-URIs on a `HumanMessage`)
- Coordinator Decision #6, Q-qwen-vision

**Spec / exact values:**

1. **`DefaultModels` in `ai/models.py`:** uncomment / add `default_vision_model: Optional[str] = None` to the `DefaultModels` dataclass. Add a `get_vision_model()` getter to `ModelManager` that returns `self.defaults.default_vision_model` (falls back to None if not configured).

2. **Vision provisioning helper** (in `ai/provision.py` or a new `ai/vision_utils.py`):
   ```python
   async def provision_vision_message(page_images: List[bytes], text_prompt: str) -> HumanMessage:
       """Build a HumanMessage with text + page-image data-URIs."""
       # inline each image as data:image/png;base64,...
       # reuse the _attach_media_blocks pattern from graphs/chat.py:70-105
   ```
   Make `_attach_media_blocks` importable from `graphs/chat.py` (or copy the logic — keep it DRY).

3. **PILOT (the gate):**
   - Pick a real dense textbook PDF from `data/uploads/` (or ingest one now).
   - Use PyMuPDF `doc.get_pixmap(page=0)` to render page 0 as a PNG.
   - Send the image + prompt "Transcribe and verify the text on this page. List any tables or math." to the deployed Ollama Qwen.
   - Record the output quality: Can it read body text? Does it handle tables? Math? Equations?
   - If quality is adequate → **GO** → record resolution of Q-qwen-vision in coordinator.
   - If quality is inadequate → **NO-GO** → record the fallback decision (cloud vision for verify-only OR text-only dual-parse cross-check) in the coordinator's Decisions log, and note the adjusted B2 design (skip image input; use text-only diff between PyMuPDF and Docling outputs).

4. **Stop here.** Report the pilot outcome (GO/NO-GO + sample output) to the user. Do not implement B2 until the user confirms.

**Verify:**
- The `default_vision_model` field is present and readable.
- The helper builds a valid `HumanMessage` with image data-URIs (inspect the message structure).
- The pilot returns a response from Ollama (no timeout/crash).
- Record whether the output quality gates B2 proceed.

**Gate outcome (filled 2026-07-02, wave4):** `Q-qwen-vision = GO-WITH-CAVEATS` — **human-blessed 2026-07-02.**
Piloted `qwen3.6:35b` via Ollama on 3 real pages of `data/uploads/Modern Greek Grammar Notes.pdf`
(image-only cover page, dense IPA/phonetics table, dense verb-conjugation table). Body-text fidelity
excellent (including the image-only page PyMuPDF's text layer got 0 chars from); both dense tables
faithfully reconstructed as markdown tables; Greek script/diacritics handled well. Two small
transcription slips found in dense prose (a dropped letter; one letter-identity reference rendered
inconsistently across runs — non-determinism). **Math notation untested** — no sampled page contained
any; spot-check before trusting that path. **Plumbing bug found:** default (unset) `max_tokens` makes
this thinking-capable model silently return empty final content on real pages, no error — fixed by
passing `max_tokens=8192` (same value `graphs/chat.py` already uses); B2 must carry this forward
explicitly. **Infra issue found and fixed:** the DB-linked credential for this
model (`credential:sl23md12zdmi5ok3v9bc`) stored `base_url=http://localhost:11434` directly, which
bypassed the `:11435` heavy-slot admission-control gate entirely (credential config takes priority over
env vars in `ModelManager.get_model`). Full pilot transcript kept in this run's session
record; not reproduced here in full. See coordinator Decision Register (Q-qwen-vision, Q-vision-gate-bypass).

**Resolution (2026-07-02):** Human blessed **GO-WITH-CAVEATS**. `credential:sl23md12zdmi5ok3v9bc`
("Default (Migrated from env)", provider `ollama`, linked to both `qwen3-embedding:8b` and
`qwen3.6:35b`) had `base_url` updated `:11434` → `:11435` via `Credential.save()`. Verified: gate
forwards `/api/tags` and `/api/embeddings` correctly; `on-api`/`on-worker` restarted clean. **B2 is unblocked.**

---

### Chunk B2 — Per-chapter verify-clean background command

**Goal:** A background command that, for **one** section, renders its page images as ground truth,
feeds them (+ the parsed `content`) to the vision verifier, and writes a corrected `cleaned_content`
— leaving the raw parse immutable.

**⚠ Requires B1 GO (or an agreed fallback). Confirm before implementing.**

**Read first:**
- `commands/embedding_commands.py` `create_insight_command` (738–820) — command shape template
- `commands/source_commands.py` `process_source_command` (49–113) — command shape template
- `open_notebook/domain/notebook.py` — `SourceSection` (from A1) + `Source.get_sections` (from A3)
- B1's vision provisioning helper / fallback decision (from B1 gate outcome)
- `Source.page_offset` (from A1) — for physical-index slicing

**Spec / exact values (Decision #5, #6, #8):**

`commands/verify_commands.py`:
```python
class VerifyCleanSectionInput(CommandInput):
    source_section_id: str

class VerifyCleanSectionOutput(CommandOutput):
    cleaned_content: Optional[str] = None
    discrepancies: Optional[str] = None

@command("verify_clean_section", app="open_notebook",
         retry={"max_retries": 2, "delay_seconds": 10})
async def verify_clean_section(input_data: VerifyCleanSectionInput) -> VerifyCleanSectionOutput:
    section = await SourceSection.get(input_data.source_section_id)
    source = await Source.get(str(section.source))
    # 1. Render pages section.page_start .. section.page_end as PNG images (PyMuPDF get_pixmap)
    # 2. Build HumanMessage: pages + section.content + instruction to fix parser artifacts
    #    (column merges, header/footer interleaving, hyphenation, tables, math)
    #    Instruction: "Fix parser artifacts. Do NOT paraphrase. Flag unreconcilable issues."
    # 3. Call vision model (or text-only fallback per B1 gate outcome)
    # 4. Write cleaned_content to section; store discrepancies as SourceInsight type "verify_flag"
    # 5. Return output
```

**Fan-out orchestrator:** a `verify_clean_source` command that queries all sections for a source and
submits one `verify_clean_section` job per section. Trigger fire-and-forget from `graphs/source.py`
after A3's chaptering step, and expose as a re-run path.

**Key constraints:**
- Never overwrite `source_section.content` (raw parse slice) or `Source.full_text`.
- One section per invocation → context reset between sections (by design).
- Failure of one section must not poison others (catch exceptions per section).
- Bounded retries (2 as above).

**Verify:**
1. Run on one real section → `source_section.cleaned_content` is populated and visibly better than `content` (fewer column merges, cleaner tables).
2. Raw `source_section.content` and `Source.full_text` are unchanged (diff-able).
3. Discrepancies (if any) recorded as `SourceInsight` type `"verify_flag"` on the source.
4. A multi-section source fans out and each section completes independently.
5. Failure of one section (e.g. image render error) does not block others.

---

### Chunk B3 — Per-section summaries + doc abstract

**Goal:** Generate a summary for each section and one document-level abstract, stored as derived
layers, so the viewer and agent context have a compressed map.

**Read first:**
- `open_notebook/graphs/transformation.py` `run_transformation` (23–68) — reuse pattern
- `open_notebook/domain/notebook.py` `Source.add_insight` (525–570) + `SourceInsight` (323–351)
- `SourceSection.summary` field (from A1)
- Coordinator Decision #4 (derived layers), #7 (tiered context)

**Spec / exact values:**

`commands/summary_commands.py`:
```python
class SummarizeSectionInput(CommandInput):
    source_section_id: str

@command("summarize_section", app="open_notebook",
         retry={"max_retries": 2, "delay_seconds": 5})
async def summarize_section(input_data: SummarizeSectionInput) -> SummarizeSectionOutput:
    section = await SourceSection.get(input_data.source_section_id)
    text = section.cleaned_content or section.content  # prefer cleaned
    model = provision_langchain_model(text, None, "transformation")
    summary = await model.ainvoke([HumanMessage(content=f"Summarize this document section concisely:\n\n{text}")])
    section.summary = clean_thinking_content(summary.content)
    await section.save()
```

**Doc abstract:** a separate command `generate_source_abstract` that:
1. Queries all section summaries for the source via `Source.get_outline()`.
2. Builds a roll-up prompt: "Based on these chapter summaries, write a concise abstract for the document."
3. Calls the large-context model (section summaries may be long).
4. Stores as `source.add_insight("abstract", abstract_text)` — a `SourceInsight` with `insight_type="abstract"`.

**`Source.summarize_sections()` helper** on `notebook.py`: fans out one `summarize_section` job per
section via `submit_command`, then submits `generate_source_abstract`. Called fire-and-forget after
B2 (so summaries reflect cleaned text), with a manual re-run path.

**Trigger chain:** `graphs/source.py` after chaptering → verify (B2) → summarize (B3). Both are
fire-and-forget; ordering is enforced by the command retrying if sections aren't yet cleaned (or
accept running on raw content when cleaned_content is None).

**Verify:**
1. After running, each `source_section.summary` is non-null and < 500 words.
2. The source has a `SourceInsight` with `insight_type="abstract"`.
3. `Source.get_outline()` (A3) now surfaces real per-chapter summaries.
4. Re-running regenerates cleanly (idempotent — old insights are replaced, not duplicated).

---

### Chunk B4 — Tiered get_context rewrite (the digestion fix)

**Goal:** Stop dumping raw `full_text` into chat context. Default context = title + doc abstract +
chapter outline (summaries) + on-demand `vector_search` retrieval. The `/chat` endpoint contract is
unchanged — only what it feeds the model changes.

**Read first:**
- `open_notebook/domain/notebook.py` — `Notebook.get_context` (69–127), `Source.get_context` (427–440)
- `open_notebook/utils/context_builder.py` — callers at ~170 and ~280
- `grep -rn "get_context" open_notebook/` to find all callers
- `vector_search` (744–774) — still the detail retrieval mechanism

**Spec / exact values (Decisions #7, #9):**

`Source.get_context("long")` → return dict:
```python
{
    "id": self.id,
    "title": self.title,
    "insights": await self.get_insights(),  # existing
    "abstract": abstract_insight.content if abstract_insight else None,  # new
    "outline": await self.get_outline(),    # new (titles + page ranges + summaries)
}
# Do NOT include "full_text" in this return value.
```

Keep the existing `"short"` and `"medium"` context levels unchanged (they don't dump full_text either).

`Notebook.get_context` and `context_builder.py`: update the formatting of the `"long"` source block
to render:
```
## [title]
Abstract: [abstract]
Chapters: [for each section: "- Ch N: [title] (pp. X–Y) — [summary]"]
```

**Callers to update:** `grep -rn "get_context"` — update any caller that consumes `full_text` from
the returned dict to consume `abstract`/`outline` instead. Do NOT change the `/chat` endpoint
signature.

**Verify:**
1. A notebook chat over a large textbook no longer balloons the prompt with the whole `full_text`.
2. The model receives abstract + chapter outline and can still answer detail questions via retrieval.
3. `uv run pytest tests/` — green.
4. `grep -rn "get_context"` — confirm no caller breaks (no `full_text` key consumed after this change).

---

### Chunk B5 — Agent tools get_source_outline / get_section

**Goal:** Give the Claude Agent navigation tools so it pulls the document outline and drills into
specific sections by name/id — instead of receiving the entire source text.

**Read first:**
- `open_notebook/ai/claude_agent_tools.py` — full file; `@tool` pattern; `create_sdk_mcp_server`; existing `get_source` / `search` tools
- `Source.get_outline()` + `Source.get_sections()` (from A3)
- `SourceSection.get(id)` — fetch a single section

**Spec / exact values:**

Two new `@tool` functions in `claude_agent_tools.py`:

```python
@tool(
    name="get_source_outline",
    description="Get the chapter/section outline of a source document. Returns title, page ranges, and summary for each chapter. Use this to navigate a long document before drilling into a specific section.",
)
async def get_source_outline(source_id: str) -> str:
    source = await Source.get(source_id)
    outline = await source.get_outline()
    return json.dumps({"source_id": source_id, "title": source.title, "outline": outline})

@tool(
    name="get_section",
    description="Get the full content of a specific section of a document by section ID (from get_source_outline). Returns cleaned content when available, otherwise raw parsed content.",
)
async def get_section(source_id: str, section_id: str) -> str:
    section = await SourceSection.get(section_id)
    content = section.cleaned_content or section.content
    return json.dumps({
        "section_id": section_id,
        "title": section.title,
        "page_start": section.page_start,
        "page_end": section.page_end,
        "content": content,
    })
```

Add both to the `create_sdk_mcp_server` tools list.

Optionally adjust `get_source` to return the outline summary instead of full `full_text` + add a
hint: "Use get_source_outline to navigate chapters, get_section to read a specific chapter."

**Verify:**
1. An agent chat calls `get_source_outline` → returns a well-formed JSON outline.
2. Agent then calls `get_section` with a section_id from the outline → returns section content.
3. An agent chat answers a chapter-specific question by drilling in (not crashing or returning garbage).
4. No regression to existing tools (`list_sources`, `get_source`, `search`).
5. `uv run pytest tests/` — green.

---

## Open Questions (this track)

- **Q-qwen-vision** — Resolved by the B1 gate. Record GO/fallback in the coordinator.
- **Q-verify-trigger** — Auto-run verify+summarize on every PDF ingest vs. user-initiated. Default: auto fire-and-forget after chaptering (cost/speed not a constraint, Decision #2), with a manual re-run path.
- **Q-summary-model** — Which model slot for per-section summaries? Default: `provision_langchain_model(text, None, "transformation")` — same slot as existing note transformations. Upgrade to `large_context` automatically for long sections.
