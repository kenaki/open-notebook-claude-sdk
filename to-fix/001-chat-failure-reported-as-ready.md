---
id: 001
title: Failed chat jobs are silently reported as "ready" with an empty reply
type: bug
severity: high
status: open
area: chat jobs / background job polling (frontend/src/lib/hooks/use-jobs-poller.ts)
created: 2026-07-03
---

# 001 · Failed chat jobs are silently reported as "ready" with an empty reply

## Summary
A side chat using the local "DeepSeek V4" model failed at the infra layer (ds4-activator refused to wake the backend — not enough free GPU memory) and the backend correctly caught, classified, logged, and marked the job `failed` with a real error message. None of that ever reaches the user: the frontend's job poller only polls the *active* jobs endpoint, so a job that fails between two polls simply disappears from that list — and the poller's disappearance handler assumes disappearance means success. The chat turn ends with a false "chat ready" toast and a permanently empty assistant message, with the real error never surfaced. This is not ds4-specific or side-chat-specific — it reproduces for any chat job (main or side, any provider) that fails fast enough to skip being observed in a non-terminal state.

## What was reported
> Side chat scoped to a passage, model "Deek Seek V4" (DeepSeek V4 via local ds4), sent "When do you think I should do the math?" — reply never appeared, just two spinner/retry icons with no text and a disabled composer. User restarted [services] twice; second time the chat reported "ready" but the assistant turn was still completely empty, with no error shown anywhere. Question raised: why can't error messages be seen at all?

## Findings

**Confirmed trigger (this occurrence):** `journalctl --user -u ds4-activator` shows repeated admission-control refusals right when the user sent the message:
```
ds4-activator: ERROR: only 97010MB free (< 105000MB) after eviction; refusing ds4 wake
```
`ds4-activator.py:104-108` (`start_backend_and_wait`) refuses to start the ds4 backend when there isn't enough free unified memory after evicting heavy Ollama models, and correctly returns a real error to the caller: `ds4-activator.py:339-346` sends **HTTP 502** with `{"error": {"message": "ds4 backend did not become ready in time", ...}}`. The proxy layer behaves correctly — this is not the bug.

**Backend handles it correctly too.** `open_notebook/graphs/chat.py:145-193` (`call_model_with_messages`) catches the exception and runs it through `open_notebook/utils/error_classifier.py:63-68`, which matches `"502"` → `ExternalServiceError` ("The AI provider is temporarily unavailable..."). This propagates out of the LangGraph invocation into `commands/chat_commands.py:153-161`, which logs via loguru (`logger.error(f"chat_completion failed for {full_session_id}: {e}")`) and `raise RuntimeError(user_message) from e`. `surreal-commands` marks the job **`failed`** with that message attached. Verified this is a real, populated `error_message` on the job row, not a swallowed exception.

**The bug is entirely in the frontend poller.** Chat answers are not streamed via SSE — they're delivered by polling `GET /commands/jobs?status_filter=active`, which `api/command_service.py:87-88` expands to `status IN ('new','running')`. A job that has already transitioned to `failed` is excluded from this query by design.

`frontend/src/lib/hooks/use-jobs-poller.ts:235-250`:
```ts
// -- Handle persisted jobs that are no longer in the active list ------------
// A job disappears from the active list when it transitions out of new/running.
// We need to reflect that in our store (it likely completed while we were away).
for (const stored of jobs) {
  if (stored.status !== 'new' && stored.status !== 'running') continue
  if (serverIds.has(stored.jobId)) continue
  // Was in-flight, no longer active → treat as completed (most common case).
  ...
  update(stored.jobId, { status: 'completed' })
  ...
  handleTermination(stored.jobId, { ...stored, status: 'completed' })
}
```
Any job that fails between two poll ticks (which is nearly guaranteed for a fast admission-control rejection like this one) vanishes from the active list and is force-marked `completed` — never `failed` — regardless of what actually happened server-side. `handleTermination`'s `completed` branch (lines 266-297) invalidates the session cache and fires `toast.success(t('jobs.chatReady'))`. The correctly-implemented `failed` branch right below it (lines 298-303, `toast.error(getApiErrorMessage(job.error, t, 'jobs.chatFailed'))`) is dead code for this class of failure — it can only fire for a job whose `failed` state happens to be observed on some earlier poll tick while server-side status briefly shows `failed` in a broader query, which doesn't happen here since the poll query itself excludes `failed` rows.

Compounding it: `commandsApi.getJob(id)` (`frontend/src/lib/api/commands.ts:19`) exists specifically to fetch one job's real terminal status/error, but is **never called anywhere** in the frontend (confirmed via repo-wide grep) — it's the fix that was never wired up.

**Why the reply area is empty:** the optimistic placeholder (`useNotebookChat.ts:227-238`, `{id: "pending-${job_id}", content: '', pending: true}`) is client-only. Since the graph node threw before producing an `AIMessage`, nothing was ever persisted server-side to replace it; the cache invalidation on the false "completed" path just refetches a session with the user's message and no reply.

**Not ds4- or side-chat-specific:** side chats (`chat_session` rows with `parent_session_id`/`quote`, `open_notebook/domain/notebook.py:975,980`) run through the exact same `chat.py` graph, the same `chat_commands.py`, and the same `use-jobs-poller.ts` as main notebook chat (`job.kind === 'notebook_chat'` covers both). Any provider whose call fails fast (auth error, connection refused, etc.) would hit the same silent-success path.

## Affected code
- `frontend/src/lib/hooks/use-jobs-poller.ts:238-250` — disappeared-from-active-list jobs are unconditionally marked `completed`; root cause.
- `frontend/src/lib/api/commands.ts:19` — `getJob()` (single-job status/error lookup) is defined but dead code; this is what should be called instead of guessing.
- `api/command_service.py:74-91` — `status_filter="active"` semantics (`new`/`running` only) that make failed jobs invisible to the polling query.
- `commands/chat_commands.py:153-161` — confirms the error is captured correctly server-side (for comparison / not itself buggy).
- `open_notebook/utils/error_classifier.py:63-68` — confirms a real, user-readable error message is generated (for comparison / not itself buggy).
- `frontend/src/lib/hooks/useNotebookChat.ts:227-238` — client-only pending placeholder that's left empty when no `AIMessage` is ever persisted.
- `/home/itz_kenaki/.local/bin/ds4-activator.py:90-121,339-346` — infra trigger for this occurrence (working as designed; refusing to overcommit GPU memory).

## Repro
1. Put the ds4 heavy slot under memory pressure so `ds4-activator` refuses to wake ds4-backend (or simulate any fast-failing provider — auth failure, connection refused, etc. would also work).
2. Send a message in any chat (main or side) using a model routed through that failing provider.
3. Observe: composer/job UI shows a pending/spinner state, then a `toast.success` "chat ready", the assistant turn stays empty, no error is ever shown.
→ Expected: `toast.error` with the real backend error message (`jobs.chatFailed` + the classified message, e.g. "The AI provider is temporarily unavailable...").
→ Actual: false success toast, empty reply, error fully hidden — confirmed by loguru/journalctl logs showing the real failure occurred.

## Proposed direction
In `use-jobs-poller.ts`'s disappeared-job branch (~line 238-250), don't assume `completed` — call `commandsApi.getJob(stored.jobId)` to fetch the real terminal status/error before deciding which `handleTermination` path to take. This is a single fetch per disappeared job (rare event, not the normal poll path) so it shouldn't add meaningful load. Fall back to the current "assume completed" behavior only if the single-job lookup itself fails (e.g. 404 because the job record was purged). Watch out for: the grace-period removal timer (`REMOVE_GRACE_MS`) and the `prevStatuses` bookkeeping both currently assume synchronous resolution — switching to an async lookup means `handleTermination` needs to run after the fetch resolves, not inline in the same effect pass. Also worth checking whether other job kinds (podcast, embed) that go through the same disappearance branch have the same silent-failure exposure, since the fix is generic to the poller, not chat-specific.

## Open questions / unknowns
- The screenshot shows two small spinner/retry-style icons stacked with no text in the side chat's message area — I did not trace the exact component rendering those (likely `MessageList.tsx` or a job-tray pending indicator) to confirm whether that's the optimistic placeholder, a stuck retry affordance, or something else. Worth a quick look if the visual glitch itself (not just the missing error) needs fixing.
- Didn't trace `surreal_commands`' own crash-recovery internals, so it's unconfirmed whether an API/worker restart mid-flight adds a second, distinct orphaning path on top of the poller bug (e.g. a job stuck in `running` forever after a worker restart, rather than reaching `failed`). The user's repro involved two restarts before the empty message appeared, which may be a second contributing factor.
