# Background Jobs — Track D: i18n

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first, then execute this
> track's chunk here.
> **Location:** `.claude/plans/background-jobs/d-i18n.md`.

## SESSION HANDOFF — resume here
**Track deps:** **Tracks B and C must be ☑** — the final `jobs.*` key names are defined by their usage.
**Concurrent with:** none (runs last).
**This chat owns ONLY:** `frontend/src/lib/locales/*/index.ts` (all 14 locale dirs).
**State at handoff (2026-06-25):** not started; waiting on B + C.
**Paste-able resume prompt — re-runnable:**
> Continue Background-Jobs Track D. Read `.claude/plans/background-jobs/coordinator.md` then
> `.claude/plans/background-jobs/d-i18n.md`. Confirm Tracks B and C are ☑ in the coordinator (stop if not).
> Collect every `t('jobs.*')` key referenced by Track B & C code (grep the repo), add a complete `jobs:`
> section to `frontend/src/lib/locales/en-US/index.ts`, then replicate the SAME key set across all other 13
> locale dirs (English fallback values acceptable). Verify `npx tsc --noEmit` + the app renders with no
> missing-key warnings. Commit. Update this track's Status table AND the coordinator's Global table +
> Changelog. If this completes EVERY track, archive the feature directory per the coordinator's Completion
> section and tell the user.

## This track's file ownership
Modifies: `frontend/src/lib/locales/<lang>/index.ts` for all 14 languages
(`bn-IN, ca-ES, de-DE, en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR, ru-RU, tr-TR, zh-CN, zh-TW`).

## Status table (this track)
| Chunk | Title | Status | Owner / session | Notes |
|------:|-------|--------|-----------------|-------|
| 1 | `jobs.*` keys across 14 locales | ☐ todo | | dep B, C |
Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked · ⊘ deferred.

## Changelog (this track)
- _(none yet)_

## Chunks (verbatim)

### Chunk 1 — `jobs.*` i18n keys across 14 locales
- **Goal:** every background-jobs UI string has a translation key in all locales.
- **Read first:** `frontend/src/lib/locales/en-US/index.ts` (find the `chat:` section as a placement
  reference), `frontend/src/lib/locales/index.ts` (how locales aggregate), and the Track B/C code that
  calls `t('jobs.*')`.
- **Steps:**
  1. `grep -rho "t('jobs\.[^']*'" frontend/src` (and `"jobs\.[^"']*"`) to collect the exact keys actually used.
  2. Add a `jobs:` section to `en-US/index.ts` covering at least: `jobs.tray.title`, `jobs.tray.empty`,
     `jobs.status.{queued,running,completed,failed}`, `jobs.chatReady`, `jobs.chatFailed`, `jobs.view`,
     `jobs.generating` — plus any key the grep surfaced.
  3. Replicate the identical key set into the other 13 locale `index.ts` files (English values acceptable as
     fallback for v1; keys MUST exist so the loader doesn't warn).
- **Verify:** `npx tsc --noEmit`; restart `on-frontend`; open the tray / trigger a completion toast in a
  couple of languages → strings resolve, no `jobs.*` raw keys leak to the UI, no missing-key console warnings.
- **On completion:** this is the last build-now chunk — if the coordinator's Global status table now shows
  every track ☑, perform archival (move the feature dir to `.claude/plans/archived/background-jobs/`).

## Open Questions (this track)
- **Q-translate-now** — v1 ships English values in non-en locales (keys present, values not localized).
  Default: acceptable; real translations are a follow-up. Flag if the user wants full localization now.
