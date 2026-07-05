---
id: 003
title: Chaptering mis-bounds section content — a "section" can hold ~the whole book
type: correctness
severity: high
status: open
area: commands/section_commands.py (_sections_from_toc content slicing)
created: 2026-07-05
blocks: document-foundation B2/B3 archival; makes summarize_section overflow the LLM context
---

# 003 · `build_sections` produces sections whose `content` is ~the entire book

> Surfaced 2026-07-05 during the b2/b3 full-book re-run (the fix in `7c51ea5` for the fan-out race is
> correct and works — summaries ARE written for normal-sized sections — but the re-run exposed that the
> **section `content` field itself is mis-bounded**). The user caught it: `summarize_section` reported a
> 376,267-token prompt, which is impossible for one section of a book whose *entire* text is ~459K tokens.

## The observation (hard numbers, `source:jnunvbxml03utb8x6kww`, Hands-On ML, 472 sections)
- **Actual book `full_text`: 1,835,231 chars (~459K tokens).**
- **Sum of all 472 section `content` fields: 21,099,444 chars (~5.27M tokens) — 11.5× the whole book.**
- Largest "section": **"Preface" (level 1, page_start=4, page_end=4) = 1,690,662 chars (~423K tokens)** —
  i.e. 92% of the entire book lives under a preface that spans a single page.
- **17 sections exceed ~90K tokens** → each overflows the 100K-context summarizer (`summarize_section`
  failed 3×/each with `context_length_exceeded`, prompt 376,267 tokens).
- The page ranges are CORRECT and small (Preface 4–4; many "Exercises" on single pages) while `content`
  is enormous — proof that `content` is decoupled from `page_start/page_end` and mis-sliced.

## Root cause — `_sections_from_toc` content slicing (section_commands.py:79–142)
Section `content` is a **markdown slice** `full_text[char_start:char_end]`, bounded by *title-matching*,
which breaks on any real book:

1. **First-occurrence-wins title→char map (`:94–98`).** `title_to_char` records only the FIRST position of
   each heading text. Repeated headings collapse to one early position. In this book: **"Exercises" appears
   19×**, "Get the Data" 2×, plus admonition noise ("tip" 69×, "note" 62×, "warning" 48×) that the
   `^#{1,6}\s+` regex wrongly treats as headings. So all 19 "Exercises" TOC entries resolve to the char
   position of the *first* "Exercises" → each slices a giant near-identical region (that's the ~11 "Exercises"
   sections of 0.7–1.5M chars each in the size ranking).
2. **`char_end` defaults to `len(full_text)` (`:116`)** and is only narrowed when a *later TOC entry at the
   same-or-higher level* has a title that ALSO matches a markdown heading (`:117–123`). Docling markdown
   heading text frequently does not match the PDF-TOC titles, so the boundary lookup fails and the slice
   runs from the heading **to the end of the document** (the Preface→whole-book case).

Net: `content` is grossly over-bounded, overlapping, and duplicated ~11.5×.

## Blast radius
- **B3 summarize / abstract (BROKEN):** 17 sections overflow → fail; the event-driven abstract trigger
  (`summarize_section` → `_remaining_unsummarized == 0`) can NEVER reach 0 while any text-bearing section
  fails → **the document abstract wedges** (same *symptom* as the original b3 bug, new *cause*). Even the
  non-overflowing sections summarize duplicated/overlapping text → redundant, low-quality summaries.
- **B2 verify-clean (mostly OK):** renders PDF *pages* (`page_start..page_end`, which are correct), so the
  vision step is fine; but it diffs the render against `content`, so discrepancy detection is noisy.
- **Section viewer / TOC (C3) (user-visible):** renders `cleaned_content` or `content` → shows the whole
  book under "Preface".
- **Embeddings / search / citations (FINE):** `source_embedding` chunks come from `full_text`
  (`embed_source_command`), NOT from section `content` — unaffected. Phase3 page provenance unaffected.

## The fix (proposal — needs a decision)
Bound section content by the **page ranges**, which are already correct, instead of fragile title-matching.
Options:
- **A (recommended): page-range slice.** Content for a section = the markdown/text corresponding to
  `page_start..page_end`. The code already has this as the *fallback* branch (`:127–130`, PyMuPDF page
  text); make it the primary path, or map page boundaries → markdown char offsets via the Docling page_map
  (Phase3 already persists `source.page_map`) and slice the markdown by those offsets. Parents that should
  aggregate children can concat child slices explicitly rather than by heading-run.
- **B: positional heading matching.** Walk headings in document order; assign each TOC entry the NEXT
  heading occurrence after the previous entry's; end at the next entry's start. Fixes the repeated-title
  collision and the EOF fallback, but still trusts title-matching.
- Also: filter admonition pseudo-headings ("tip"/"note"/"warning") out of the heading regex, and guard
  `summarize_section` with a context-budget cap (truncate or map-reduce) as defense-in-depth for any
  genuinely huge section.

After the fix: re-chapter this source (`build_sections`), confirm no section `content` exceeds the
summarizer context and the `content` total ≈ the book size (not 11×), then re-run verify-clean + summarize
+ abstract. This is what unblocks document-foundation archival (together with the visual smokes).

## Operational note (2026-07-05)
The b2/b3 re-run was submitted then **halted** (worker stopped) once this was found, to avoid burning hours
of GPU on mis-bounded sections. ~940 per-section jobs (472 verify + 472 summarize) remain queued and MUST
be cleared before the worker is restarted, else they resume on the broken data. During/after the burst,
SurrealDB began **rejecting new WS signins** ("problem with authentication") while the app's existing pooled
connection kept serving — likely rocksdb write-contention from the burst (or a session leak from the killed
in-flight jobs) surfacing as a misleading auth error. Clearing the queued jobs needs either the DB to
recover fresh-signin, or a controlled SurrealDB/worker restart.
