# Claude Agent chat (your Claude subscription, no API key)

Open Notebook can route its **chat** to Claude using your **Claude Pro/Max subscription**
instead of an Anthropic API key. Claude runs as a full **agent** — it can use Bash, read/write
files, search/fetch the web — **plus** custom tools that read your Open Notebook data
(notebooks, sources, notes).

This works by riding on the **Claude Code CLI** that is already logged into your subscription
on this machine. No `ANTHROPIC_API_KEY` is involved.

> ⚠️ **Security — read this first.** The agent runs with `permission_mode="bypassPermissions"`,
> which means it executes tools (including **Bash** and file writes) **without asking**. It is a
> real agent on your machine, **not a sandbox**. The working directory
> (`~/open-notebook-agent-workspace` by default) is just where it starts — it is not a hard
> boundary. Only enable this on a machine you trust, for your own personal use.

---

## Why it must run from source

The published `lfnovo/open_notebook` Docker image does **not** contain this integration, and a
container could not reach your host's logged-in `claude` CLI anyway. Run Open Notebook **from
source** on the same machine where Claude Code is logged in.

---

## Prerequisites

- **Claude Code logged in** on this machine with a Pro/Max subscription. The `claude` binary is
  expected at `~/.claude/local/claude` (this is the default; override with `CLAUDE_AGENT_CLI_PATH`).
  Verify with `claude --version` and that you can run `claude` interactively.
- **[uv](https://docs.astral.sh/uv/)** (Python toolchain) — the backend runs via `uv run`.
- **Node.js** (for the Next.js frontend).
- **Docker** (for SurrealDB).

---

## Setup

### 1. Configure `.env`

Copy the example and adjust for a run-from-source setup:

```bash
cp .env.example .env
```

Then in `.env`:

- `SURREAL_URL=ws://localhost:8000/rpc` — from source, SurrealDB is on `localhost`, **not** the
  docker-internal `surrealdb` host.
- `OPEN_NOTEBOOK_ENCRYPTION_KEY=<any-strong-secret>` — required for credential storage (the Claude
  Agent model itself needs no key, but the app expects this set).
- Leave `OPEN_NOTEBOOK_PASSWORD` **unset** for a local single-user run (API auth is then disabled).
- You do **not** need `ANTHROPIC_API_KEY` (or any provider key) for the Claude Agent model.

Optional Claude Agent overrides (defaults shown):

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_AGENT_CLI_PATH` | `~/.claude/local/claude` | Path to the Claude Code CLI binary (not on `PATH` for subprocesses). |
| `CLAUDE_AGENT_CWD` | `~/open-notebook-agent-workspace` | Agent's working directory (created if missing). **Not a sandbox.** |
| `CLAUDE_AGENT_MODEL` | _(unset)_ | Pin a specific Claude model; unset follows the Claude Code default. |

### 2. Start the stack

```bash
make database     # SurrealDB in Docker (port 8000)
make api          # FastAPI backend (port 5055)
make worker       # surreal-commands worker (embeddings, etc.)
```

> `make start-all` is currently **broken** (it references a non-existent
> `docker-compose.dev.yml`). Use the individual targets above.

### 3. Register the Claude Agent model

Run once (from the repo root, so it can find `.env`):

```bash
uv run python scripts/register_claude_agent_model.py
```

This creates a `provider="claude_agent"` language model and sets it as your default **chat**,
**tools**, and **large-context** model. It is idempotent — safe to re-run.

### 4. Start the frontend and pick the model

```bash
make frontend     # Next.js UI on http://localhost:3000
```

Open <http://localhost:3000>, go to a notebook's chat panel, open the model picker (the Settings
icon), and select **claude-agent**. No frontend changes were needed — the picker lists every
`language` model automatically.

---

## What you can do in chat

- **Normal conversation** — replies come from Claude via your subscription.
- **Agent tools** — ask it to run a shell command, fetch a web page, etc. (full Claude Code toolset).
- **Your Open Notebook data** — ask things like *"list my notebooks"* or *"search my notes for X"*.
  Claude calls the in-process tools (`mcp__open_notebook__*`): `list_notebooks`, `get_notebook`,
  `list_sources`, `get_source`, `get_note`, `search`.

---

## How it works (brief)

- The chat graph node (`open_notebook/graphs/chat.py`) detects when the selected/default model's
  provider is the `claude_agent` sentinel and routes to `open_notebook/ai/claude_agent.py` instead
  of the normal Esperanto/LangChain path.
- The Agent SDK spawns the `claude` CLI (`cli_path`) which authenticates via your subscription.
- Open Notebook's system prompt (notebook context + citation rules) is **appended** to Claude
  Code's agent preset, so notebook context still applies.
- The conversation is re-sent as a flat transcript each turn (stateless — robust across restarts).

---

## Limitations (v1)

- **No streaming** — `/api/chat/execute` is blocking; long tool-running turns return when complete.
- **Stateless transcript** — SDK session-resume is not used yet.
- **Chat only** — the per-source chat (`source_chat`) is not wired to this path.
- **Not sandboxed** — see the security note at the top.

---

## Troubleshooting

- **No Claude responses / auth errors** — confirm `claude --version` works and you are logged in;
  check `CLAUDE_AGENT_CLI_PATH` points at the real binary.
- **"claude-agent" not in the picker** — re-run the register script; confirm
  `curl -s localhost:5055/api/models?type=language` includes a `"provider":"claude_agent"` record.
- **DB connection errors from source** — ensure `SURREAL_URL=ws://localhost:8000/rpc` (not
  `surrealdb:8000`) and that `make database` is running.
- **Standalone scripts can't see the DB** — run them from the repo root (or with
  `uv run --env-file .env ...`) so `.env` is loaded.
