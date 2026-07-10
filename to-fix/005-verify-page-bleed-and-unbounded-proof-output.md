---
id: 005
title: Verify renders whole pages for sub-page sections, so a section's cleaned_content absorbs its neighbours' text; the proof output has no upper bound and no content contract
type: correctness (live data corruption)
severity: high
status: open — diagnosed and measured, nothing built
area: commands/verify_commands.py (`_render_section_pages`, `_VERIFY_INSTRUCTION`, `_split_cleaned_and_discrepancies`, `_output_truncation_reason`)
created: 2026-07-09
blocks: running `verify_clean_source` / `reverify_sections.py` again — verify degrades data as it runs
related: 004 (this re-opens Finding 2 — the guard was half a guard), 003 (section content bounds), migration 27 (`verify_status`, which is what made this visible)
---

## TL;DR

`verify_clean_section` renders a section's **physical PDF pages** as images and asks
the vision model to correct the parsed text against them. A page holds several
sections. The model sees the whole page and transcribes the whole page.

So a section that occupies part of a page gets its **neighbours' text appended to
its `cleaned_content`**. The agent's `get_section` tool, generated section summaries,
and the `include_content=true` sections API all prefer that layer over the raw parse,
so they read the wrong text for small sections.

The reader view, `full_text`, and vector search are **unaffected** — all three come
from `document_block`, which verify never writes. Clearing `cleaned_content` therefore
returns a section to normal-but-unproofed; nothing regresses.

Three defects, one root cause: **the proof has no output contract.**

1. **Page bleed** (this doc's headline) — no bound on what the model may *add*.
2. **No upper ratio bound** — `_output_truncation_reason` guards only shrinkage.
3. **Commentary becomes the chapter** — `_split_cleaned_and_discrepancies` only
   splits on a `DISCREPANCIES:` header; when the model omits it, its freeform
   analysis is written to `cleaned_content` as if it were the section text.

Discovered while removing the `verify_flag` insights (migration 27). The verdict
field is what made the damage countable; nothing had ever read the cleaned layer.

## Background

```
process_source → build_blocks → build_sections → verify_clean_source → summarize_source
```

`verify_clean_section` (`commands/verify_commands.py`):

- `_render_section_pages(file_path, page_start, page_end)` (line 187) rasterises
  **entire pages**, 0-based physical indices. There is no crop.
- `text_prompt` (line 538) says: *"Below are the rendered page images (pp. X-Y) of a
  document section titled "T" … Output ONLY the corrected text of the section."*
- `_VERIFY_INSTRUCTION` (line 123): *"Fix parser artifacts … Do NOT paraphrase or
  summarize. Preserve all content. Flag any unreconcilable discrepancies at the end
  under a 'DISCREPANCIES:' header."*

The instruction says "of the section" but the *evidence* handed to the model is the
page. Nothing tells the model where the section ends on that page, and nothing
checks the reply against the section's extent.

The raw parse (`section.content`) is immutable, which is the only reason all of this
is recoverable.

Test source throughout: **`source:bms5qu1xfaq9vvlpm11f`** (Hands-On Machine Learning;
472 sections, 351 with `cleaned_content`, ~1.77M chars).

---

## Finding 1 — Page bleed (correctness, **live data corruption**)

Expansion scales inversely with section size — exactly what "the model transcribes
the page, not the section" predicts:

| section size | n | mean pages | mean expansion |
|---|---|---|---|
| tiny (< 1k chars) | 27 | 1.0 | **170%** |
| small (1–3k) | 137 | 1.4 | 123% |
| large (3k+) | 187 | 3.3 | 105% |

A large section spans 3.3 pages and is most of what's on them, so it barely inflates.
A 597-char section sharing one page inflates 3×.

**Direct evidence:** of the 61 sections that share a page with a neighbour,
**22 have that neighbour's raw text inside their `cleaned_content`.**

Two read by eye:

- **`Ensemble Methods`** (597 raw → 2,006 cleaned, 336%). `cleaned_content` *opens*
  with `from sklearn.model_selection import RandomizedSearchCV` — code belonging to a
  different section on the same page. The words "Ensemble Methods" appear nowhere in
  the first 600 chars.
- **`Type Conversions`** (998 → 2,578, 258%). Opens mid-sentence: *"That the
  tf.transpose() function does not do exactly the same thing as NumPy's T
  attribute…"* — a neighbour's paragraph.

### Blast radius — narrower than it first looks. Three consumers, not everything.

```
open_notebook/ai/chat_tools.py:92          content = section.cleaned_content or section.content
open_notebook/ai/claude_agent_tools.py:231 content = section.cleaned_content or section.content
commands/summary_commands.py:318           text    = section.cleaned_content or section.content
api/routers/sources/sections.py:22         content = node["cleaned_content"] or node["content"]
```

- **The agent's `get_section` tool** reads it. Ask chat about a small section and it
  gets a neighbour's content. This is the one that matters.
- **Summaries are generated from it** (13 sections currently have both a summary and
  `cleaned_content`). Summaries reach the prompt via `get_outline`, so bleed has a
  second path into context.
- **`GET /sources/{id}/sections?include_content=true`** serves it
  (`frontend/src/lib/api/sources.ts:116`).

**NOT affected — verified, do not assume otherwise:**

- **The reader view.** `ReaderView` renders `document_block` rows via
  `use-source-blocks`. It has never read `cleaned_content`. Pages display the true
  parse.
- **`full_text`.** Regenerated from blocks: `full_text = blocks_to_markdown(finalized.blocks)`
  (`commands/block_commands.py:465`). Not derived from the cleaned layer.
- **Vector search / embeddings.** `embed_source` chunks `full_text`/blocks and contains
  **zero** references to `cleaned_content`. An earlier draft of this doc claimed bled
  text was separately embedded and duplicated in search results. That was wrong — it
  was inferred from `add_insight`'s embedding behaviour and never checked.

Consequence for remediation: clearing `cleaned_content` returns a section to
**normal-but-unproofed**, which is what the reader already shows. Nothing regresses.

### Fix options

**A. Crop the render to the section (correct, and now possible).** `document_block`
already carries normalized `bbox`, `page`, `seq`, `section_path` — 12,116 rows on the
test book. Union the section's block bboxes per page and crop the raster to that
region. PyMuPDF supports a clip rect on `get_pixmap()`. This makes the *evidence*
match the *instruction* and fixes the cause rather than detecting the symptom.

**B. Reject on expansion ratio.** Cheap, but only rejects — small sections stay on
the raw parse forever, which is most of what verify was supposed to improve. Useful
as a backstop even with (A).

**C. Skip sub-page sections entirely.** Honest, cheap, and loses the proof for 164 of
351 sections. Consider as an interim while (A) is built.

**Rejected: telling the model where the section ends in prose.** We already tell it
"the section titled T" and it ignores the boundary. The bbox exists — use it.

---

## Finding 2 — No upper bound on proof output (correctness)

`_output_truncation_reason` (line 238) rejects a proof that is **shorter** than
`_MIN_CLEANED_RATIO = 0.8` of the raw, or that hit a length stop. **There is no
symmetric check.** A reply of any length above the floor is written verbatim
(line ~674).

**38 sections exceed 150% expansion**, topping out at **537%**
(`Changes Between the First and the Second Edition`, 1,116 → 5,994).

004 measured expansions of 100/133/177% and called them "plausible (repairing broken
tables and hyphenation adds characters)… but **nobody has read them**." They were not
plausible. Reading them was the work that needed doing.

---

## Finding 3 — The model's commentary becomes the chapter (correctness)

`_split_cleaned_and_discrepancies` (line 226) splits the reply on a
`DISCREPANCIES:` header. **When the model doesn't emit that header, the entire reply
— commentary included — is returned as `cleaned`** and written to `cleaned_content`.

**32 of 351 sections carry model commentary inside `cleaned_content`.** Two
severities:

**Preamble** (majority). The chapter is intact; a junk line rides on top:

```
'Here is the corrected text:\n\n## Reverse-Mode Autodiff\n\nReverse-mode autodiff is…'
'Based on the provided images and parsed text, here is the corrected section:\n\n## Pretrained Models…'
```

**Wholesale** (at least 2 confirmed). `cleaned_content` contains no book text at all:

- `source_section:unkjgezhqw6tfehae2zq` — *"The parsed text provided is actually quite
  clean compared to the image content… Therefore, I must reconstruct the text from the
  image."* 5,994 chars of reasoning where a 1,116-char section should be.
- `source_section:za1elgb39wunr4x9tqis` (`Progressive Growing of GANs`) — opens with an
  essay about two-column layout artifacts.

Note the shrink floor **cannot** catch this: commentary is usually *longer* than the
section it replaced.

### Fix

- Strip a leading preamble deterministically (reply up to and including the first
  markdown heading, when a heading follows within N chars).
- Reject when the reply's opening doesn't look like the section (no heading, no
  overlap with the raw opening) — this is a content contract, not a length check.
- Consider a structured output (JSON with `corrected_text` / `discrepancies`) instead
  of a header convention the model is free to ignore.

---

## Finding 4 — The shrink floor rejects *good* proofs (correctness, opposite sign)

`_MIN_CLEANED_RATIO = 0.8` compares **raw character counts**. But removing parser
artifacts — dash rules, pipe wrappers, cell padding — is verify's *job*, and those
are characters.

**`Code Examples`** (`source_section:syjxpsx09tl8b1kdfy7f`): 2,405 raw chars, of which
**785 are table artifact** (a NOTE callout rendered as a markdown table with a
~392-char dash separator + 387 chars of cell padding). The model returned **1,620
chars — exactly 2,405 − 785**. It deleted the artifact and nothing else. The proof was
perfect. The floor threw it away.

Across the 30 current `rejected` sections, **7 have model output ≥ 90% of the
section's non-artifact characters** (several at 100–106%): `Code Examples`,
`The Architecture of the Visual Cortex`, `Synchronous updates`, `AdamW`, `Roadmap`,
`Implementing batch normalization with Keras`, `Using Clustering for Semi-Supervised
Learning`.

The floor is **not** merely too low — it measures the wrong quantity. It also catches
genuine loss (`Learning Curves` returned **1%** of a 7,979-char section), so it cannot
simply be removed.

### Fix

Compare **alphanumeric** characters, not raw characters — artifacts (dashes, pipes,
spaces) are not alphanumeric, so `alnum(cleaned) / alnum(raw)` measures "were words
lost?", which is the actual invariant. Verify against the corpus before picking a
threshold: 1% still rejects, 100% still passes.

---

## Recommended order

1. **Freeze verify.** Do not run `verify_clean_source` or
   `scripts/reverify_sections.py` — each run corrupts more sections (I introduced the
   537% one by re-running 8 sections today).
2. **Finding 1 (crop-to-section).** It's the cause; the rest are detectors.
3. **Findings 2 + 3 + 4** — one coherent output contract: alnum floor, upper bound,
   preamble strip, opening-content check. Ideally structured output.
4. **Remediate the existing data** (see below), then re-run verify once.

## Remediation of existing data

`cleaned_content` is derived and `content` is immutable, so all of this is reversible
by clearing the cleaned layer — the reader falls back to the raw parse.

- **Wholesale-commentary sections** → clear `cleaned_content`, set
  `verify_status='rejected'`. Immediate: they are actively wrong in chat today.
- **Preamble sections** → strip the preamble in place (deterministic, no model call).
- **Bled sections** → cannot be repaired in place; the neighbour text is
  interleaved. Clear and re-run after Finding 1 lands.
- **The 7 false rejections** → nothing to clear (no cleaned_content was written); they
  re-proof for free once Finding 4 lands.
- **The 13 summaries derived from `cleaned_content`** → clearing the cleaned layer does
  not touch them. Re-summarize those sections after verify is fixed, or they keep
  feeding bled text into `get_outline` and thus into every chat turn.
- Insights are already gone: `scripts/drop_verify_flag_insights.py` deleted all 170
  `verify_flag` rows, and verify no longer writes any.

## Landmines

- **`updated` cannot date these rows.** `source_section.updated` has
  `VALUE time::now()`, and migration 27's backfill plus `scripts/backfill_verify_status.py`
  touched every row today. Provenance is destroyed; don't try to reconstruct when a
  proof was written. (346 sections had `cleaned_content` before 2026-07-09, and only 5
  were written that day, so the contamination overwhelmingly predates the migration.)
- **`cleaned_content or content`** means an empty string and NONE behave the same, but
  a *wrong* string wins over a right one. There is no "confidence" tier.
- **Don't assume a field is read where you'd expect.** `cleaned_content` is *not* read
  by the reader, is *not* in `full_text`, and is *not* embedded — but it *is* read by
  the agent's `get_section`, by summary generation, and by the sections API. Grep
  before reasoning about blast radius; this doc's first draft got it wrong.
- **13 sections have a summary derived from `cleaned_content`.** Clearing the cleaned
  layer does not regenerate those summaries; they stay bled until re-summarized, and
  they reach the prompt through `get_outline`.
- **`_MAX_VERIFY_PAGES = 50`** guards render count, not reply size, and is unrelated to
  any of this.
- Everything in 004's Landmines still applies (`ObjectModel.get` → `NotFoundError`,
  `classify_error` defaulting to `ExternalServiceError`, `source_section.source` being a
  record link, `load_dotenv('.env')`, systemd `--user` units).

## Useful queries

```python
# expansion outliers
"SELECT title, string::len(content) AS raw, string::len(cleaned_content) AS clean
 FROM source_section WHERE cleaned_content != NONE AND cleaned_content != ''"

# verdict distribution (migration 27)
"SELECT verify_status, count() AS n FROM source_section GROUP BY verify_status"

# sections sharing a page (page-bleed candidates)
"SELECT id, title, page_start, page_end FROM source_section
 WHERE source = type::thing($sid) AND page_start != NONE ORDER BY order"
```

Commentary detector used above (matched 32 sections on the first 1,200 chars):

```python
re.compile(r"the parsed text|the provided (image|text)|rendered page image|"
           r"I must reconstruct|the image contains|compared to the image|"
           r"^\s*(Okay|Sure|Here is|Here's) ", re.I | re.M)
```

Artifact measure used in Finding 4:

```python
artifact = sum(len(m) for m in re.findall(r'-{5,}', c)) + c.count('|') \
         + sum(len(m) for m in re.findall(r'  {2,}', c))
```
