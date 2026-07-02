# Resume Prompts — Codebase Readability Refactor

These prompts are **stateless and re-runnable**. Paste one into a fresh Claude Code chat (or the same chat after `/clear`). Each run reconstructs progress from the Status table in `coordinator.md` + `git log`, then continues from the next eligible chunk. Use the *same* prompt every time — first run or tenth.

**Rule of thumb:** when a chat's context gets long, `/clear` and paste the prompt again. Because status is written to `coordinator.md` after every chunk and each chunk is its own commit, nothing is lost.

---

## 1. BACKEND track (Chat 1)

```
Resume the BACKEND track of the codebase readability refactor.

1. Read .claude/plans/codebase-readability/coordinator.md (shared rules, decisions, Status table) and backend.md (my chunk specs + order).
2. Determine where I am: in the Status table find the backend chunks (IDs A1–A3, B1–B3, C1–C5) and pick the next one that is "not started" or "in progress", following backend.md's order (A1·A2·A3 → B1·B2·B3 → C1 → C5·C3·C4 → C2 last). Respect the phase chain: never start a B chunk until its A primitives exist, never split a file (C) until its dedup (B) landed. Cross-check git log so you don't redo a committed chunk.
3. Execute exactly that ONE chunk. Behavior-preserving only. Reuse the primitives listed in backend.md's "Reuse map" — do not reinvent.
4. Verify: uv run pytest tests/ and uv run mypy open_notebook/ api/ (and for a C-split, smoke-boot uv run uvicorn api.main:app --port 5055 and confirm /docs lists the same routes). Do not proceed if red — fix or report.
5. Commit just that chunk (one chunk = one commit; message like "refactor(be): A1 get_or_404 + ensure_prefix helpers"). I work on this branch/worktree; commit here.
6. Update the Status table in coordinator.md (set the chunk to "done", add a one-line changelog note if useful).
7. Then either continue to the next eligible backend chunk and repeat, or stop and tell me the next chunk if you think context is getting large. Always leave the Status table accurate before stopping.

Do NOT touch frontend/ — that's the other chat. Ask me before any human-gated or destructive step.
```

---

## 2. FRONTEND track (Chat 2)

```
Resume the FRONTEND track of the codebase readability refactor.

1. Read .claude/plans/codebase-readability/coordinator.md (shared rules, decisions, Status table) and frontend.md (my chunk specs + order).
2. Determine where I am: in the Status table find the frontend chunks (IDs A4–A6, B5–B9, C6–C9) and pick the next one that is "not started" or "in progress", following frontend.md's order (A4·A5·A6 → B5·B6·B7·B9 → B8 → C6 → C8·C9 → C7 last). Respect the phase chain: never start a B chunk until its A primitives exist, never split a file (C) until its dedup (B) landed. Cross-check git log so you don't redo a committed chunk.
3. Execute exactly that ONE chunk. Behavior-preserving only — do NOT convert fetch-in-useEffect to TanStack (that's deferred). Error helpers use getApiErrorMessage. Reuse the primitives in frontend.md's "Reuse map". Remember i18n translation keys for any new strings.
4. Verify: cd frontend && npx tsc --noEmit, then npm run lint and npm run test. For a C-split, sanity-check the affected screen renders identically. Do not proceed if red — fix or report.
5. Commit just that chunk (one chunk = one commit; message like "refactor(fe): A4 client get/post/put/del helpers"). I work on this branch/worktree; commit here.
6. Update the Status table in coordinator.md (set the chunk to "done", add a one-line changelog note if useful).
7. Then either continue to the next eligible frontend chunk and repeat, or stop and tell me the next chunk if context is getting large. Always leave the Status table accurate before stopping.

Do NOT touch api/ or open_notebook/ — that's the other chat. Ask me before any human-gated or destructive step.
```

---

## 3. STATUS check (either chat, read-only)

```
Read .claude/plans/codebase-readability/coordinator.md and report the Status table: which chunks are done, in progress, and what the next eligible chunk is for each track. Cross-check against git log. Do not make any changes.
```

---

## Notes
- **One chunk = one commit** keeps `git log` a reliable progress record even if the Status table ever drifts.
- If two chats share one branch+checkout they will clobber each other — run each track in its own git worktree or branch (see coordinator.md).
- When the last build-now chunk in a track lands, that track is done; when both tracks finish, archive this directory (move to `.claude/plans/archived/codebase-readability/`).