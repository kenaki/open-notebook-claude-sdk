# Codebase Cleanup Audit — Open Notebook

> **Status:** Phase 1 (audit) COMPLETE — read-only, no files touched. Phase 2 (apply) NOT STARTED.
> **Produced:** 2026-06-23 · **Branch:** feature/multipanelchat
> **Origin:** `/codebase-cleanup-sweep` skill (audit-first, slice-by-slice apply).

This is a living plan. Each cluster below is a candidate **slice** = one reviewable commit/PR.
Citations are `file:line`, verified by the audit agents against the real files (line numbers
drift as the code changes — re-confirm before editing).

---

## How to resume (fresh session)

1. Read this doc. Pick slices by ID (e.g. `T1-a`) — a single ID, a tier, or "backend Tier 1".
2. For each chosen slice, run the `code-structure-cleanup` 6-step pass scoped to that slice only:
   inspect → confirm the duplication → smallest extraction → update every call site → run
   typecheck/tests → summarize what got simpler. **One slice = one commit. Never batch unrelated slices.**
3. Update the Status table below as slices land.
4. **Gate:** `T1-c` and `T1-e` are blocked on the error-resolver decision (see "Decision gate"). Resolve it before those two.
5. Verify per slice: user-facing behavior unchanged · call sites actually collapsed · calling files simpler · tests/typecheck ran · slice is its own focused diff.

### Commands
- Backend tests: `uv run pytest tests/`
- Frontend typecheck: `cd frontend && npx tsc --noEmit` (and lint/test per its config)

---

## Status

| ID | Slice | Tier | Sites | Risk | Status |
|----|-------|------|-------|------|--------|
| T1-a | FE api `response.data` unwrap → client helpers | 1 | 88 | LOW | not started |
| T1-b | `get_or_404` + `ensure_prefix` helpers | 1 | ~49 | LOW | not started |
| T1-c | FE mutation `onError` → `useErrorToast` ⚠️gated | 1 | 44 | LOW | not started |
| T1-d | Service-layer `_unwrap` | 1 | ~26 | LOW | not started |
| T1-e | FE chat-hook `toastApiError` ⚠️gated | 1 | 15 | LOW | not started |
| T1-f | FE `format.ts` (number + date) | 1 | ~17 | LOW–MED | not started |
| T1-g | Backend small wins bundle | 1 | ~17 | LOW | not started |
| T1-h | `_as_list` + persisted enum-store factory | 1 | ~8 | LOW | not started |
| T2-a | `session_to_response` / `episode_to_response` | 2 | 10 | LOW–MED | not started |
| T2-b | PodcastService/CommandService job-status dedup | 2 | 2 blk | LOW–MED | not started |
| T2-c | `require_model` / `require_embedding_model` guards | 2 | ~9 | LOW–MED* | not started |
| T2-d | `_prepare_save_data` → `record_id_fields` ClassVar | 2 | 5 | MED | not started |
| T2-e | surreal-commands handler skeleton | 2 | ~11 | MED | not started |
| T2-f | model_discovery openai-compatible helper + table | 2 | ~10 | MED | not started |
| T2-g | Adopt `LoadingSpinner` over inline `Loader2` | 2 | ~20 | MED | not started |
| T2-h | Adopt `EmptyState` over inline empty blocks | 2 | ~8 | MED | not started |
| T2-i | Adopt `ConfirmDialog` over hand-rolled `AlertDialog` | 2 | 4 | MED | not started |
| T2-j | SSE `streamFetch` + `getAuthToken` | 2 | 2–3 | MED | not started |
| T2-k | Credential migration twins helper | 2 | 2 | MED | not started |
| T3-a | `chat_service.py` async HTTP idiom → `_arequest` | 3 | 7 | MED | not started |
| T3-b | Router raw `refers_to` queries → domain methods | 3 | 8 | MED | not started |
| T3-c | `RecordModel.get_fresh_instance` | 3 | 2 | MED | not started |
| T3-d | Graph async/sync event-loop bridge helper | 3 | 3 | MED | not started |
| T3-e | NotebookCard/NotebookRow shared actions | 3 | 2 | MED | not started |
| T3-f | Speaker/Episode ProfilesPanel scaffold | 3 | 2 | MED | not started |
| T3-g | Fetch-in-`useEffect` → TanStack hooks | 3 | ~20 | HIGH | not started |

\* T2-c has a 400-vs-404 inconsistency to resolve first (see detail).

---

## Summary

- **Slices scanned:** `api/` (22 routers + ~24 service files), `open_notebook/` (domain/ai/graphs/database/utils/podcasts + `commands/`), `frontend/src/lib/` (api clients/hooks/stores/utils), `frontend/src/components/` + `app/`. ~380 files.
- **Clusters found:** 36 + report-only items.
- **Call sites that collapse:** ~450+.
- The repo already has good shared primitives (`api/main.py` global exception handlers, `repository.py` repo_* helpers, `domain/base.py` model bases, `lib/api/client.ts`, `common/EmptyState`/`LoadingSpinner`/`ConfirmDialog`, `utils/error_classifier.classify_error`). Most duplication re-implements by copy-paste what a primitive already offers, or should have a primitive and doesn't.

---

## ⚠️ Decision gate (blocks T1-c and T1-e)

`frontend/src/lib/utils/error-handler.ts` exports **two** error-message resolvers, chosen ad-hoc per hook with no rule:
- `getApiErrorKey` → returns an i18n **key** (caller must `t()` it). Used in use-credentials.ts:12, use-models.ts:6, use-notebooks.ts:10, use-notes.ts:6, use-podcasts.ts:8, use-search.ts:4.
- `getApiErrorMessage` → returns **translated text or the raw backend string**. Used in use-settings.ts:6, use-sources.ts:7, use-ask.ts:6, use-transformations.ts:5, useSourceChat.ts:6, useNotebookChat.ts:6.

They produce **different user-facing strings** for an unmapped backend error (generic translated fallback vs raw backend message). Which to standardize on is a **product decision**, not mechanical — unifying blindly silently changes error copy app-wide. **Answer this before T1-c/T1-e.**

---

## TIER 1 — High payoff, LOW risk (do first)

### T1-a · Frontend API `response.data` unwrap  — payoff VERY HIGH (88) · risk LOW · slice `lib/api`
Every resource method is `const r = await apiClient.X(url); return r.data`. `client.ts` exports only the raw axios instance (no shared `request()`), so 14 modules reimplement the unwrap.
- `return response.data` counts: credentials.ts(13), models.ts(15), podcasts.ts(12), notebooks.ts(8), chat.ts(7), sources.ts(7), transformations.ts(7), notes.ts(4), source-chat.ts(4), insights.ts(4), embedding.ts(3), settings.ts(2), search.ts(1).
- void-delete variants: notes.ts:26, sources.ts:75, transformations.ts:33, models.ts:34, insights.ts:51, chat.ts:48, podcasts.ts:39/72/103.
- **Extraction:** `get<T>(url,cfg)`, `post<T>(url,body,cfg)`, `put<T>(url,body,cfg)`, `del(url,cfg)` in `lib/api/client.ts`.
- **Leave alone:** `sources.downloadFile` needs the full `AxiosResponse<Blob>` — keep on raw apiClient.
- **Behavior change:** none.

### T1-b · `get_or_404` + record-id `ensure_prefix`  — payoff HIGH (~49) · risk LOW · slice `api/routers`
- **`get_or_404`** (`X = await Model.get(id); if not X: raise HTTPException(404, ...)`), ~25 sites:
  notebooks.py:162-163; insights.py:16-17,42-43,60-61; sources.py:137-138,251-252,307-310,577-578,671,731-732,774-775,904-905,922-923,962-963,967-968; context.py:17-19; transformations.py:86-88,91-93,165-167,196-198,239-241; episode_profiles.py:64-68,133-137,159-163,185-189; speaker_profiles.py:52-56,109-113,135-139,161-165; models.py:284-290; chat.py:323-325,367-369,419-421,487-489,555-557,580-582,667-669; source_chat.py:100-102,142-144,207-209,217-219,305-307,315-317,375-377,385-387,495-497,505-507.
- **`ensure_prefix`** (`id if id.startswith("t:") else f"t:{id}"`), ~24 sites:
  chat.py:414-418,438-442,482-486,514-515,552-553,577-578,685,714 (414 & 438 recompute the same value twice); source_chat.py:98,140,205,212-216,303,312-313,373,382-383,493,502-503; context.py:35,64.
- **Extraction:** `get_or_404(model_cls, id, name)` + `ensure_prefix(id, table)` in new `api/routers/_helpers.py`. (Domain already has `ensure_record_id` — reuse if it fits.)
- **Behavior change:** none; pass entity-specific 404 wording as a param.

### T1-c · Frontend mutation `onError` toast → `useErrorToast`  — payoff HIGH (44) · risk LOW · slice `lib/hooks` ⚠️GATED
44 byte-identical destructive-toast handlers (`onError: (error: unknown) => ...`):
- use-podcasts.ts: 105,129,167,198,223,249,296,328,354,379,405 (11)
- use-credentials.ts: 94,128,163,198,230,274,327,380 (8)
- use-sources.ts: 123,152,181,212,271,334 (7, incl. useAddSourcesToNotebook)
- use-models.ts: 46,72,103,142,183,204 (6)
- use-transformations.ts: 49,75,99,115,146 (5)
- use-notebooks.ts: 118,144,184 (3); use-notes.ts: 42,68,94 (3); use-settings.ts: 30 (1)
- **Extraction:** `useErrorToast()` in `lib/hooks/use-error-toast.ts` closing over `useToast()`+`useTranslation()`, returning `(error, fallbackKey?) => void` (title `t('common.error')`, `variant: 'destructive'`). Call sites become `onError: (e) => showError(e, 'sources.failedToAddSource')`.
- **Blocked by the decision gate** (which resolver the hook uses internally).

### T1-d · Service-layer `_unwrap`  — payoff HIGH (~26) · risk LOW · slice `api services`
`data = resp if isinstance(resp, dict) else resp[0]` + domain hydration in every read/create/update method:
notebook_service.py:39,53,72 (+loop 24-33); notes_service.py:40,64,85 (+loop 24-33); insights_service.py:64 (+loops 24-33,38-51,83-96); models_service.py:39,58,91 (+loop 24-33); transformations_service.py:46,79,109 (+loop 25-40); sources_service.py:106,177,205,222,299 (+loop 79-100); settings_service.py:20-24,54-58; episode_profiles_service.py:43-47,86-90 (+loop 24-37).
- **Extraction:** `_unwrap(resp) -> dict` in `api/client.py` or a new `api/service_utils.py`.
- **Leave alone:** transformations_service date-parsing (`datetime.fromisoformat(...replace("Z","+00:00"))` at 34-39,55-60,88-93,117-119) is the only real variation — keep per-service.

### T1-e · Frontend chat-hook `toastApiError`  — payoff MED (15) · risk LOW · slice `lib/hooks` ⚠️GATED
Hand-rolled `err as {response?:{data?:{detail?:string}}, message?:string}` cast + `toast.error(getApiErrorMessage(...))`, duplicating logic `formatApiError` already has:
- useNotebookChat.ts: 184-185,204-206,226-228,315-316,354-357,442-444,466-468,498-500,532-534,550-552 (10)
- useSourceChat.ts: 66-67,80-82,98-100,116-119,194-197 (5)
- **Extraction:** `toastApiError(err, t, fallbackKey)` in `lib/utils/error-handler.ts` (these are deliberately direct `sonner` toasts — keep as a util, not the `useToast` hook). Same gate as T1-c.

### T1-f · Frontend `format.ts` (number + date)  — payoff MED (~17) · risk LOW–MED · slice `components`
- Byte-identical `formatNumber` (K/M): `common/ContextIndicator.tsx:18-26`, `podcasts/GeneratePodcastDialog.tsx:43-52`.
- Inline `new Date(...).toLocaleString()`: `source/SourceDetailContent.tsx:785,797`; `app/(dashboard)/advanced/components/RebuildEmbeddings.tsx:306,308`; `sources/AddExistingSourceDialog.tsx:178` (`toLocaleDateString`).
- Repeated `formatDistanceToNow(new Date(x), {addSuffix:true, locale:getDateLocale(language)})`: NotebookCard.tsx:113-116, NotebookRow.tsx:95-98, SourceDetailContent.tsx:779-782 & 791-794, EpisodeCard.tsx:208-211 (+ SessionManager, ChatGallery:130, NotesColumn:137).
- **Extraction:** `lib/utils/format.ts` → `formatCompactNumber(n)`, `formatAbsolute(date,lang)`, `formatRelative(date,lang)` (wrap the existing `getDateLocale`).
- **Watch:** `auth/LoginForm.tsx:105` and `GeneratePodcastDialog.tsx:373` use a hand-rolled locale ternary differing slightly from `getDateLocale` for zh — verify before collapsing.

### T1-g · Backend small wins (bundle)  — payoff MED (~17) · risk LOW · slice `open_notebook`
- **`full_model_dump`** byte-for-byte in 3 modules → move to `open_notebook/utils/` (one is a dead import): commands/source_commands.py:21, commands/embedding_commands.py:16 (dead), commands/podcast_commands.py:40.
- **Graph-node error-wrap** (`except OpenNotebookError: raise / except Exception: classify_error→raise`) → `@graph_node` decorator: graphs/ask.py:76-80,120-124,139-143; graphs/source_chat.py:47-51; graphs/chat.py:181-185; graphs/transformation.py:64-68. (graphs/prompt.py:20 LACKS the wrap — add it for consistency.)
- **`get_command_status` wrapper** (4 methods, guard→lazy import→await→`except: return "unknown"`) → shared helper / `JobTrackedModel`: domain/notebook.py:388 (`Source.get_status`),:402 (`get_processing_progress`); podcasts/models.py:231 (`get_job_status`),:244 (`get_job_detail`).
- **`get_by_name`** single-row lookup → `ObjectModel.get_one_by(field,value)` on `base.py`: podcasts/models.py:116 (EpisodeProfile),:192 (SpeakerProfile).
- **`command` field_validator + `get_source`** → shared: domain/notebook.py:370 & podcasts/models.py:262 (validator); domain/notebook.py:312 (`SourceEmbedding.get_source`) & :332 (`SourceInsight.get_source`).
- *These are independent micro-extractions; can be 1 commit or split. Keep `get_by_name`/`command-validator` aligned with T2-d's `record_id_fields`.*

### T1-h · `_as_list` + persisted enum-store factory  — payoff LOW–MED (~8) · risk LOW
- `result if isinstance(result, list) else [result]` → `_as_list`: client.py:89,163,196 (+ more list methods); podcast_api_service.py:23,81.
- `stores/chat-gallery-view-store.ts:14-24` ≈ `stores/notebook-view-store.ts:11-21` (near-identical persist+setter) → `createPersistedEnumStore<T>(name, default)` in `lib/stores/create-view-store.ts`. (Toggle stores sidebar-store/utility-drawer-store are similar but have bespoke field names — report only.)

---

## TIER 2 — Medium payoff/risk (after Tier 1, with review)

### T2-a · `session_to_response` / `episode_to_response` serializers — 10 · LOW–MED · `api/routers`
- ChatSession→response 10-field mapping: chat.py:337-350,385-396,457-468,526-537 (4×); source_chat.py:114-122,170-179,344-352 (3×). **Preserve** the title-fallback difference (create uses `or ""`, others `or "Untitled Session"`) — make it a param.
- PodcastEpisode→response + job-status/audio-url derivation: podcasts.py:118-133 & 170-183 (build), ~100-110 & ~150-162 (job-status), ~112-116 & ~164-168 (audio-url). Helper can call existing `_resolve_audio_path` + `episode.get_job_detail()`.

### T2-b · PodcastService/CommandService job-status dedup — 2 blocks · LOW–MED · `api services`
- Status dict **byte-identical**: podcast_service.py:119-133 == command_service.py:51-65.
- Submit preflight near-identical: podcast_service.py:89-105 ≈ command_service.py:21-40.
- **Extraction:** have `PodcastService.get_job_status` call `CommandService.get_command_status`; move dict-shaping into one `_serialize_command_status`. Preserve podcast's `HTTPException(500)` on failure (109-112,136-138) — keep HTTP-ification in the router.

### T2-c · `require_model` / `require_embedding_model` guards — ~9 · LOW–MED · `api/routers`
- Model-exists guard: search.py:117-136 & 164-183 (two near-identical twins, 6 raises); transformations.py:91-93.
- Embedding-model guard (same message): embedding.py:18-22; search.py:138-143,185-190.
- **⚠️ Inconsistency to resolve first:** search uses **400**, transformations.py:91-93 uses **404** for the same "model not found". Decide intended status before extracting.
- *Which models a feature requires = policy; leave that. Extract only the guard mechanic.*

### T2-d · `_prepare_save_data` → declarative `record_id_fields` ClassVar — 5 · MED · `domain/base`
Overrides that only RecordID-coerce FK fields: ai/models.py:43 (`credential`); domain/notebook.py:576 (`command`); podcasts/models.py:89 (outline_llm/transcript_llm),:171 (voice_model + per-speaker),:269 (command).
- **Extraction:** add `record_id_fields: ClassVar[set[str]] = set()` to `ObjectModel`; base `_prepare_save_data()` (base.py:195) auto-coerces. Subclasses declare the set. **Keep the `if data.get(field)` truthiness guard** so behavior is identical.
- *Exclude credential.py:227 & provider_config.py:411 — those do encryption, genuinely different.*

### T2-e · surreal-commands handler skeleton — ~11 · MED · `commands/`
`start_time=time.time()` → try → `processing_time` → 3-arm except ladder (permanent ValueError → failure payload/re-raise; generic → debug-log transient + raise), `cmd_id=get_command_id(...)` logging ~12×:
embedding_commands.py:188,283,380,516,602,667,731; source_commands.py:61,192; podcast_commands.py:70; example_commands.py:44,94.
- **Extraction:** `@timed_command` / `async with command_run(input_data) as ctx:` in `commands/_command_runner.py`.
- **⚠️ Risk:** surreal-commands distinguishes job `failed` vs `completed` by whether the handler RAISES (documented source_commands.py:141-148). The wrapper must preserve raise-vs-return per command exactly or job status shifts. Do AFTER the LOW-risk ones.

### T2-f · model_discovery openai-compatible helper + config table — ~10 · MED · `ai/`
HTTP "list models" funcs sharing the same fetch/parse loop: ai/model_discovery.py discover_openai:198, google:251, ollama:294, groq:327, mistral:361, deepseek:400, xai:434, openrouter:468, dashscope:582, minimax:616, openai_compatible:650. (Static-list ones anthropic:232/voyage:503/elevenlabs:525/deepgram:552 are data — exclude.)
- **Extraction:** `async def _discover_openai_compatible(url, env_key, provider, *, capability_fn=None)` + a `{provider: (url, env_key, capability_fn)}` table.
- **⚠️ Risk:** each has subtle field handling (Google strips `models/` + overrides type at :273; OpenRouter forces `"language"`; openai_compatible reads Credential first + catches `HTTPStatusError`). `capability_fn` must capture each or classification changes.

### T2-g · Adopt `LoadingSpinner` over inline `Loader2 … animate-spin` — ~20 · MED · `components` (site-by-site)
source/MessageActions.tsx:85; source/ChatPanel.tsx:492,588,605; settings/MigrationBanner.tsx:40; podcasts/EpisodesTab.tsx:102-106,130-135; podcasts/TemplatesTab.tsx:101-104; podcasts/GeneratePodcastDialog.tsx:182-185,258,898,966; sources/AddSourceDialog.tsx:476; sources/AddExistingSourceDialog.tsx:207-209,214-218; source/NotebookAssociations.tsx:120-122,215-219; common/CommandPalette.tsx:221; common/LanguageLoadingOverlay.tsx:86.
- **⚠️** `LoadingSpinner` sizes are fixed (sm/md/lg = h-4/6/8); several sites use off-scale (h-3/3.5/5/12) or extra color/position classes — swap **site-by-site**, not a sweep. EpisodeCard.tsx:391 animates a `RefreshCcw`, not Loader2 — **skip**.

### T2-h · Adopt `EmptyState` over inline empty blocks — ~8 · MED · `components`
notebooks/ChatGallery.tsx:1077-1092 (a local `function EmptyState` that **shadows** common/EmptyState — clearest win) & :316-318; source/ChatPanel.tsx:388-410; source/SourceDetailContent.tsx:620-625; source/SessionManager.tsx:154-163; podcasts/EpisodesTab.tsx:137-143, EpisodeProfilesPanel.tsx:102-105, SpeakerProfilesPanel.tsx:85-88 (3 near-identical dashed "no X yet" boxes); notebooks/ChatSidebar.tsx:92 (text-only, minor).
- **⚠️** Inline ones carry feature-specific markup (ChatPanel suggestion buttons; dashed-border styling; ChatGallery themed tokens `bg-accent-soft`/`text-text-3`). Needs a `className`/`variant` prop or markup shifts.

### T2-i · Adopt `ConfirmDialog` over hand-rolled delete `AlertDialog` — 4 · MED · `components`
podcasts/EpisodeCard.tsx:395-416; podcasts/SpeakerProfilesPanel.tsx:179-237; podcasts/EpisodeProfilesPanel.tsx:142-192; source/SourceInsightDialog.tsx:98-151 (inline conditional, not even AlertDialog). Target primitive: common/ConfirmDialog.tsx:27-66.
- **⚠️** ConfirmDialog is self-rendering (no trigger child); profile panels nest the trigger inside a DropdownMenuItem — converting changes the open mechanism (onSelect→setOpen). **Do AFTER T3-f** (its `<ProfileActionsMenu>` is the right seam).

### T2-j · SSE `streamFetch` + `getAuthToken` — 2–3 · MED · `lib/api`
client.ts:37-49 already parses the Bearer token from `localStorage['auth-storage']`; two streaming fns copy it verbatim (can't use the axios interceptor): search.ts:14-27 (token) + 34-60 (fetch+ok-check); source-chat.ts:51-64 (token) + 71-83 (fetch+ok-check).
- **Extraction:** export `getAuthToken()` from client.ts + a `streamFetch(url, body)` helper.
- **⚠️** search.ts:43-53 extracts richer errors (`errorData.detail||message`) while source-chat.ts:79-81 only throws `HTTP error! status:` — unifying improves source-chat (behavior shift, arguably a fix). Verify SSE error path.

### T2-k · Credential migration twins — 2 · MED · `lib/hooks`
use-credentials.ts:294-299 & 348-352 (identical 5-key invalidation) + the migrated/error count→toast ladder at :301-325 vs :354-378 (4 branches).
- **Extraction:** `invalidateAfterMigration(qc)` + `migrationResultToast(result, t, toast)`. **Do NOT touch the rest of the invalidation sets — intentional policy.**

---

## TIER 3 — Higher risk / do last / per-file

### T3-a · `chat_service.py` async HTTP idiom → `_arequest` — 7 · MED · `api`
7 methods each open `httpx.AsyncClient()`, attach `self.headers`, `raise_for_status()`, `return .json()`, wrapped in try/except-log-raise: chat_service.py:24-37,39-63,65-77,79-108,110-122,124-147,149-164. Auth-header init at 17-22 duplicates client.py:43-46.
- **Extraction:** async `_arequest(method, path, **kw)` on `APIClient`. **⚠️** `execute_chat` uses a custom long read-timeout (line 138) — helper must allow per-call `timeout=` (client.py `_make_request` already supports it).

### T3-b · Router raw `refers_to` queries → domain methods — 8 · MED · `api`
chat.py:444-447,517-…,585-… (`SELECT out FROM refers_to WHERE in=$session_id`, 3×); source_chat.py:147-150,222-224,320-…,390-…,510-… (4×). Reaches into DB from the router (architecture says domain/services own this).
- **Extraction:** `ChatSession.get_notebook_id_for_session()` / `session_belongs_to_source()` (domain) or `api/routers/_chat_queries.py`. **⚠️** in/out direction differs per call — encode correctly.

### T3-c · `RecordModel.get_fresh_instance` — 2 · MED · `domain/base`
ai/models.py:74 (DefaultModels) & domain/provider_config.py:198 (ProviderConfig) repeat the `repo_query(SELECT * FROM ONLY $record_id)` + isinstance-unwrap + `object.__new__`/`object.__setattr__` ritual to bypass the singleton cache (base.py:254). ProviderConfig adds decryption.
- **Extraction:** `RecordModel.get_fresh_instance()` (or `fresh=True`) on base.py returning raw `data` for subclasses to post-process. **⚠️** touches the `__new__` singleton-cache contract; tests rely on `clear_instance()` (base.py:352). (The unwrap ladder also recurs at base.py:291-303 — report only.)

### T3-d · Graph async/sync event-loop bridge helper — 3 · MED · `graphs`
Same `run_in_new_loop()` + `get_running_loop()`→ThreadPoolExecutor else `asyncio.run()` dance: chat.py:150-173; source_chat.py:62-90 & 134-171. Flagged fragile in graphs/CLAUDE.md:17.
- **Extraction:** `run_async_in_node(coro)` in `utils/graph_utils.py` (already exists, does to_thread bridging at :7). **⚠️** timing-sensitive — reproduce the exact branch or chat can deadlock.

### T3-e · NotebookCard / NotebookRow shared actions — 2 · MED · `app/(dashboard)/notebooks`
Twin components: NotebookCard.tsx:25-141 & NotebookRow.tsx:26-149. Near-identical sub-blocks: archive/delete menu (Card 67-103 ≈ Row 101-138); count badges (Card 120-129 ≈ Row 83-92); `handleArchiveToggle` (Card 32-38 = Row 33-39); click-to-navigate (Card 40-43 ≈ Row 41-44); `formatDistanceToNow` (Card 113-116 ≈ Row 95-98); delete-dialog mount (Card 133-138 = Row 141-146).
- **Extraction:** `useNotebookCardActions(notebook)` hook + `<NotebookActionsMenu>` + `<NotebookCountBadges>`. **⚠️** Row uses a real `<Link>` (59-69) + extra focus classes (107) for a11y — preserve.

### T3-f · Speaker/Episode ProfilesPanel scaffold — 2 · MED · `components/podcasts`
SpeakerProfilesPanel.tsx:85-88/97-134/171-238 ≈ EpisodeProfilesPanel.tsx:102-105/116-133/134-193 (empty block + card header + Edit/Duplicate/Delete menu-in-AlertDialog).
- **Extraction:** `<ProfileActionsMenu>` + `<ProfileCardHeader>` with optional slots. **⚠️** Speaker adds a `deleteDisabled` reason paragraph (221+) + usage badge Episode lacks — keep as optional slots. This is the seam for T2-i.

### T3-g · Fetch-in-`useEffect` → TanStack hooks — ~20 · **HIGH** · `components` (PER-FILE ONLY)
Biggest raw payoff, **riskiest** — changes cache keys, invalidation timing, loading/error state, polling lifecycle.
- source/SourceDetailContent.tsx (heaviest): imports sourcesApi/insightsApi/transformationsApi/embeddingApi (8-11); fetch-in-effect 105/125/136/143-149; direct mutations 159,203,219,234,275,362,825.
- app/(dashboard)/sources/page.tsx: `fetchSources()` + effects 42-85,88-145; delete 242.
- sources/AddExistingSourceDialog.tsx: loadAllSources/performSearch effects 56-74,76-117,120-135.
- app/(dashboard)/advanced/components/RebuildEmbeddings.tsx: inline `useMutation` 34-43 + `setInterval` poll 53.
- source/ChatPanel.tsx:349 (`chatApi.uploadMedia`); notebooks/NotebookWorkspaceProvider.tsx:256-261 (`notebooksApi.update().then()`); podcasts/EpisodeCard.tsx:183 (raw `fetch(directAudioUrl)`).
- **Extraction:** move into `lib/hooks/` TanStack hooks (useSource, useSourceInsights, useCreateInsight, useDeleteInsight, useRebuildEmbeddings w/ polling, useUploadMedia). **Do one file at a time, verify each.** (GeneratePodcastDialog `chatApi.buildContext` used as queryFn is fine — report only.)

---

## Report-only / leave-alone (do NOT force)

- **api/auth.py double password check** — `PasswordAuthMiddleware.dispatch` (30-75) and `check_api_password` (82-114) implement the same bearer+password compare twice, but `check_api_password` appears **unused/dead**. Verify dead first → then it's a deletion, not an extraction.
- **api/upload_utils.py** — two drifted path-traversal guards (`generate_unique_filename` 40-46 vs `resolve_within` 91-94). Already the "good" extraction; unify carefully (symlink `!=` edge case).
- **Form-dialog scaffolding** (Create/Edit dialogs: CreateNotebookDialog, NoteEditorDialog, TransformationEditorDialog, EpisodeProfileFormDialog, SpeakerProfileFormDialog, AddSourceDialog, SaveToNotebooksDialog) — share useForm+zodResolver+reset-on-open, but bodies differ materially (wizard/fullscreen/field-arrays). HIGH risk, low confidence.
- **NotebookDeleteDialog** (radio-group source-action + preview fetch) and **EmbeddingModelChangeDialog** (two confirm paths) — policy-bearing, not plain confirms.
- **Broad query-invalidation sets** (~102 `invalidateQueries`) — intentional cache-coherence policy (documented frontend/CLAUDE.md "broad vs scoped").
- **`classify_error` vs `connection_tester._normalize_error_message`** — overlap, but different surfaces (workflow exceptions vs UI connection test); merging couples two policies.
- **auth-store.ts bootstrap `fetch`** (40,83,86,175,178) — intentionally can't depend on the authed apiClient (chicken-and-egg). LOW value.
- **Domain policy spotted (leave):** title fallbacks (`or "Untitled Session"`), default ordering (`updated desc`/`created desc`), async-vs-sync source-processing branch (sources_service.py:198-217), model-type pattern maps (model_discovery.py:36-154), TEST_MODELS/DEFAULT_TEST_VOICES (connection_tester.py:18,172), per-model graph-traversal query strings.
- **base.py `_load_from_db` unwrap ladder** (291-303) — same parsing as T3-c; report only.
- **migrate.py** — intentional sync `asyncio.run` shim over async_migrate.py.

---

## Recommended execution order

1. **Pure-mechanical Tier 1:** T1-a → T1-b → T1-d → T1-f → T1-g → T1-h (no behavior change, ~150+ sites).
2. **Resolve the decision gate**, then T1-c → T1-e.
3. **Tier 2**, resolving T2-c's 400/404 first; T2-e after the LOW-risk ones (raise/return semantics).
4. **Tier 3** last, per-file with verification; T3-g is the highest-risk and should be sliced one file at a time. Do T3-f before T2-i.
