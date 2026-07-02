# Backend Track — `api/` + `open_notebook/`

> Part of the **Codebase Readability Refactor**. Shared rules, status table, and decisions live in **[coordinator.md](coordinator.md)** — read it first. Update the Status table *there* as each chunk lands.
> **Order:** A1·A2·A3 → B1·B2·B3 → C1 (pilot) → C5·C3·C4 → **C2 last**.
> **Verify after every chunk:** `uv run pytest tests/` · `uv run mypy open_notebook/ api/` · smoke-boot `uv run uvicorn api.main:app --port 5055` and confirm `/docs` route list is unchanged after C-splits.

---

## PHASE A — Shared primitives (additive; new code, no call-site changes yet)

### A1 · `api/routers/_helpers.py` — `get_or_404` + `ensure_prefix` · LOW
~25 sites do `X = await Model.get(id); if not X: raise HTTPException(404, ...)`; ~24 sites do `id if id.startswith("t:") else f"t:{id}"`.
- Create `api/routers/_helpers.py`:
  - `async def get_or_404(model_cls, id, name, *, prefix=None)` → coerce prefix if given, fetch via `model_cls.get`, raise `HTTPException(404, f"{name} not found")` if falsy. Note `ObjectModel.get` (`open_notebook/domain/base.py:103`) raises `NotFoundError` rather than returning None for some paths — the helper should treat both "raised NotFoundError" and "returned falsy" as 404.
  - `def ensure_prefix(id, table)` → `id if id.startswith(f"{table}:") else f"{table}:{id}"`.
- **Reuse:** `ensure_record_id` (`open_notebook/database/repository.py:40`) when a `RecordID` (not a prefixed string) is needed.

### A2 · `api/service_utils.py` — `_unwrap` + `_as_list` · LOW
~30 sites do `data = resp if isinstance(resp, dict) else resp[0]` after `repo_*` calls; several do `result if isinstance(result, list) else [result]`.
- Add `def _unwrap(resp) -> dict` (dict → as-is; non-empty list → `[0]`; empty/None → match current behavior, likely raise or return None) and `def _as_list(resp) -> list`.
- **Leave alone:** per-service ISO date-parsing in `transformations_service.py` (genuine variation).

### A3 · domain `refers_to` methods + response serializers · LOW
- On `ChatSession` (`open_notebook/domain/notebook.py`): add `async def get_notebook_id(self)` wrapping `SELECT out FROM refers_to WHERE in=$id`; add the source-side equivalent used by source_chat (`SELECT in FROM refers_to WHERE out=$source_id`). Pulls raw DB queries out of routers (architecture fix — `api/CLAUDE.md`: domain owns DB).
- Add `session_to_response(session, *, notebook_id, message_count, default_title)` + `episode_to_response(episode, ...)` (in `_helpers.py` or new `api/routers/_serializers.py`). **Preserve** the title-fallback difference (`or ""` on create vs `or "Untitled Session"` elsewhere) via the `default_title` param.

---

## PHASE B — Apply the dedup

### B1 · routers adopt `get_or_404` + `ensure_prefix` · LOW
Sweep: chat, source_chat, context, sources, insights, transformations, episode_profiles, speaker_profiles, models, notebooks. Behavior identical; pass entity-specific 404 wording. **Standardize "model not found" on 404** (search.py currently 400, transformations.py 404).

### B2 · services adopt `_unwrap` · LOW
8 service files: notebook / notes / insights / models / transformations / sources / settings / episode_profiles.

### B3 · raw `refers_to` → domain; adopt serializers · MED
Replace 3× (chat) + 5× (source_chat) raw `refers_to` queries with A3 domain methods. Replace the 4× `ChatSessionResponse(...)` builds in chat + 3× in source_chat + podcast episode builds with the A3 serializers. Encode in/out direction correctly per call.

---

## PHASE C — Split the monster files

Router package conversion: `api/routers/foo.py` → `api/routers/foo/__init__.py` re-exporting `router` keeps `api/main.py` unchanged (verified: main.py does `from api.routers import foo; app.include_router(foo.router, ...)`). After each split, confirm `/docs` lists the same routes.

### C1 · `chat.py` (826) → `api/routers/chat/` · MED · **PILOT**
- `schemas.py` (pydantic request/response models, ~lines 33-185)
- `citations.py` (`_make_snippet`/`_fetch_citation_meta`/`_resolve_citations`/`_build_chat_message`, ~187-315 — pure, now unit-testable)
- `sessions.py` (session CRUD)
- `execute.py` (`execute_chat` + `build_context`)
- `media.py` (`_classify_media` + upload/serve)
- `__init__.py` mounts the sub-routers under one `router`.

### C5 · `podcasts.py` (299) → response-mapping helper · LOW–MED
Extract episode→response build + job-status/audio-url derivation into `episode_to_response` (A3); push `_resolve_audio_path` toward `upload_utils`. Smallest split — good warm-up after C1.

### C3 · `models.py` (831) → extract provider logic to service · MED
Move provider helpers (`_check_provider_has_credential`/`_check_azure_support`/`_check_openai_compatible_support`, ~125-177) and the 114-line `get_provider_availability` (~416-530) into `models_service.py`. Router becomes thin HTTP.

### C4 · `source_chat.py` (554) → extract streaming/graph to service · MED
Move SSE streaming + graph-invocation + context-indicator building (~417-554) into `source_chat_service.py`; thin router. Coordinate with B3 (this file's `refers_to`/serializer dedup must already be done).

### C2 · `sources.py` (998) → package + service extraction · HIGH · **LAST**
- `api/routers/sources/` package; push the 290-line `POST /sources` (upload→extract→transform→embed, ~234-524) and 131-line retry (~768-898) into `sources_service.py`; router keeps thin HTTP + form parsing.
- Merge `_resolve_source_file` (~533-556) into existing `upload_utils.resolve_within`.
- Extract `source_to_response` helper for the repeated response mapping.
- **Most tests live here (`tests/test_sources_api.py`) — lean on them; do this split last and carefully.**

---

## Reuse map (don't reinvent)
- `open_notebook/database/repository.py`: `ensure_record_id:40`, `repo_query:65`, `repo_create/update/upsert/delete`.
- `open_notebook/domain/base.py`: `ObjectModel.get:103` (polymorphic, raises `NotFoundError`).
- `api/main.py:198-286`: global exception handlers (`NotFoundError`→404, `InvalidInputError`→400, etc.) — prefer raising typed exceptions over manual `HTTPException` where it reads cleaner.
- `api/upload_utils.py`: `resolve_within` (path-traversal guard) — target for the `_resolve_source_file` merge.
