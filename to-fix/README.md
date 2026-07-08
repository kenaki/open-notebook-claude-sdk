# to-fix — investigation backlog

Reports created by `/investigate`. Each file is a self-contained, read-only
investigation of a bug, question, or observation. Status is maintained by hand
(or by whoever fixes the item). This directory is committed to the repo.

All four items are **code-complete and landed on `feature/multipanelchat`**; offline tests
pass (24/24 across `tests/test_section_bounds.py` + `tests/test_url_validation.py`, re-run
2026-07-06). The only work left on any item is a **live GPU re-run / sign-off** that needs the
worker + services running — those are handed back to the user, not code tasks.

| ID | Title | Type | Severity | Status | Area | Created |
| --- | --- | --- | --- | --- | --- | --- |
| [001](001-chat-failure-reported-as-ready.md) | Failed chat jobs are silently reported as "ready" with an empty reply | bug | high | resolved (code `3537d09`; live repro pending) | chat jobs / background job polling | 2026-07-03 |
| [002](002-illustrate-image-fetch-ssrf.md) | Auto-illustrate image fetches — SSRF in judge fetch + safety bait-and-switch | security | high | fixed (code `5edf9f1`+guard; SSRF matrix green; user sign-off pending) | `open_notebook/graphs/illustrate.py` (W2/W3) | 2026-07-04 |
| [003](003-chaptering-section-content-unbounded.md) | Chaptering mis-bounds section content — a "section" can hold ~the whole book | correctness | high | fixed (code `9ec7b8a`; bounds verified live; b2/b3 re-run in coordinator) | `commands/section_commands.py` | 2026-07-05 |
| [b2-b3](b2-b3-pipeline-empty-output.md) | B2 (verify-clean) + B3 (summaries/abstract) produce nothing on real books | bug | high | fixed in code (`7c51ea5`; full-book re-run pending) | doc pipeline (`commands/verify_commands.py`, `commands/summary_commands.py`) | 2026-07-03 |
