# B2 (verify-clean) + B3 (summaries/abstract) produce nothing on real books

**Status:** Open · **Found:** 2026-07-03 · **Area:** `commands/verify_commands.py`, `commands/summary_commands.py`, `open_notebook/graphs/source.py`
**Severity:** High — the layered doc model (cleaned content, per-section summaries, doc abstract) is empty for real multi-chapter PDFs. Also the visible cause of raw `<!-- image -->` placeholders showing in the Content tab (B2 never writes `cleaned_content`).

## Symptoms (observed)
Reprocessed the Hands-on ML book (`source:jnunvbxml03utb8x6kww`, 472 chapters, 1659 embeddings):
- **B2**: `verify_clean_section` completed ~117× but wrote **0** `cleaned_content` and **0** `verify_flag` insights (silent skip / no-op).
- **B3**: **0/472** section summaries written; `generate_source_abstract` failed (it retries until all text-bearing sections have summaries, then gives up).

## Pipeline context (where these run)
1. Extract — content-core (PyMuPDF) + Docling (`_extract_docling_page_map`, OCR disabled) → `full_text` + `page_map`. No LLM.
2. Embed — `source.vectorize()` → `qwen3-embedding:8b`. Works.
3. Chapter — `build_sections` → `source_section` tree w/ page ranges. Deterministic, no LLM. Works (472 sections).
4. **B2 verify-clean** — `verify_clean_section` renders each section's PDF pages to PNG + parsed text → **vision model (qwen3.6:35b)** → `cleaned_content`. **Broken.**
5. **B3 summaries** — `summarize_section` (per section) + `generate_source_abstract` → **transformation model (qwen3.6)**. **Broken.**

## Leading hypotheses (NOT yet confirmed by live repro)
The handoff blamed "qwen thinking-model burns its token budget in `<think>` and returns empty because max_tokens is unset." **That mitigation is already in the code** — `max_tokens=8192` is passed at [verify_commands.py:315](../commands/verify_commands.py#L315), [summary_commands.py:136](../commands/summary_commands.py#L136), [:228](../commands/summary_commands.py#L228), and `clean_thinking_content()` strips `<think>`. So the simple explanation is insufficient. Real suspects, by layer:

**B2 (strong non-qwen suspect):** ingestion sets [`auto_delete_files="yes"`](../open_notebook/graphs/source.py#L98). If the uploaded PDF is deleted after extraction, **every** `verify_clean_section` hits the "no on-disk PDF → skip" branch ([verify_commands.py:246-252](../commands/verify_commands.py#L246-L252)) and writes nothing — no qwen involvement at all. Also check `section.page_start is None` (skip branch at :254; note the TOC also isn't showing page ranges → same data gap suspected). Secondary: qwen vision genuinely returning empty.

**B3:** would only write 0 if qwen returns empty/errors on essentially every call. `summarize_section` falls back to raw `content` when `cleaned_content` is absent, so B2 being broken does NOT by itself explain B3=0 — sections must have text. If qwen3.6 (35B thinker) exhausts 8192 tokens inside `<think>` on a full chapter, output is empty → 0 summaries → abstract retries 8× then fails.

## Diagnostic to run first (read-only)
1. Check whether the source PDF still exists on disk: `Source.get(...).asset.file_path` → `Path(...).exists()`. If false → B2 root cause is `auto_delete_files`, fix is to preserve the PDF (or re-render from a stored copy).
2. Reproduce ONE `verify_clean_section` and ONE `summarize_section` on an ML-book section id; print: does it hit a skip branch? raw model output length? is output non-empty before `clean_thinking_content`, empty after (→ all-`<think>`)?
3. From that, decide: preserve PDF (B2), and/or raise qwen max_tokens well above 8192 / disable thinking / route summaries to a non-thinking model (B3).

## Also worth doing regardless
- `open_notebook/graphs/ask.py` caps every node at `max_tokens=2000` → empty answers with qwen3.6; raise to ~8000 (local GPU, cost not a constraint).

## Related
- `<!-- image -->` placeholders in Content tab = symptom of B2 never producing `cleaned_content`.
- Plan docs `.claude/plans/document-foundation/{coordinator,b-pipeline}.md` currently overstate B2/B3 as ☑ — correct once root-caused.
