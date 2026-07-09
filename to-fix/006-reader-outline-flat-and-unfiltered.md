---
id: 006
title: The reader outline is built from raw heading blocks, not the TOC — so it carries TIP/NOTE/WARNING callouts and has no hierarchy at all
type: correctness (UX / wrong data surfaced)
severity: medium
status: FIXED 2026-07-09 — option A + TOC⋈blocks alignment; no reparse needed. See "Resolution".
area: open_notebook/parsers/outline.py (new), open_notebook/parsers/base.py (`finalize` → `section_index`), commands/block_commands.py (step 3a), frontend/src/components/source/reader/ReaderOutline.tsx
created: 2026-07-09
blocks: nothing — this is a read-path defect; no data is corrupted and nothing downstream consumes `section_index`
related: 003 (added the admonition filter — but to the *other* outline path, which the reader never reads)
fix-available: shipped — see "Resolution" at the bottom. Option B (the docling flag) was NOT taken.
---

> **Resolution (2026-07-09).** Fixed by option A plus a variant of option C that
> needs **no reparse and no schema change** — see the "Resolution" section at the
> end. One claim in the analysis below turned out to be **wrong** and is corrected
> there: absence from the TOC does *not* distinguish junk from real headings.

## TL;DR

There are **two independent outlines** in this codebase, derived from two different
inputs, and the reader uses the worse one.

- **`section_index`** (parse header) — every block Docling classified as a heading.
  No filter. This is what `ReaderOutline` renders.
- **`source_section`** (DB table) — built from the PDF's own embedded TOC bookmarks.
  Correctly hierarchical, no callouts. Nothing in the reader touches it.

Consequences on the Hands-on ML book (`source:bms5qu1xfaq9vvlpm11f`):

1. **Callouts are outline entries.** 179 of 882 entries (**20.3%**) are `TIP` (69),
   `NOTE` (62), or `WARNING` (48). Plus 20 `OceanofPDF.com` watermark lines and 23
   sentence fragments Docling misread as headings (`Let's walk through this code:`,
   `In this equation:`). **222 junk entries — a quarter of the outline.**
2. **The outline is completely flat.** *Every* entry is `level: 1`, on both test
   books. The indentation in `ReaderOutline.tsx:51` (`entry.level - 1`) therefore
   always evaluates to zero. Meanwhile `source_section` for the same book has a
   real 5-deep tree: `{1: 27, 2: 180, 3: 227, 4: 36, 5: 2}`.

to-fix/003 already fixed (1) — but it added `_ADMONITION_MARKERS` to
`commands/section_commands.py`, which is the path the reader does **not** read. The
fix is real and still correct; it just landed one pipeline stage too late to ever
reach the reader.

Defect 2 is **not our bug**: docling's PDF pipeline never assigns a heading level, and
ships an off-by-default flag to infer one. Turning it on is one line, and its
prerequisite is already satisfied. See Defect 2 and Option B.

## Why 003's fix could never have reached it

`section_index` is created **before** `source_section` exists. From `build_blocks`
(`commands/block_commands.py`):

```
1. parser runs        → finalize() builds section_index   (parsers/base.py:200)
2. header written     → status='ready'                    (block_commands.py:445)
3. markdown regen     → source.full_text                  (block_commands.py:465-471)
4. submit_command_once("build_sections", ...)             (block_commands.py:479-483)
                            ↓ async, separate job
                        source_section rows created       (commands/section_commands.py)
```

`source_section` is *downstream* of `section_index`. And the dependency never runs
the other way either — `section_commands.py` contains **zero** references to
`source_parse`, `document_block`, or `get_parse_header`. It reads the PDF's TOC
bookmarks via PyMuPDF plus the regenerated `full_text`, and nothing else.

So the two are independent derivations of "what are the headings in this document":

| | `section_index` | `source_section` |
|---|---|---|
| Source of truth | Docling's layout classification | the PDF's embedded TOC bookmarks |
| Built by | `parsers/base.py::finalize` | `commands/section_commands.py::build_sections` |
| Admonition filter | **none** | `_ADMONITION_MARKERS` (003) |
| Hierarchy | all `level: 1` | real, levels 1–5 |
| Read by | `ReaderOutline` | agent `get_section`, summaries, verify |

## Defect 1 — no filter on the heading set

`open_notebook/parsers/base.py:200-209`:

```python
section_index = [
    {
        "seq": b.seq,
        "level": b.level if b.level is not None else 1,
        "title": b.text or "",
        "subtree_end": b.subtree_end,
    }
    for b in blocks
    if b.type == BlockType.heading      # <-- the only predicate
]
```

Docling emits O'Reilly's callout boxes as `SectionHeaderItem`, so `TIP` / `NOTE` /
`WARNING` become `BlockType.heading` and land in the outline verbatim. Same for the
`OceanofPDF.com` watermark, which is visually a standalone bold line.

Note this is **book-dependent**: the AI Engineering book
(`source:oo9y87r4n39qlt4cfa9o`) has 0 admonition entries in its 373. The callout
pollution tracks how a given publisher styles its callouts.

## Defect 2 — heading level is always 1 (and it's a docling flag, not our bug)

Measured: the level histogram for `section_index` is `{1: 882}` and `{1: 373}` on the
two ready parses. **No entry at any other level, on either book.** Unlike Defect 1,
this is not book-dependent — it's universal.

**Our parser is not at fault.** `open_notebook/parsers/docling_parser.py:377-381`
reads the level correctly:

```python
elif isinstance(item, SectionHeaderItem):
    lvl = getattr(item, "level", None)
    level = int(lvl) if isinstance(lvl, int) and lvl >= 1 else 1
```

and `SectionHeaderItem.level` is a real, always-present field
(`annotation=int, required=False, default=1, Ge(1), Le(100)` in docling-core 2.85.0).
The `else 1` fallback never fires. The field simply always *holds* 1.

The reason is upstream: **docling's PDF pipeline never assigns a level.** In
`docling/utils/glm_utils.py:306` and `:357` the PDF path calls

```python
doc.add_heading(text=text, prov=prov)      # no level= argument → takes the default of 1
```

Every `level=` call site in docling 2.107.0 is a *markup* backend (`md_backend`,
`msword_backend`, `opendocument_backend`, `asciidoc_backend`, `jats_backend`) —
formats that carry explicit heading levels. The layout-model path has none to carry.

Docling states this outright in `docling/datamodel/pipeline_options.py:1550`:

> *"The layout model only flags regions as `SECTION_HEADER` without a level, so every
> heading produced by the PDF path defaults to `level=1` and the document hierarchy is
> flattened."*

### There is an off-by-default flag that fixes it

The same docstring describes `HeadingHierarchyOptions`:

> *"When `enabled`, `HeadingHierarchyModel` runs right after the reading-order model and
> assigns `SectionHeaderItem.level` from (in precedence order) numbering and font style.
> The step only changes heading levels; it never adds, removes or reorders items."*
>
> *"`use_style` requires the parsed PDF cells to still be available … i.e.
> `PdfPipelineOptions.generate_parsed_pages=True`."*

It defaults to `enabled=False` ("all detected headings remain at level 1 — unchanged
behavior") and is wired into the **non-legacy** pipeline we use —
`docling/pipeline/standard_pdf_pipeline.py:617` and `:1003`.

And `docling_parser.py:218` **already sets `opts.generate_parsed_pages = True`** (for
code-block cell retention), which is precisely the prerequisite for `use_style`.

So enabling it is a one-line change. See Option B.

### Remaining hardcode in our parser

Separately, `docling_parser.py:408-410` hardcodes `level = 1` for a plain `TextItem`
carrying a `SECTION_HEADER` / `TITLE` label, ignoring `item.level`. That branch would
need to read the level too, or it will discard whatever `HeadingHierarchyModel`
assigns to items that arrive on the `TextItem` path. (`TitleItem` → `level = 1` at
line 385 is fine — a title *is* level 1.)

### Knock-on: `subtree_end` is degenerate

`parsers/base.py:162-178` computes `subtree_end` with a heading-level stack — "a
heading at level L closes every open heading with level >= L". With every level
equal to 1, each heading closes the previous one, so every heading's subtree ends
exactly where the next heading begins.

Verified against the stored data: of 881 adjacent pairs on the big book, **0** have
a `subtree_end` that reaches past the next heading's `seq`. `subtree_end` is
non-null on all 882 entries and carries no nesting information whatsoever. Anything
that later tries to use it to collapse or scope a subtree will silently get a
single-heading span.

## Blast radius

Narrow, and read-only. `section_index` has exactly one consumer chain:

```
GET /sources/{id}/parse   (api/routers/sources/blocks.py:104)
  → ParseStatusResponse.section_index
    → ReaderView.tsx:146-148  (sectionIndex memo)
      → ReaderOutline.tsx     (the dropdown)
```

Nothing else reads it. No LLM prompt, no summary, no embedding, no search. **No
stored data is wrong** — `document_block`, `full_text`, `source_section` and the
vector index are all unaffected. The defect is confined to what the outline dropdown
displays. That is why this is `medium`, not `high`.

## Not a defect: "Code Examples"

Worth stating explicitly because it looks like junk and isn't. `Code Examples` is a
legitimate O'Reilly front-matter heading (p6), and it appears in the PDF's real TOC
bookmarks — it is present in `source_section` too, at level 2 under `Preface`,
alongside `Conventions Used in This Book`, `O'Reilly Online Learning` and
`How to Contact Us`. Any filter must not key on the word "code".

The distinguishing property of the junk is that it is **absent from the PDF's TOC**,
not that its title looks unusual.

## Proposed direction

Three options, cheapest first.

### A. Filter `section_index` (cheap, partial)

Apply the existing `_ADMONITION_MARKERS` set (and a watermark/fragment heuristic) in
`parsers/base.py::finalize`. Removes 222 of 882 entries.

Leaves the outline **flat**. You get a clean 660-entry unindented list instead of a
dirty 882-entry unindented list. Does not fix Defect 2. Cheap enough to be worth
doing regardless, but it is not the fix.

### B. Turn on docling's heading-hierarchy model (cheap, fixes Defect 2)

In `docling_parser.py`'s converter setup (line 211-218), next to the existing
`opts.generate_parsed_pages = True`:

```python
opts.heading_hierarchy_options.enabled = True
```

`HeadingHierarchyModel` then assigns `SectionHeaderItem.level` from numbering and
font style. Its `use_style` prerequisite (`generate_parsed_pages=True`) is already
satisfied. Also fix the `TextItem` branch at `docling_parser.py:408-410` to read
`item.level` instead of hardcoding 1, or headings arriving on that path will discard
the inferred level.

This fixes Defect 2 *and* `subtree_end` at once, since `parsers/base.py` derives
`subtree_end` from the level stack.

Caveats:

- **Requires a reparse** of every existing source. Levels live in stored blocks;
  the flag only affects new parses.
- **Costs pipeline time** — one more stage per page, and `use_style` reads parsed
  cells. Unmeasured. Worth timing on the 1,122-page book before committing.
- **Inference, not ground truth.** Numbering + font style is a heuristic. The
  authoritative signal is the PDF's bookmark outline, and docling explicitly says
  *"PDF bookmark/outline inference (the most authoritative signal) is planned as a
  separate follow-up"* — i.e. **not implemented**. Note that the bookmark outline is
  exactly what `source_section` already reads, via PyMuPDF. Docling is, in effect,
  planning to reimplement what Option C would give us today.
- Does **not** touch Defect 1. Callouts are `SECTION_HEADER` regions to the layout
  model no matter what level they get assigned.

### C. Serve the outline from `source_section` (correct, most work)

Have the reader read the TOC-derived tree, which is already filtered and already
hierarchical. Fixes both defects by construction and deletes the duplicate
derivation.

**Cost — the `seq` problem.** `ReaderOutline.onJump(seq)` needs a block `seq` to
scroll to. `source_section` has no `seq` column; it carries only `page_start` /
`page_end` (see `SourceSection`, `open_notebook/domain/notebook.py:429-449`). So C
requires either:

- resolving section → seq at read time via `page_index` (page → `[seq_lo, seq_hi]`)
  and then locating the matching heading block inside that span — fuzzy, and
  ambiguous for the 19 sections titled `Exercises`; or
- adding a `heading_seq` column to `source_section`, populated by `build_sections`
  by matching each TOC entry to a heading block. `build_sections` already does
  exactly this matching against `full_text` char offsets (the positional cursor
  walk from 003, `_sections_from_toc`), so it has the information — it currently
  stores `char_start` for diagnostics only and never persists a block reference.

C is also ordering-sensitive: `source_section` is populated by an async job that
lands *after* the parse header goes `ready`, so the reader must tolerate an outline
that is briefly empty or stale on a fresh parse. Today `section_index` is available
the instant the header flips.

**Recommendation.**

`A + B` together are a genuinely cheap, high-value fix: roughly two lines of config
plus a filter list, and they turn a 25%-junk flat list into a clean hierarchical one.
Neither requires touching the DB schema. The cost is a full reparse and an unmeasured
per-page pipeline hit. **Do this first** — it likely closes the user-visible problem.

Note that A and B are independent and A is worth shipping regardless: docling will
always classify a boxed `TIP` as a `SECTION_HEADER`, no matter what level it lands at.

`C` remains the architecturally correct end state and should be the target whenever
someone is next inside `build_sections`. Two things make it more attractive than it
first looks: it derives the outline from the PDF's own bookmarks — the signal docling
itself calls "the most authoritative" and has **not yet implemented** — and the
`heading_seq` column it needs is the same column block-anchored annotations would
want. It is the only option that deletes the duplicate derivation rather than
papering over it.

The honest framing: **B buys a good outline; C buys the right one.** If the reparse
is happening anyway, C is not much more work than B and is worth doing properly.

## Reproduction

```python
# reader outline: polluted + flat
si = (await repo_query(
    "SELECT section_index FROM source_parse "
    "WHERE record::id(id)[0]='bms5qu1xfaq9vvlpm11f' AND status='ready'"
))[0]["section_index"]
len(si)                                                    # 882
sum(t["title"].strip().lower() in
    {"tip","note","warning","caution","important"} for t in si)   # 179
collections.Counter(e["level"] for e in si)                # {1: 882}

# TOC outline: clean + hierarchical, same book
ss = await repo_query(
    "SELECT level FROM source_section "
    "WHERE source = source:bms5qu1xfaq9vvlpm11f")
len(ss)                                                    # 472
collections.Counter(s["level"] for s in ss)                # {3:227, 2:180, 1:27, 4:36, 5:2}
```

## Resolution (2026-07-09)

Shipped **A + a no-reparse variant of C**. Option B (docling's
`heading_hierarchy_options.enabled`) was deliberately **not** taken: the flag is
real and its prerequisite is met, but it infers levels heuristically, requires a
full reparse to take effect, and does nothing about Defect 1 — while the PDF's
bookmarks (the signal docling itself calls authoritative and has not implemented)
were available for free on already-parsed data.

### What changed

New `open_notebook/parsers/outline.py`:

- `is_junk_heading()` — **option A**. Admonitions, ebook watermarks, colon-terminated
  lead-in sentences, and bare enumerators (`CHAPTER 1`, `Part I`, a stray folio).
- `build_outline()` — aligns each TOC entry to a heading block by normalized title
  within a ±2-page window, walking a monotonic `seq` cursor (so `Exercises` ×19 map
  to distinct blocks). A second, **interval-bounded** pass retries the misses with
  the leading enumeration stripped.
- `read_pdf_toc()` / `resolve_toc()` — the TOC provider **seam**. Bookmarks are the
  only provider today; a synthesized-TOC provider (parsing a printed contents page)
  slots in behind it without touching a caller.

`finalize()` now emits the junk-filtered flat outline (the no-TOC fallback);
`build_blocks` step 3a replaces it with the aligned hierarchical one when the PDF
has bookmarks. `build_sections` shares the same `resolve_toc` seam and the same
marker set. `scripts/backfill_section_index.py` rewrites existing parses in place.

### Measured, on the two ready parses

| | before | after |
|---|---|---|
| Hands-on ML | 882 entries, `{1: 882}` | 664 entries, `{1:32, 2:212, 3:306, 4:106, 5:8}` |
| AI Engineering | 373 entries, `{1: 373}` | 371 entries, `{1:18, 2:59, 3:123, 4:171}` |

**98.9% of TOC entries** matched a heading block on both books. Unmatched entries
fall back to the first block on their bookmark page, so none are dropped. Zero
admonitions, zero watermarks. `subtree_end` is no longer degenerate: 150 entries
on the big book have a subtree spanning past the next entry, and no child's subtree
escapes its parent's.

### Correction to the analysis above

> *"The distinguishing property of the junk is that it is absent from the PDF's
> TOC, not that its title looks unusual."*

**This is false**, and a pure-TOC outline (option C as originally written) would
have silently deleted real content. Of the 418 heading blocks absent from Hands-on
ML's TOC, only 235 are junk; the other 183 are real. On AI Engineering — which has
*zero* admonitions — **196 of its 201** non-TOC heading blocks are genuine
sub-headings the publisher simply left out of the bookmark tree (`Language models`,
`Masked language model`, `Self-supervision`, `AI product defensibility`).

So `build_outline` **keeps** non-TOC headings, nesting them one level under the
preceding TOC entry, and filters them with `is_junk_heading` instead. TOC-matched
entries bypass the filter entirely — which is why a book whose bookmark is literally
`Chapter 1` keeps it, while the same text as a stray block is dropped.

### Follow-ups not done

- **No no-bookmark PDF exists to test against.** Both sources have bookmarks. The
  synthesized-TOC provider is deliberately unbuilt — see the seam. When one appears:
  the printed TOC's heading level falls out of the line's **x-indent** (measured on
  AI Engineering: x0 72.0→L1, 86.4→L2, 95.0→L3, zero misclassification), so this is
  deterministic, not an LLM job. The LLM belongs in a repair role, validated by
  aligning its output against heading blocks. Note printed page numbers need the
  full `get_page_labels()` map, not `_detect_page_offset` — AI Engineering has a
  roman front-matter run *and* an arabic body run.
- `document_block.level` / `.subtree_end` are still uniformly degenerate in stored
  rows; only `section_index` was repaired. Nothing reads them (`subtree_end` has
  zero logic consumers — it is declared in `api.ts` and never used), so this is
  latent, not live.
- `section_path` on non-heading blocks still threads through junk headings (a
  paragraph under a `TIP` callout carries `TIP` in its path). Requires a reparse to
  fix; no consumer complained yet.

## Notes

- Discovered while auditing the outline for callout pollution after 003; the fix
  was assumed to cover the reader and does not.
- Both `status='ready'` parse headers exhibit Defect 2. Only the O'Reilly book
  exhibits Defect 1.
- `source:oo9y87r4n39qlt4cfa9o` also has a `status='failed'` gen-1 header with an
  empty `section_index`; gen 2 is the live one. Unrelated to this report.
