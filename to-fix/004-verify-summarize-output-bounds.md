---
id: 004
title: Verify silently truncates large sections; summaries generated ~3x longer than consumed; verify re-proofs the book 2.6x over
type: correctness + efficiency
severity: high
status: open
area: commands/verify_commands.py (fan-out + cleaned_content persist), commands/summary_commands.py (prompt + target selection)
created: 2026-07-09
blocks: restarting the verify/summarize phases on source:bms5qu1xfaq9vvlpm11f (queue deliberately paused)
related: 60363df (orphan-storm fix + phase sequencing), 003 (section content bounds)
---

> **⏸ QUEUE PAUSED.** 460 queued `verify_clean_section` jobs cancelled and 186 `summarize_section` jobs held, to stop active data loss (see Finding 2). Fully reversible via the re-trigger endpoints at the bottom. Do not restart the phase before Finding 2 is fixed.

## TL;DR

Fixing a storm of failed "Proofing pages" jobs (done, committed `60363df`) surfaced three further problems in the same pipeline, all diagnosed and measured but **not built**:

1. **Verify proofs the book 2.6× over** — sections nest, and each is proofed independently.
2. **Verify silently truncates any section too large for an 8192-token reply.** One section already lost 98% of its text. This is live data loss.
3. **Summaries are generated as prose but consumed as 300-char routing blurbs** — ~80% of generated text is discarded on read.

Findings 2 and 3 share a pathology: the model is asked for unbounded output, and a downstream consumer quietly truncates or discards what it can't use, so the waste never surfaces as an error.

## Background

The PDF ingest chain is fire-and-forget jobs on `surreal-commands`:

```
process_source → build_blocks → build_sections → verify_clean_source → summarize_source
```

`verify_clean_section` renders a section's physical PDF pages as images and asks the vision model to repair parser artifacts, writing to `source_section.cleaned_content`. The raw parse (`content`) is immutable. `summarize_section` writes `source_section.summary`.

Both run on a **single local heavy slot** — one Ollama process holding ~81 GB (confirmed via `nvidia-smi`). Two 35B models cannot co-reside, so any model switch is a full evict-and-reload. `commands/_heavy_lane.py` serializes heavy generations with a `threading.Lock`.

Model defaults (`open_notebook_default_models`):

| role | model | provider |
|---|---|---|
| vision | `qwen3.6:35b` | ollama |
| transformation | `nemotron-3-super:latest` | ollama |
| embedding | `qwen3-embedding:8b` | ollama |
| chat | `claude-haiku-4-5` | claude_agent (subprocess, not an Ollama load) |

Test source throughout: **`source:bms5qu1xfaq9vvlpm11f`** (Hands-On Machine Learning; 472 sections, ~500 physical pages, ~1.77M chars).

---

## Finding 1 — Verify re-proofs the book 2.6× over (efficiency)

`_flatten_section_ids` (`commands/verify_commands.py:216`) walks the whole tree, so **every** section gets a job. But sections nest: a parent's page range covers its children's. The model therefore re-emits the book once per level.

Verify is **output-bound**, not input-bound: the prompt says *"Do NOT paraphrase or summarize. Preserve all content."* Cost scales with characters re-emitted.

| level | chars re-emitted |
|---|---|
| 1 | 1,768,234 |
| 2 | 1,718,866 |
| 3 | 995,352 |
| 4–5 | 160,625 |
| **total** | **4,643,077** |

The book is ~1.77M chars → proofed **2.6× over**. 1,173 page-renders cover ~500 pages (~2.3× each).

### Fix: fan out over leaf sections only

Leaves partition the document — full coverage, zero overlap.

| | today (all sections) | leaves only |
|---|---|---|
| jobs | 472 | 382 |
| chars re-emitted | 4,643,077 | 1,685,837 |
| sections over the output cap | 32 | 1 |

The single remaining outlier is a 142,122-char childless chapter whose 123-page span already exceeds `_MAX_VERIFY_PAGES = 50` (`verify_commands.py:84`) and is skipped anyway.

**Rejected: bounding to level 1.** That's the *worst* option — all 19 oversized chapters, every one truncated by Finding 2.

---

## Finding 2 — Silent truncation of `cleaned_content` (correctness, **live data loss**)

The vision call passes `max_tokens=8192` (`verify_commands.py:444`) — roughly 32,000 chars of output. This is **mandatory**: the B1 pilot found this thinking-capable model silently returns empty content when `max_tokens` is unset.

**32 of 472 sections exceed that budget**, 19 of them level-1 chapters:

| level | sections | median chars | max chars | over 32k cap |
|---|---|---|---|---|
| 1 | 27 | 71,937 | 142,122 | **19** |
| 2 | 180 | 5,492 | 55,652 | **13** |
| 3 | 227 | 3,379 | 22,858 | 0 |
| 4 | 36 | 3,503 | 14,951 | 0 |
| 5 | 2 | 2,465 | 2,465 | 0 |

**Nothing checks output length against input.** `verify_commands.py:505` guards only for *empty* output. `_MAX_VERIFY_PAGES` guards render count, not reply size. The result is written straight to `cleaned_content` at `verify_commands.py:518`.

### This already destroyed data

The "Preface" section (level 1, **22,532** raw chars) was proofed down to **506 chars — 2% kept**. Note it was *under* the 32k cap, so the cap is not the only failure mode; the model can simply return a short reply.

It matters because every reader prefers the cleaned layer:

```
commands/summary_commands.py:267      text    = section.cleaned_content or section.content
open_notebook/ai/chat_tools.py:92     content = section.cleaned_content or section.content
open_notebook/ai/claude_agent_tools.py:231  content = section.cleaned_content or section.content
```

So a truncated proof silently shortens that chapter **everywhere** — chat context, summaries, agent tools. Raw `content` is immutable, which is the only reason this is recoverable.

### Fix: output-sanity guard

- If returned text is implausibly shorter than the input, treat the proof as failed: write a `verify_flag` insight instead of overwriting `cleaned_content`.
- Check the model's `finish_reason` for a length stop, if Ollama exposes it — that catches the cap case directly.
- Threshold used for the cleanup pass was `len(cleaned) < len(content) * 0.8`; treat that as a starting point, not a measured optimum.

### Already remediated

`cleaned_content` was cleared on the one truncated section (Preface). **3 sections retain cleaned content**, at 100% / 133% / 177% of raw. The expansions are plausible (repairing broken tables and hyphenation adds characters) but **nobody has read them** — worth an eyeball before trusting them.

---

## Finding 3 — Summaries are routing guidance, generated as prose (efficiency)

Both consumers truncate hard:

```
open_notebook/ai/chat_tools.py:79           get_outline(max_depth=2, summary_depth=2, summary_chars=300)
open_notebook/ai/claude_agent_tools.py:212  get_outline(max_depth=2, summary_depth=2, summary_chars=300)
```

`summary_chars` truncates with an ellipsis. **The agent never sees more than 300 chars of any summary**, then calls `get_section` to read the real text. The tool description says so: *"Use this to navigate a long document."*

But `summary_commands.py:299` prompts `"Summarize this document section concisely"` with `max_tokens=8192` (line 283) — **no length target**. Measured across the 26 summaries in the DB:

| | |
|---|---|
| median length | 998 chars |
| longest | 12,355 chars |
| exceeding the 300-char cap | **26 of 26** |
| chars generated | 39,748 |
| chars ever shown | 7,800 |

**~80% discarded**, each costing a serialized 35B generation on the single heavy slot.

### The depth bound is the wrong axis

`_summary_target_ids` (`summary_commands.py:143`) bounds by tree depth (`_MAX_SUMMARY_LEVEL = 2`, line 140). Depth is a bad proxy for size. Of the 207 qualifying sections:

| threshold | sections under it | share |
|---|---|---|
| < 1,200 chars | 19 | 9% |
| < 2,000 chars | 36 | 17% |
| < 4,000 chars | 74 | 36% |

A 1,200-char section costs ~300 tokens to just read; summarizing it to 300 chars saves almost nothing and costs a full model call. The in-code comment estimates level-2 at ~9.5K avg; the real median is **7,006** with mean **16,846** — a heavily skewed distribution the depth bound doesn't capture.

### Fix

- Prompt for a 1–2 sentence routing blurb; set `max_tokens` to ~150, not 8192.
- Skip sections below ~2,000 raw chars — the section *is* its own summary.
- Keep the depth bound as a secondary guard.

---

## Recommended order

1. **Finding 2 first** — it prevents data loss and is why the queue is paused.
2. **Finding 1** — leaf-only fan-out. Verify the leaf set still covers all pages.
3. **Finding 3** — prompt + `max_tokens` + size bound.
4. Restart the phases via the endpoints below. Watch `journalctl --user -u on-worker` for `wrote cleaned_content`, and confirm `curl -s localhost:11434/api/ps` shows **one** resident model (proves sequencing holds).

## Re-trigger endpoints

Added in `60363df`; both coalesced (409 if a run is already queued).

```
POST /api/sources/{source_id}/verify-clean    # api/routers/sources/create.py:408
POST /api/sources/{source_id}/summarize       # api/routers/sources/create.py:436
POST /api/sources/{source_id}/reparse         # pre-existing; forces build_blocks
```

## Adjacent gaps — flagged, deliberately not fixed

- **Heavy-lane has no model affinity.** `commands/_heavy_lane.py` is a bare `threading.Lock`: mutual exclusion, no ordering. Waiters poll in 0.5s slices; whoever wins gets the slot. Phase sequencing (`60363df`) removed the batch-vs-batch thrash, but an interactive chat during a batch would still swap models. Mostly theoretical today since chat is `claude_agent` (a subprocess, not an Ollama load) — it would bite if chat moved to a local model.
- **`embed_source` bypasses the lane entirely.** `commands/embedding_commands.py` has **zero** `heavy_lane` references, yet `qwen3-embedding:8b` is a heavy Ollama provider. It contends for the slot outside the mutex.
- **Two zombie `running` command rows**: `command:g7o7gea4t6bjebclg96s` (`embed_source`) and `command:nv2r8j6cshd706i9gh09` (`process_source`). Both last updated before the worker restarted, so neither is executing. Cancelling is safe but affects whether that source counts as fully ingested.
- **`args` drops undeclared keys.** Fixed for `source_id` in `60363df`, but `label` (job-tray row title) is still dropped for per-section jobs, so the tray loses click-to-origin routing and titles.
- **Chain blind spot.** If the *last* `verify_clean_section` fails terminally after exhausting retries, nothing observes it and `summarize_source` never starts. The manual endpoints exist for this, but it isn't handled automatically.

## Landmines for whoever picks this up

- **`ObjectModel.get` funnels every exception into `NotFoundError`** (`open_notebook/domain/base.py:125`). A transient DB error is indistinguishable from a deleted record at the call site. This caused two separate bugs in one session. The skip paths therefore re-ask with a plain existence query before concluding "gone."
- **`classify_error` defaults every *unclassified* exception to `ExternalServiceError`** (`open_notebook/utils/error_classifier.py:96`). The resource-busy check in `commands/_job_guards.py` is deliberately an explicit allowlist that defaults to "real error." **Do not** rewrite it on top of `classify_error` — that would reclassify genuine bugs (`AttributeError`, `KeyError`) as "waiting for a model" and requeue them 25× until the cap, burying them. Tests pin this.
- **`source_section.source` is a record link.** Compare with `type::thing($sid)`, not a string, or you get a silent zero count.
- DB scripts need `load_dotenv('.env')` or SurrealDB auth fails.
- Services are systemd `--user` units (`on-api`, `on-worker`, `on-frontend`). Don't launch them manually; `systemctl --user restart on-worker` to apply code changes.

## Useful queries

```python
# truncation audit
"SELECT title, level, string::len(content) AS raw, string::len(cleaned_content) AS clean
 FROM source_section WHERE cleaned_content != NONE AND cleaned_content != ''"

# queue state
"SELECT name, status, count() AS n FROM command
 WHERE status IN ['new','running'] GROUP BY name, status"
```
