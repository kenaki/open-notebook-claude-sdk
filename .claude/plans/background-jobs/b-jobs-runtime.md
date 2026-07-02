# Background Jobs — Track B: Jobs Runtime, Tray & Notifications

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first, then execute this
> track's chunks here, one per session.
> **Location:** `.claude/plans/background-jobs/b-jobs-runtime.md`.

## SESSION HANDOFF — resume here
**Track deps:** **Track A chunks 4 (status API + `commands.ts`) and 5 (`jobs-store.ts`) must be ☑** — check
the coordinator's Global status table before starting.
**Concurrent with:** Track C (disjoint files — B owns `layout.tsx` + `components/jobs/*`; C owns chat hooks/components).
**This chat owns ONLY:** `frontend/src/lib/hooks/use-jobs-poller.ts`,
`frontend/src/components/jobs/*` (`JobsRuntime`, `JobTray`, `JobTrayItem`, `JobStatusBadge`),
`frontend/src/lib/utils/job-origin.ts`, and `frontend/src/app/(dashboard)/layout.tsx` (mounts only).
Never edit `jobs-store.ts` / `commands.ts` (Track A owns them — import only) or any chat component (Track C).
**State at handoff (2026-06-25):** not started; waiting on A4 + A5.
**Paste-able resume prompt — re-runnable:**
> Continue Background-Jobs Track B. Read `.claude/plans/background-jobs/coordinator.md` then
> `.claude/plans/background-jobs/b-jobs-runtime.md` in full. Confirm Track A chunks 4 and 5 are ☑ in the
> coordinator; if not, stop and say so. Derive the next unstarted chunk from this track's Status table +
> `git log`; implement exactly ONE chunk (reuse the podcast polling/badge patterns; smallest faithful diff).
> Touch ONLY Track B's files (mount-only edits to `layout.tsx`). Verify (`npx tsc --noEmit` + manual);
> if red, fix or report — don't commit red. Commit just that chunk. Update BOTH this track file's Status
> table AND the coordinator's Global status table + Changelog. Announce "✅ Chunk B.n complete — safe to
> clear context. Next: <derived>" and stop. If this completes EVERY track, archive per the coordinator.

## This track's file ownership
Creates: `frontend/src/lib/hooks/use-jobs-poller.ts`, `frontend/src/components/jobs/JobsRuntime.tsx`,
`JobTray.tsx`, `JobTrayItem.tsx`, `JobStatusBadge.tsx`, `frontend/src/lib/utils/job-origin.ts`.
Modifies (mount-only): `frontend/src/app/(dashboard)/layout.tsx`.
Imports but never edits: `jobs-store.ts`, `lib/api/commands.ts`, `query-client.ts`, `EpisodeCard` badge classes.

## Per-chunk workflow
read referenced files → implement → verify → commit → mark ☑ here AND in coordinator → announce
"✅ Chunk B.n complete — safe to clear context" → stop. One chunk per session.

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 1 | `use-jobs-poller` + `JobsRuntime` + mount | ☑ done | wave3 2026-06-29 | commit 82257ae; poller reconciles store + invalidates session on chat-job completion; JobsRuntime mounted in (dashboard)/layout |
| 2 | `JobTray` + `JobTrayItem` + `JobStatusBadge` + mount | ☐ todo | | dep B1 ✓ |
| 3 | completion/failure toasts + `job-origin` helper | ☐ todo | | dep B1 ✓ |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk 1 — `use-jobs-poller` + `JobsRuntime` + mount
- **Goal:** an app-level poller that fetches active jobs, reconciles them into the global store, and on
  chat-job completion invalidates the originating session's query cache so the answer appears.
- **Read first:** `frontend/src/lib/hooks/use-podcasts.ts` (`usePodcastEpisodes` dynamic `refetchInterval`),
  `frontend/src/lib/stores/jobs-store.ts` (A5), `frontend/src/lib/api/commands.ts` (A4),
  `frontend/src/lib/api/query-client.ts` (`QUERY_KEYS.notebookChatSession`, `sourceChatSession`),
  `frontend/src/app/(dashboard)/layout.tsx`.
- **Steps:**
  1. `use-jobs-poller.ts`: `useQuery(['commands','active'], commandsApi.listActive, { refetchInterval: (q) => anyActive(q) ? 4000 : false, meta:{ silent:true } })`. Snappy initial cadence (~1.5 s) ramping to 4 s while a local chat job is in flight (track a per-job `startedAt` to ramp).
  2. Reconcile each server row into the store: derive `kind` from `name` (`chat_completion`→ args.kind`'notebook_chat'|'source_chat'`, `generate_podcast`→`'podcast'`, `process_source`/`embed_*`→`'source'`, `run_transformation`→`'transformation'`), and `sessionId/notebookId/targetId/label` from `args`. `register` unseen jobs (so server-started podcasts/embeds show up too), `update` status on changes.
  3. On a `chat` job transition to `completed`: `queryClient.invalidateQueries(QUERY_KEYS.notebookChatSession(sessionId))` (or `sourceChatSession(targetId, sessionId)` for source); then `remove(jobId)` after a short grace. On `failed`: `update(jobId,{status,error})`; leave the toast to B3.
  4. `JobsRuntime.tsx`: a client component that calls `useJobsPoller()` and renders `null`. Mount it in
     `(dashboard)/layout.tsx` (authed scope) so it polls only when logged in.
  5. **Reload survival:** on mount the persisted in-flight jobIds are in the store; the first poll
     reconciles their live status (dropping ones already completed while away, after invalidating their session cache).
- **Reuse:** the podcast `refetchInterval` shape; `QUERY_KEYS`; `useJobsStore`.
- **Verify:** `npx tsc --noEmit`; restart `on-frontend`; with a job running (after Track A lands, submit a
  chat or kick a podcast) confirm the network tab polls `/commands/jobs?status_filter=active` and the store
  populates (log it or inspect via React devtools). No console errors when idle (poller off).

### Chunk 2 — `JobTray` + `JobTrayItem` + `JobStatusBadge` + mount
- **Goal:** the persistent bottom-corner tray listing active jobs with status, click-to-origin.
- **Read first:** `frontend/src/components/podcasts/EpisodeCard.tsx` (StatusBadge color map ~46–82),
  `jobs-store.ts`, `frontend/src/app/(dashboard)/layout.tsx`, an existing fixed/overlay component for
  styling conventions (e.g. `CommandPalette`).
- **Steps:**
  1. `JobStatusBadge.tsx`: extract the `bg-amber/emerald/red/sky` status→class map (running/processing→amber,
     completed→emerald, failed/error→red, new/pending→sky) into a shared badge used by both jobs and (optionally later) podcasts.
  2. `JobTrayItem.tsx`: one row — `label`, `<JobStatusBadge>`, optional `progress.phase`, spinner while
     `running`. Click → `router.push(jobOrigin(job))` (the helper lands in B3; for B2 inline a minimal
     origin switch and refactor in B3, or land B3's helper first — your call, keep them consistent).
  3. `JobTray.tsx`: read `useJobsStore`; collapsed pill (count + spinner) when any active, expands to the
     `JobTrayItem` list; empty state hidden. Fixed `bottom-4 right-4 z-50`.
  4. Mount `<JobTray/>` in `(dashboard)/layout.tsx` next to `<JobsRuntime/>`.
- **Reuse:** EpisodeCard badge classes; existing Shadcn `Button`/`Card`/`Popover` primitives; `useRouter`.
- **Verify:** `npx tsc --noEmit`; restart `on-frontend`; with active jobs the tray shows them with correct
  badges; clicking navigates to the notebook/source/podcast origin; tray hides when no jobs.

### Chunk 3 — completion/failure toasts + `job-origin` helper
- **Goal:** notify on completion/failure with a "View" action; centralize origin routing.
- **Read first:** `frontend/src/lib/hooks/use-toast.ts` / `sonner` usage in `use-podcasts.ts`,
  `frontend/src/lib/utils/error-handler.ts` (`getApiErrorMessage`), `use-jobs-poller.ts` (B1).
- **Steps:**
  1. `frontend/src/lib/utils/job-origin.ts`: `jobOrigin(job): string` → `/notebooks/{notebookId}/chat/{sessionId}` for notebook chat, the source page for source chat, the podcasts/episode route for podcasts, the source page for source/transformation. Use it in `JobTrayItem` (B2) and here.
  2. In `use-jobs-poller.ts` completion handler: `toast.success(t('jobs.chatReady'), { action: { label: t('jobs.view'), onClick: () => router.push(jobOrigin(job)) } })`. Failure: `toast.error(getApiErrorMessage(job.error, t, 'jobs.chatFailed'), { action: … })`. Use `jobs.*` keys (Track D fills the locales; reference the keys now).
- **Verify:** `npx tsc --noEmit`; finish a chat job while on another page → success toast with working
  "View"; force a failure (bad model) → error toast; keys resolve (fall back to English until Track D).

## Open Questions (this track)
- **Q-toast-noise** — if many embeds complete at once the tray + toasts could be noisy; default: toast only
  `notebook_chat`/`source_chat` completions, show podcasts/embeds/transforms in the tray silently. Revisit if needed.