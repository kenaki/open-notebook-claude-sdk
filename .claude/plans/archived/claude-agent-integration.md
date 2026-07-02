# Claude Agent SDK chat integration — Feature Development Doc

> **Living master plan & single source of truth.** Written so a fresh, uncontextualized session can
> pick up any unstarted chunk, execute it, verify it, and mark it done — without the original
> conversation. Keep the Status table + Changelog current.
> **Location:** `.claude/plans/claude-agent-integration.md` while active → moved to
> `.claude/plans/archived/claude-agent-integration.md` once every chunk is done.

---

## SESSION HANDOFF — COMPLETE
**State (2026-06-21, final):** **All build-now chunks (0–5) are ☑ done & verified.** Backend module,
model registration + dev stack, chat-node hook, in-process MCP data tools, and end-to-end verify +
setup docs all landed. The human browser walkthrough was confirmed by the user, closing Chunk 5.
**This plan is complete and archived.** Deferred items (D1–D5) remain out of scope.
⚠️ Note: this integration was originally built/verified on the Mac (registered model
`model:q9itqn4k3m9zt77shisq`). The user has since migrated to the DGX Spark with a **fresh DB**, where
the registered model id differs and the CLI lives at `/home/itz_kenaki/.local/bin/claude`. Remaining
follow-on work (local AI / Ollama) lives in `DGX-SPARK-MIGRATION.md`, not here.

**To resume:** 1) read this whole file; 2) re-read the referenced files for the next chunk; 3) do the next
☐ chunk in order — **one chunk per session**; 4) at the end: verify → update Status + Changelog → announce
"✅ Chunk X complete — safe to clear context" → stop.

**Paste-able resume prompt (run in a fresh chat):**
> Continue the Claude Agent SDK chat integration. Read `.claude/plans/claude-agent-integration.md` in full,
> then implement the next unstarted chunk (one only), verify it, update the doc's Status table + Changelog,
> and tell me when it's safe to clear context. If that was the last build-now chunk, archive the doc per its
> Completion section. Work on the `claude-agent-integration` branch.

---

## How to use this document (read first, every session)
1. Reuse before create — this integration is deliberately a *small, surgical* set of additions plus **one**
   ~6-line hook in `graphs/chat.py`. Do not refactor the Esperanto/ModelManager path.
2. Never invent a value → put it in Open Questions and ask.
3. **Per-chunk workflow:** read referenced files → implement → verify → update Status + Changelog → note new
   Open Questions → **announce it's safe to clear context** → stop. **One chunk per session.**
4. Conventions: see "Conventions / gotchas" below (async-in-sync bridging, provider sentinel, cli_path).

### Context-clear checkpoints (one chunk per session)
Every chunk is a checkpoint. At the end of each: (1) verify, (2) mark ☑ + Changelog line, (3) record
decisions/Open Questions, (4) tell the user "✅ Chunk X complete and verified — safe to clear context.
Next: Chunk Y." then **stop**.

### Completion & archival
When the **final build-now chunk (Chunk 6) is ☑ done**: append a Changelog line ("All chunks complete —
archived 2026-..."), then **move this file** to `.claude/plans/archived/claude-agent-integration.md`
(`mkdir -p .claude/plans/archived && mv .claude/plans/claude-agent-integration.md .claude/plans/archived/`),
and tell the user the plan is complete and archived.

### Status table
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 0 | Dependency + subscription-auth spike | ☑ done | initial session | `claude-agent-sdk==0.2.106` added; auth via `cli_path` verified (cost ~$0.05/turn) |
| 1 | Claude Agent backend module | ☑ done | chunk1 / 2026-06-21 | `open_notebook/ai/claude_agent.py`; ruff+mypy clean; live AUTH_OK + bash-tool verify passed via Max-subscription auth |
| 2 | Register model + env config + dev bring-up | ☑ done | orchestrator / 2026-06-21 | `model:q9itqn4k3m9zt77shisq` registered as chat+tools+large-context default; dev stack up; UI-picker check folded into Chunk 5 |
| 3 | Hook interception into chat node | ☑ done | orchestrator / 2026-06-21 | `_generate_ai_message` branch in `chat.py`; live `CHAT_OK` + bash-tool `TOOLS_WORK` via `/api/chat/execute`; non-claude→False unit-verified |
| 4 | Open Notebook data tools (in-process MCP) | ☑ done | orchestrator / 2026-06-21 | 6 tools live via `claude_agent_tools.py`; DB-direct works on SDK loop (Q-tool-dbloop resolved); bash co-exists with the MCP allowlist |
| 5 | End-to-end verify + setup docs | ☑ done | orchestrator / 2026-06-21 | docs + README pointer landed; all three message types verified; browser walkthrough confirmed by user → plan complete & archived |
| D | Deferred items | ⊘ deferred | | session resume, streaming, source_chat, true sandbox, concurrency |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

### Changelog
- 2026-06-21 — Plan created. Chunk 0 done: branched `claude-agent-integration`, `uv add claude-agent-sdk`
  (v0.2.106), verified subscription auth through existing Claude Code login via `cli_path=~/.claude/local/claude`
  (test prompt returned `AUTH_OK`, `is_error=False`, ~$0.05).
- 2026-06-21 — Chunk 1 done (orchestrated, main tree): created `open_notebook/ai/claude_agent.py`
  (`_flatten` / `_run` / `_build_options` / `generate_with_claude_agent` / `is_claude_agent_selected` + the
  `CLAUDE_AGENT_*` constants). Spec honored exactly (bypassPermissions, preset+append system prompt, model
  omitted unless `CLAUDE_AGENT_MODEL` set, light imports, no ModelManager). Verify: `ruff` clean; mypy adds
  **0** errors (82-error/19-file baseline unchanged with vs without the file); **live** SDK calls returned an
  `AIMessage` `"AUTH_OK"` and a working bash-tool date reply via `cli_path` Max-subscription auth. Seam left
  for Chunk 4: `_build_options(mcp_servers=…)` already wires `mcp_servers` + `allowed_tools=["mcp__open_notebook__*"]`
  when a server dict is passed (server itself not built yet).
- 2026-06-21 — Chunk 2 done (orchestrated, main tree). Created idempotent `scripts/register_claude_agent_model.py`
  (self-loads `.env` via python-dotenv; SELECT-then-create; sets chat/tools/large-context defaults), extended
  `.env.example` with the `CLAUDE_AGENT_*` block + "no ANTHROPIC_API_KEY" note, and wrote a local **uncommitted**
  `.env` (gitignored; `SURREAL_URL=ws://localhost:8000/rpc`, generated encryption key, **auth OFF** via unset
  `OPEN_NOTEBOOK_PASSWORD`). Brought up the dev stack: SurrealDB (docker, DB already at v15), API `:5055`
  (background, `/health` healthy), worker (background, 13 commands, live). Ran the script →
  `model:q9itqn4k3m9zt77shisq`. Verify: `GET /api/models?type=language` returns **exactly one** `claude_agent`
  model; `GET /api/models/defaults` shows chat/tools/large_context all = that id; re-run = idempotent (no
  duplicate); ruff clean; mypy adds 0 errors (baseline-only). UI-picker confirmation deferred to Chunk 5 (frontend
  not started; plan made that check conditional on the frontend being up).
- 2026-06-21 — Chunk 3 done (orchestrated, main tree). Added module-level `async _generate_ai_message(model_id,
  payload, config)` to `graphs/chat.py` and routed the **existing** event-loop bridging through it (ThreadPool +
  `asyncio.run` branches now return the `AIMessage` directly; `clean_thinking_content`/`extract_text_content`/
  `classify_error` unchanged). When `is_claude_agent_selected(model_id)` → `generate_with_claude_agent(payload,
  thread_id=config…thread_id)`, else the original `provision_langchain_model(...).invoke(payload)`. Strict
  prepend — the non-Claude path is byte-for-byte unchanged. Verify: ruff clean; mypy baseline-only; **unit** (3×)
  default→True / claude_agent→True / valid-non-claude(openai)→False / missing→False; **live** via
  `POST /api/chat/execute` (default model, API hot-reloaded) → plain `CHAT_OK` and bash-tool turn returned
  `TOOLS_WORK`, both 200 OK. Live non-Claude chat not run (no other credential configured — user chose the
  structural+unit check; Decision: subscription-only setup retained). Orphan verify notebook cleaned from shared DB.
- 2026-06-21 — Chunk 4 done (orchestrated, main tree). Created `open_notebook/ai/claude_agent_tools.py` with 6
  `@tool` async fns (`list_notebooks`, `get_notebook`, `list_sources`, `get_source`, `get_note`, `search`) bundled
  via `create_sdk_mcp_server(name="open_notebook")`; each returns `{"content":[{"type":"text",...}]}` with embeddings
  stripped and strings capped (`_MAX_STR=4000`). `generate_with_claude_agent` now builds the server and passes
  `mcp_servers={"open_notebook": …}` into `_build_options` (which adds `allowed_tools=["mcp__open_notebook__*"]`);
  the import is **lazy** to keep `claude_agent.py` import-light. Verify: ruff clean; mypy baseline-only; init message
  shows all 6 `mcp__open_notebook__*` tools **and** `bash` still present (built-ins survive the MCP allowlist under
  `bypassPermissions`); **live** through the real chat node (`/api/chat/execute`) — "list my notebooks" → real
  `Agent Tools Test`, "search Testlandia" → `Testville` with note citation. Validated DB access from a tool callback
  on the SDK loop in BOTH the main-thread loop and the node's thread+new-loop path. Test data created + cleaned.
- 2026-06-21 — Chunk 5 in progress (orchestrated). Wrote `docs/claude-agent.md` (prereqs, run-from-source,
  `.env` + `CLAUDE_AGENT_*`, register script, picker selection, **security note** that bypassPermissions = full
  machine access / not a sandbox, no-API-key/subscription explanation, limitations, troubleshooting) and added a
  README pointer under "More Installation Options". Closed the last functional gap at API level: **web-tool**
  message via `/api/chat/execute` (WebFetch `https://example.com` → "Example Domain"). So all three message types
  are proven through the chat node (normal=Chunk 3, web=here, ON-data=Chunk 4). Ran `npm install` (frontend) and
  started `make frontend` → Next.js live on `:3000` (proxies `/api/*` → :5055). **Remaining:** human browser
  walkthrough (pick `claude-agent` in the picker; send normal/web/ON-data) before ☑ + archival. NOTE: plan prose
  says "Chunk 6" in places — typo; **Chunk 5 is the final build-now chunk** (chunks are 0–5 + deferred D).
- 2026-06-21 — Chunk 5 done & **all chunks complete — archived 2026-06-21**. User confirmed the browser
  walkthrough (picked `claude-agent` in the chat model picker; normal, web-tool, and ON-data messages all
  returned Claude responses). Plan moved to `.claude/plans/archived/claude-agent-integration.md`. Deferred
  items D1–D5 left for future work; local-AI follow-up tracked in `DGX-SPARK-MIGRATION.md`.

---

## Context — why
**Goal:** Let the user talk to Claude *inside Open Notebook's chat* using their **Claude Pro/Max subscription
(no Anthropic API key)**, with Claude having **full agent capabilities** (Bash, file read/write/edit, web
search/fetch, glob/grep) **plus custom tools to read their Open Notebook data**.

**Why this shape:**
- Open Notebook's normal chat path goes user → `POST /chat/execute` → LangGraph `chat.py` node →
  `provision_langchain_model()` (Esperanto → LangChain `BaseChatModel`) → `model.invoke()`. We intercept at the
  node: when the selected model's provider is the sentinel `claude_agent`, route to the Agent SDK instead.
- **No frontend changes** are needed: the chat model picker lists every `GET /models` record where
  `type === 'language'` (provider is shown as a label, never filtered). A `provider="claude_agent"` model
  appears in the dropdown automatically.
- **Auth without API key is supported for personal use.** The Agent SDK rides on the already-authenticated
  Claude Code CLI on this Mac (the same login powering this session). The ToS restriction the research surfaced
  is about *reselling* claude.ai login to *other* users — not a single user using their own subscription.
- **Must run from source**, not the published `lfnovo/open_notebook` Docker image (that image won't contain
  this code). Dev stack: `make database` (SurrealDB in Docker) + `make api` + `make worker` + `make frontend`
  (Next.js UI on :3000, API on :5055).

**In scope (build now):** Chunks 1–5 (backend module, registration, node hook, ON-data tools, verify+docs).
**Deferred:** see Deferred section.

## Decisions log
| # | Question | Decision |
|--:|----------|----------|
| 1 | Where does the modified backend run? | **From source on this Mac** (reuses existing Claude Code login; zero auth setup). SurrealDB stays in Docker. |
| 2 | How much capability does Claude get? | **Full agent** — Bash, file read/write/edit, web, glob/grep, via `permission_mode="bypassPermissions"`. |
| 3 | Default Claude model? | **Follow Claude Code default** — do not pin `options.model` (leave `None`). Overridable via env `CLAUDE_AGENT_MODEL`. |
| 4 | Build scope: pass-through vs ON-data tools? | **Both** — pass-through agent (Chunks 1–3) **and** custom SDK tools exposing notebooks/sources/notes (Chunk 4). |
| 5 | Agent default working directory? | **Dedicated workspace folder** `~/open-notebook-agent-workspace` (created if missing). Overridable via env `CLAUDE_AGENT_CWD`. NOTE: with full Bash + bypass this is the default work area, **not** a hard sandbox. |
| 6 | Conversation continuity? | **Stateless flatten** for v1 (re-send transcript each turn; robust to restarts). SDK session-resume is deferred. |
| 7 | Auth mechanism / CLI discovery? | Subscription via Claude Code login. `claude` is NOT on PATH for spawned subprocesses → pin `cli_path=~/.claude/local/claude` (env `CLAUDE_AGENT_CLI_PATH`). |
| 8 | System prompt handling? | Keep Claude Code's agent system prompt and **append** ON's `chat/system` render via `SystemPromptPreset` (`{"type":"preset","preset":"claude_code","append": <on_system>}`) so notebook context/citation rules still apply without losing agent scaffolding. |
| 9 | (Q-defaults-extra) Set tools/large-context defaults too? | **Yes** (user choice 2026-06-21): Claude Agent = `default_chat_model` **+** `default_tools_model` **+** `large_context_model`. `default_transformation_model` left null (falls back to chat anyway). |
| 10 | (Q-tool-dbloop) DB access from in-process MCP tool callbacks? | **DB-direct works — no REST fallback.** `repo_query` opens a fresh `AsyncSurreal` connection per call on the current loop (no shared/loop-bound connection), so tool callbacks on the SDK loop query SurrealDB fine. Verified live in both the main-thread loop and the node's thread+new-loop path. |

## Conventions / gotchas
- **Async-in-sync bridging:** `chat.py`'s node is a *sync* LangGraph node that runs async work in a fresh event
  loop (it already does this for `provision_langchain_model`). The SDK is async → reuse the **same** bridging
  (try `asyncio.get_running_loop()`; if running, run in a `ThreadPoolExecutor` with a new loop; else
  `asyncio.run`). Do the claude-agent call inside that same async helper — don't add a second loop.
- **Provider sentinel:** DB stores provider with underscores; `ModelManager` converts `_`→`-` before calling
  Esperanto. Our sentinel `claude_agent` must be **intercepted before** `provision_langchain_model`/Esperanto is
  ever reached (Esperanto has no `claude-agent` provider and would error). Detection = load the `Model` record and
  check `model.provider == "claude_agent"`; never route it through ModelManager.
- **`cli_path` is required** (claude not on PATH for subprocesses). Default `~/.claude/local/claude`.
- **`bypassPermissions`** is mandatory for headless (no interactive approval prompts to hang on).
- **Return contract:** the node expects an object with `.content` and supporting `.model_copy(update=...)` — i.e.
  a LangChain `AIMessage`. The backend must return an `AIMessage(content=<text>)`.
- **Thinking tags:** node already calls `clean_thinking_content()`; we extract only `TextBlock.text` (skip
  `ThinkingBlock`) so thinking never reaches the transcript anyway.
- **Lint/type:** `make ruff` (E,F,I; E501 ignored) and `make lint` (mypy; excludes `pages.*`).
  ⚠️ **Verified gotchas (Chunk 1):** ruff/mypy live under the **dev EXTRA**, not a dependency group — run
  `uv sync --extra dev` to get them (`uv sync --group dev` is a no-op). `make ruff` calls a bare `ruff` not on
  PATH and errors ("No such file or directory"); use `uv run ruff check .` and `make lint`/`uv run mypy …`
  instead. **Baseline = 82 mypy errors / 19 files** (pre-existing in `tests/`, `commands/`, `api/`, etc.) — a
  changed file is clean iff it adds nothing to that count.
- **Persistence (where "memory" lives — NOT in Docker, on disk):**
  - SurrealDB data (notebooks, sources, notes, model/credential records) → host folder `./surreal_data/mydatabase.db`
    (bind-mounted by `docker-compose.yml`). `make database` (= `docker compose up -d surrealdb`) reuses this exact volume.
  - Chat history / LangGraph checkpoints ("conversation memory") → `DATA_FOLDER/sqlite-db/checkpoints.sqlite` where
    `DATA_FOLDER="./data"` (relative to CWD, see `open_notebook/config.py`). **In-container** that resolves to
    `./notebook_data/sqlite-db/`; **from source** it resolves to `<repo>/data/sqlite-db/` — a *different* path. Existing
    container chat threads won't carry over to the source run unless that file is copied (none exist yet, so n/a).
  - The Claude Agent's per-thread memory = that same checkpoint transcript, re-sent each turn (stateless flatten) →
    persists across restarts, independent of the SDK.
- **Dev bring-up gotchas (verified):**
  - ⚠️ `make start-all` is **broken** — it calls `docker compose -f docker-compose.dev.yml ...` but `docker-compose.dev.yml`
    does NOT exist in this repo (only `docker-compose.yml`). Use individual targets: `make database`, `make api`
    (= `uv run --env-file .env run_api.py`), `make worker`, `make frontend` (Next.js on :3000).
  - ⚠️ From source, set `.env` `SURREAL_URL=ws://localhost:8000/rpc` (NOT `surrealdb:8000` — that host only resolves
    inside Docker's network). Keep `SURREAL_NAMESPACE=open_notebook` / `SURREAL_DATABASE=open_notebook` to share the same
    data the published-image stack used. Creds `root`/`root`.
  - ⚠️ **API routes are mounted under the `/api` prefix** (`api/main.py`: `include_router(models.router, prefix="/api")`).
    So the real verify URLs are `GET /api/models?type=language` and `GET /api/models/defaults` — **not** the
    un-prefixed paths shown in some chunk Verify blocks. Chat execute is likewise `POST /api/chat/...`.
  - ✅ **Auth is OFF when `OPEN_NOTEBOOK_PASSWORD` is unset** (`api/auth.py`: `if not self.password: return call_next`).
    Local `.env` leaves it unset, so no `Authorization` header is needed for curl/UI. (The "default password" note in
    `api/CLAUDE.md` is stale.)
  - **Current dev stack (this run):** SurrealDB via `docker compose up -d surrealdb`; API + worker launched as
    background processes (`uv run --env-file .env run_api.py` / `… surreal-commands-worker --import-modules commands`),
    logs at `/tmp/on_api.log` + `/tmp/on_worker.log`. Registered model id = `model:q9itqn4k3m9zt77shisq`.
  - ⚠️ **Standalone verify scripts must load the env.** `load_dotenv()` (no args) searches upward from the
    *script's own directory*, so a script in `/tmp` never finds the repo `.env` → `SURREAL_*` unset → the DB
    client silently connects to an empty/default namespace (namespace/database = None) and reads return nothing
    (e.g. `default_chat_model` looks like `None`, giving a **false** "claude not selected"). Run verify scripts
    from the repo root **and/or** with `uv run --env-file .env python <script>`. The API/worker already use
    `--env-file .env` so they're unaffected. Symptom seen in Chunk 3: `is_claude_agent_selected(None)` flipped
    False purely from where the temp script lived — a harness artifact, not a code bug.

---

## Chunks

### Chunk 1 — Claude Agent backend module
- **Goal:** A self-contained module that turns a LangChain chat `payload` into a Claude-Agent-SDK call and returns
  an `AIMessage`. No DB, no graph coupling — standalone-testable.
- **Read first:** `open_notebook/graphs/chat.py` (lines 30–85, the payload/return contract);
  `open_notebook/exceptions.py` (OpenNotebookError subclasses); `/tmp/cc_sdk_test.py` is the proven reference call
  (may have been deleted — the working pattern is reproduced under "confirmed APIs" below).
- **Spec / exact values:**
  - New file: `open_notebook/ai/claude_agent.py`.
  - Constants/env (with defaults):
    - `CLAUDE_AGENT_PROVIDER = "claude_agent"`
    - `CLAUDE_AGENT_CLI_PATH = os.environ.get("CLAUDE_AGENT_CLI_PATH", os.path.expanduser("~/.claude/local/claude"))`
    - `CLAUDE_AGENT_CWD = os.environ.get("CLAUDE_AGENT_CWD", os.path.expanduser("~/open-notebook-agent-workspace"))`
    - `CLAUDE_AGENT_MODEL = os.environ.get("CLAUDE_AGENT_MODEL")  # None ⇒ follow CC default`
  - `def _build_options(system_prompt, mcp_servers=None) -> ClaudeAgentOptions` with:
    `permission_mode="bypassPermissions"`, `cli_path=...`, `cwd=...` (create dir with `os.makedirs(..., exist_ok=True)`),
    `system_prompt={"type":"preset","preset":"claude_code","append": system_prompt}`, `model=CLAUDE_AGENT_MODEL or` omit,
    and (Chunk 4 will add `mcp_servers=` + `allowed_tools=["mcp__open_notebook__*"]`).
  - `def _flatten(payload) -> tuple[str, str]`: split `payload` (list of LangChain messages). The first
    `SystemMessage` → `system_prompt` str (its `.content`). Remaining `HumanMessage`/`AIMessage` → a transcript
    string: `"User: <text>\n\nAssistant: <text>\n\n..."` ending with the latest `User:` turn. Use
    `extract_text_content` from `open_notebook.utils.text_utils` to normalize `.content`.
  - `async def _run(prompt, options) -> str`: iterate `query(prompt=prompt, options=options)`; collect
    `TextBlock.text` from `AssistantMessage.content`; capture `ResultMessage.result`/`.is_error`/`.errors`;
    if `AssistantMessage.error` or `ResultMessage.is_error` → raise an OpenNotebookError subclass
    (`AuthenticationError` for `"authentication_failed"`, `RateLimitError` for `"rate_limit"`, else
    `ExternalServiceError`). Return `ResultMessage.result` if non-empty else the joined assistant texts.
  - `async def generate_with_claude_agent(payload, thread_id=None) -> AIMessage`: `system, transcript = _flatten(payload)`;
    `text = await _run(transcript, _build_options(system))`; `return AIMessage(content=text)`.
    (`thread_id` is unused in v1 — reserved for deferred session-resume.)
  - `async def is_claude_agent_selected(model_id) -> bool`: resolve the effective model id (if `model_id` falsy,
    read `DefaultModels.get_instance().default_chat_model`); if still falsy return False; `Model.get(effective_id)`
    inside try/except; return `model.provider == CLAUDE_AGENT_PROVIDER`. Must NOT call `ModelManager.get_model`.
- **Reuse:** `claude_agent_sdk.{query, ClaudeAgentOptions, AssistantMessage, ResultMessage, SystemMessage, TextBlock}`;
  `langchain_core.messages.AIMessage`; `open_notebook.utils.text_utils.extract_text_content`;
  `open_notebook.exceptions.*`; `open_notebook.ai.models.{Model, DefaultModels}`.
- **Steps:** create the module; keep it import-light (don't import graph/DB at module top beyond models).
- **Verify (no DB needed):** write a temp script that builds a fake `payload`
  (`[SystemMessage("You are concise."), HumanMessage("Reply exactly: AUTH_OK")]`) and
  `asyncio.run(generate_with_claude_agent(payload))`; assert it returns an `AIMessage` containing `AUTH_OK`.
  Run `uv run python <script>`. Then a second call with `HumanMessage("Use a tool to print today's date via bash")`
  to confirm tool use works under bypass. `make ruff` + `make lint`.

### Chunk 2 — Register model + env config + dev bring-up
- **Goal:** Make "Claude Agent" a selectable language model and set it as the default chat model; document env vars;
  bring the dev stack up (needed to verify Chunks 2–5).
- **Read first:** `open_notebook/ai/models.py` (`Model`, `DefaultModels`, `.save()`, `.update()`, `get_instance()`);
  `api/routers/models.py` (`create_model` shows the duplicate-check pattern); `.env.example`; `README.dev.md`
  (Make targets); `Makefile` (`database`, `api`, `worker`, `frontend`, `start-all`).
- **Spec / exact values:**
  - New file: `scripts/register_claude_agent_model.py` — **idempotent**:
    - Query `SELECT * FROM model WHERE provider='claude_agent' AND type='language' LIMIT 1`. If absent,
      `Model(name="claude-agent", provider="claude_agent", type="language").save()`.
    - Load `DefaultModels.get_instance()`, set `default_chat_model = <that model id>`, `await defaults.update()`.
      (Optionally also set `default_tools_model`/`large_context_model` to it — ask if unsure; default: only chat.)
    - Print the resulting model id + confirmation. Must be runnable via `uv run python scripts/register_claude_agent_model.py`.
  - `.env.example` additions (documented, commented): `CLAUDE_AGENT_CLI_PATH`, `CLAUDE_AGENT_CWD`, `CLAUDE_AGENT_MODEL`,
    and a note that no `ANTHROPIC_API_KEY` is required for the Claude Agent model.
  - Local `.env`: copy from `.env.example`; set `SURREAL_*` for the dev DB and `OPEN_NOTEBOOK_ENCRYPTION_KEY`
    (any non-default secret) and `OPEN_NOTEBOOK_PASSWORD` if needed. **Do not commit `.env`.**
- **Reuse:** existing `Model`/`DefaultModels` domain methods; `repo_query`.
- **Steps:** write script; extend `.env.example`; create `.env`; `make database`; `make api`; `make worker`; run the
  script; (optionally) `make frontend`.
- **Verify:** `curl -s localhost:5055/models?type=language` (with auth header if middleware on) returns a record with
  `provider":"claude_agent"`; `curl -s localhost:5055/models/defaults` shows `default_chat_model` = that id. Confirm it
  appears in the UI model picker (Settings icon in the chat panel) if frontend is up. `make ruff`.

### Chunk 3 — Hook interception into the chat node
- **Goal:** Route chat to the Agent SDK when the selected/default model is `claude_agent`; otherwise unchanged.
- **Read first:** `open_notebook/graphs/chat.py` (whole file, esp. lines 30–85);
  `open_notebook/ai/claude_agent.py` (from Chunk 1).
- **Spec / exact values:** inside `call_model_with_messages`, after computing `model_id` (line ~34) and building
  `payload`, branch **before** provisioning. Implement a single async helper `_generate_ai_message(model_id, payload, config)`
  that: `if await is_claude_agent_selected(model_id): return await generate_with_claude_agent(payload, thread_id=config.get("configurable",{}).get("thread_id"))`
  else falls back to the existing `model = await provision_langchain_model(str(payload), model_id, "chat", max_tokens=8192); return model.invoke(payload)`.
  Run `_generate_ai_message` through the **existing** event-loop bridging (the try/except around
  `run_in_new_loop`). Keep `clean_thinking_content` + `extract_text_content` + `classify_error` exactly as-is.
- **Reuse:** the existing loop-bridging block; do not introduce a new threading helper.
- **Steps:** refactor the loop-bridged section to call `_generate_ai_message`; add the import; keep the diff minimal.
- **Verify:** with the dev stack up and the Claude Agent model set as default (Chunk 2): create a notebook + chat
  session in the UI (or via API), `POST /chat/execute` with a message → response comes back from Claude. Try a
  message that triggers a tool ("search the web for X"). Confirm a non-Claude model still works (switch model in the
  picker). `make ruff` + `make lint`.

### Chunk 4 — Open Notebook data tools (in-process MCP)
- **Goal:** Give Claude custom tools to read the user's Open Notebook data during chat.
- **Read first:** `open_notebook/domain/notebook.py` (`Notebook`, `Source`, `Note`, `get_sources`, `get_notes`,
  `vector_search` / search helpers, `get_context`); `open_notebook/ai/claude_agent.py`; SDK `create_sdk_mcp_server`
  + `tool` (see confirmed APIs).
- **Spec / exact values:**
  - New file: `open_notebook/ai/claude_agent_tools.py` defining `@tool(...)` async functions, e.g.:
    `list_notebooks()`, `get_notebook(notebook_id)`, `list_sources(notebook_id)`, `get_source(source_id)`,
    `search(query, limit)` (vector/text search over sources+notes), `get_note(note_id)`. Each returns
    `{"content":[{"type":"text","text": <serialized>}]}`. Build the server with
    `create_sdk_mcp_server(name="open_notebook", version="1.0.0", tools=[...])`.
  - In `claude_agent.py` `_build_options`: pass `mcp_servers={"open_notebook": <server>}` and
    `allowed_tools=["mcp__open_notebook__*"]` (built-in tools stay available via bypass).
- **KNOWN RISK to validate first:** the in-process MCP tool callbacks run on the SDK's event loop, which here is the
  *fresh loop* created by the node's bridging. SurrealDB's async client/connection may be loop-bound — calling
  `repo_query` from inside a tool callback on a different loop than the one that opened the connection can fail.
  **Validate** with one tool (`list_notebooks`) before building the rest; if it fails, options: (a) open a fresh DB
  connection inside the tool, (b) marshal DB calls onto the connection's loop, or (c) make tools call the local REST
  API (`http://localhost:5055`) instead of the DB directly. Pick the simplest that works and record it as a Decision.
- **Reuse:** existing domain query methods; do not duplicate search logic.
- **Steps:** implement `list_notebooks` + wire into options → verify the loop/DB risk → implement the rest → verify.
- **Verify:** in chat, ask "list my notebooks" / "summarize the sources in notebook X" → Claude calls the tool and
  answers from real data. Confirm `mcp__open_notebook__*` tools show up in the SDK `init` message. `make ruff` + `make lint`.

### Chunk 5 — End-to-end verify + setup docs
- **Goal:** Confirm the whole flow through the real UI and write durable setup docs.
- **Read first:** `README.dev.md`; `docs/` layout; this doc.
- **Spec / exact values:** new `docs/claude-agent.md` covering: prerequisites (Claude Code logged in, Node, uv),
  run-from-source steps (`make database/api/worker/frontend`), `.env` + the `CLAUDE_AGENT_*` env vars, running
  `scripts/register_claude_agent_model.py`, selecting "Claude Agent" in the chat picker, the security note
  (bypassPermissions = full machine access; not a sandbox), and the no-API-key/subscription explanation.
- **Steps:** full clean run-through from a fresh `make start-all`; fix any gaps found; write the doc; update README
  pointer if appropriate.
- **Verify:** from the browser at `localhost:3000`: pick Claude Agent, send a normal message, a web-tool message, and
  an ON-data-tool message; all succeed. Capture the steps in `docs/claude-agent.md`. Then perform **archival** (this is
  the last build-now chunk).

### Deferred (documented, not built now)
- **D1 — SDK session resume** ⊘ Replace stateless flatten with `options.resume=<session_id>` keyed by `thread_id`
  (persist the `ResultMessage.session_id`); only send the latest turn. Needs a session-id store + restart fallback.
- **D2 — Streaming responses** ⊘ `/chat/execute` is blocking; add SSE so long tool-running turns stream. Touches API +
  frontend; larger.
- **D3 — Apply to `source_chat.py`** ⊘ Same hook for the per-source chat graph/endpoint.
- **D4 — Real sandboxing** ⊘ bypassPermissions + Bash = full machine access. A true boundary needs SDK `sandbox`
  settings or a container; out of scope for personal local use.
- **D5 — Concurrency/limits hardening** ⊘ per-request timeouts, `max_turns`, `max_budget_usd`, isolation under
  concurrent chats.

## Verification (end-to-end)
- Lint/type each chunk: `make ruff` then `make lint` (ignore pre-existing baseline noise unrelated to changed files).
- Dev stack: `make database` (or reuse running SurrealDB), `make api`, `make worker`, `make frontend`.
- Functional: select "Claude Agent" in the chat model picker → (1) plain reply, (2) web/bash tool use, (3) "list my
  notebooks" (ON-data tool). All return Claude responses; non-Claude models still work when selected.
- Auth sanity: no `ANTHROPIC_API_KEY` set and Claude Agent chat still works (subscription via Claude Code login).

## Open Questions (surface to human; don't guess)
- ~~**Q-defaults-extra**~~ — ✅ RESOLVED 2026-06-21 (Decision #9): set Claude Agent as chat **+** tools **+**
  large-context default.
- ~~**Q-tool-dbloop**~~ — ✅ RESOLVED 2026-06-21 (Decision #10): DB-direct works on the SDK loop (fresh
  per-call connection); no REST fallback needed. Validated live, both loop contexts.
- **Q-context-passthrough** — Keep injecting ON notebook `context` (selected sources/notes) into the appended system
  prompt? **Default: yes** (the existing `chat/system.jinja` already does it; harmless and useful).

## Reference index
- **Files to add:** `open_notebook/ai/claude_agent.py` (C1), `scripts/register_claude_agent_model.py` (C2),
  `open_notebook/ai/claude_agent_tools.py` (C4), `docs/claude-agent.md` (C5).
- **Files to edit:** `open_notebook/graphs/chat.py` (C3, ~6 lines), `.env.example` (C2), `pyproject.toml`/`uv.lock`
  (C0, done).
- **Key existing code:**
  - Chat node: `open_notebook/graphs/chat.py:30` `call_model_with_messages` — payload `[SystemMessage]+messages`;
    `model_id = config["configurable"]["model_id"] or state["model_override"]`; returns `{"messages": AIMessage}`.
  - Provision path (leave alone): `open_notebook/ai/provision.py:10` `provision_langchain_model`.
  - Models: `open_notebook/ai/models.py` — `Model(name,provider,type).save()`, `Model.get(id).provider`,
    `DefaultModels.get_instance()/.update()`, `default_chat_model`.
  - Chat API: `api/routers/chat.py:330` `POST /chat/execute` (passes `model_id` into graph config).
  - Frontend (no changes): `frontend/src/components/source/ModelSelector.tsx` filters `type==='language'` only.
  - System prompt: `prompts/chat/system.jinja` (notebook context + citation rules).
- **Deps available:** `claude-agent-sdk==0.2.106` (installed), `langchain_core`, `loguru`, SurrealDB driver.
- **Toolchain:** Python 3.12, Node v24, `claude` CLI 2.1.185 at `~/.claude/local/claude` (logged in), uv 0.11.20.

### Post-exploration refinements (confirmed APIs)
- **Auth (verified):** subscription via existing Claude Code login. `claude` is **not** on PATH for spawned
  subprocesses → must pass `cli_path="~/.claude/local/claude"`. Verified call returned `is_error=False`, ~$0.05/turn.
- **`query`:** `query(*, prompt: str | AsyncIterable, options: ClaudeAgentOptions|None=None, transport=None)` →
  async iterator of `SystemMessage | AssistantMessage | ResultMessage | UserMessage | StreamEvent | RateLimitEvent`.
- **`ClaudeAgentOptions`** (relevant fields): `system_prompt` (str | `SystemPromptPreset` | `SystemPromptFile` | None),
  `allowed_tools: list[str]`, `disallowed_tools: list[str]`, `permission_mode` ∈
  `{default, acceptEdits, plan, bypassPermissions, dontAsk, auto}`, `model: str|None`, `fallback_model`, `cwd`,
  `cli_path`, `mcp_servers: dict[str, McpServerConfig]`, `max_turns`, `max_budget_usd`, `resume`, `session_id`,
  `continue_conversation`, `add_dirs`, `include_partial_messages`, `setting_sources`.
- **`SystemPromptPreset`** = `{"type":"preset","preset":"claude_code","append": <str>, "exclude_dynamic_sections": <bool>}`.
- **Messages/blocks:** `AssistantMessage(content=[blocks], model, error: Optional[Literal['authentication_failed',
  'billing_error','rate_limit','invalid_request','server_error','unknown']], session_id, ...)`;
  `TextBlock(text)`; `ThinkingBlock(thinking, signature)`; `ResultMessage(result: str|None, is_error, session_id,
  subtype, errors: list[str]|None, total_cost_usd, num_turns, api_error_status, structured_output)`;
  `SystemMessage(subtype, data)` (init message exposes `tools`, `mcp_servers`, `model`, `session_id`).
- **Custom tools:** `@tool(name, description, {param: type})` async fn returning
  `{"content":[{"type":"text","text": ...}]}`; bundle via `create_sdk_mcp_server(name=..., version=..., tools=[...])`;
  reference as `mcp__<server_name>__<tool_name>` (allow with `["mcp__open_notebook__*"]`).
- **Proven reference call (Chunk 1 mirrors this):**
  ```python
  opts = ClaudeAgentOptions(
      permission_mode="bypassPermissions",
      cli_path=os.path.expanduser("~/.claude/local/claude"),
      cwd=os.path.expanduser("~/open-notebook-agent-workspace"),
      system_prompt={"type":"preset","preset":"claude_code","append": on_system_prompt},
      # model omitted ⇒ follow Claude Code default
  )
  async for msg in query(prompt=transcript, options=opts):
      if isinstance(msg, AssistantMessage):
          for b in msg.content:
              if isinstance(b, TextBlock): texts.append(b.text)
      elif isinstance(msg, ResultMessage):
          final = msg.result
  ```
