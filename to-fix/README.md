# to-fix — investigation backlog

Reports created by `/investigate`. Each file is a self-contained, read-only
investigation of a bug, question, or observation. Status is maintained by hand
(or by whoever fixes the item). This directory is committed to the repo.

**Open:** 005 (verify page bleed — blocks re-running verify) and 006 (reader outline).
004 is built and tested but **uncommitted**, and half of its Finding 2 is superseded by 005.
001, 002, 003 and b2-b3 are code-complete on `feature/multipanelchat`; the only work left on
those is a **live GPU re-run / sign-off** that needs the worker + services running — handed
back to the user, not code tasks.

| ID | Title | Type | Severity | Status | Area | Created |
| --- | --- | --- | --- | --- | --- | --- |
| [001](001-chat-failure-reported-as-ready.md) | Failed chat jobs are silently reported as "ready" with an empty reply | bug | high | resolved (code `3537d09`; live repro pending) | chat jobs / background job polling | 2026-07-03 |
| [002](002-illustrate-image-fetch-ssrf.md) | Auto-illustrate image fetches — SSRF in judge fetch + safety bait-and-switch | security | high | fixed (code `5edf9f1`+guard; SSRF matrix green; user sign-off pending) | `open_notebook/graphs/illustrate.py` (W2/W3) | 2026-07-04 |
| [003](003-chaptering-section-content-unbounded.md) | Chaptering mis-bounds section content — a "section" can hold ~the whole book | correctness | high | fixed (code `9ec7b8a`; bounds verified live; b2/b3 re-run in coordinator) | `commands/section_commands.py` | 2026-07-05 |
| [b2-b3](b2-b3-pipeline-empty-output.md) | B2 (verify-clean) + B3 (summaries/abstract) produce nothing on real books | bug | high | fixed in code (`7c51ea5`; full-book re-run pending) | doc pipeline (`commands/verify_commands.py`, `commands/summary_commands.py`) | 2026-07-03 |
| [004](004-verify-summarize-output-bounds.md) | Verify silently truncates large sections; summaries ~3x longer than consumed; verify re-proofs the book 2.6x over | correctness + efficiency | high | partially superseded by 005; code built + tested but **uncommitted** | `commands/verify_commands.py`, `commands/summary_commands.py` | 2026-07-09 |
| [005](005-verify-page-bleed-and-unbounded-proof-output.md) | Verify renders whole pages for sub-page sections, so `cleaned_content` absorbs neighbouring text; proof output has no upper bound | correctness (live data corruption) | high | **open** — diagnosed + measured, nothing built | `commands/verify_commands.py` | 2026-07-09 |
| [006](006-reader-outline-flat-and-unfiltered.md) | Reader outline is built from raw heading blocks, not the TOC — carries TIP/NOTE/WARNING callouts and has no hierarchy | correctness (UX) | medium | **open** — diagnosed + measured; Defect 2 is a one-line docling flag | `open_notebook/parsers/`, `ReaderOutline.tsx` | 2026-07-09 |
