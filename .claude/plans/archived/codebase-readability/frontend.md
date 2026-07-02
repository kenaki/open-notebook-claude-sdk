# Frontend Track — `frontend/`

> Part of the **Codebase Readability Refactor**. Shared rules, status table, and decisions live in **[coordinator.md](coordinator.md)** — read it first. Update the Status table *there* as each chunk lands.
> **Order:** A4·A5·A6 → B5·B6·B7·B9 → B8 → C6 (pilot)·C8·C9 → **C7 last**.
> **Verify after every chunk:** `cd frontend && npx tsc --noEmit` · `npm run lint` · `npm run test` (vitest, jsdom) · manual check that affected screens render identically.
> **Resolved gate:** all error helpers standardize on **`getApiErrorMessage`** (i18n key → translated, else raw backend string). **Scope:** behavior-preserving splits only — do NOT convert fetch-in-`useEffect` to TanStack (deferred).

---

## PHASE A — Shared primitives (additive; no call-site changes yet)

### A4 · `client.ts` — `get/post/put/del` + `getAuthToken`/`streamFetch` · LOW
`frontend/src/lib/api/client.ts` exports only the raw axios instance; 14 modules reimplement `return response.data` (87 sites).
- Add `get<T>(url,cfg)`, `post<T>(url,body,cfg)`, `put<T>(url,body,cfg)`, `del(url,cfg)` returning unwrapped `T`.
- Export `getAuthToken()` (factor out the `localStorage['auth-storage']` Bearer parse at `client.ts:37-44`) and `streamFetch(url, body)` for SSE (reuses the token + ok-check).
- **Leave alone:** `sources.downloadFile` needs the full `AxiosResponse<Blob>` — stays on raw `apiClient`.

### A5 · `lib/utils/format.ts` · LOW
- `formatCompactNumber(n)` (K/M), `formatRelative(date, lang)` (wraps `formatDistanceToNow` + existing `getDateLocale` from `date-locale.ts`), `formatAbsolute(date, lang)`.
- **Watch:** `LoginForm.tsx` / `GeneratePodcastDialog.tsx` use a hand-rolled zh locale ternary differing slightly from `getDateLocale` — verify before collapsing those two in B7.

### A6 · error toast helpers · LOW
Both standardize on **`getApiErrorMessage`**.
- `useErrorToast()` in `lib/hooks/use-error-toast.ts` — closes over `useToast()`+`useTranslation()`, returns `(error, fallbackKey?) => void` (title `t('common.error')`, `variant:'destructive'`). For react-query `onError`.
- `toastApiError(err, t, fallbackKey)` in `lib/utils/error-handler.ts` — for the chat hooks' direct `sonner` toasts; wraps existing `formatApiError` + `getApiErrorMessage`. Replaces hand-rolled `err as {response?:{data?:{detail?:string}}}` casts.

---

## PHASE B — Apply the dedup

### B5 · api modules use `get/post/put/del` · LOW
87 sites across 14 `lib/api/*.ts`. Pure mechanical — `const r = await apiClient.get(...); return r.data` → `return get<T>(...)`. Keep `downloadFile` on raw `apiClient`.

### B6 · hooks adopt error toast helpers · LOW
~44 byte-identical mutation `onError` → `useErrorToast`; ~15 chat-hook casts (useNotebookChat / useSourceChat) → `toastApiError`.

### B7 · adopt `format.ts` · LOW–MED
`formatNumber` in ContextIndicator/GeneratePodcastDialog; `formatDistanceToNow` sites (NotebookCard/Row, SourceDetailContent, EpisodeCard, SessionManager, ChatGallery, NotesColumn); inline `.toLocaleString()` sites. Verify the zh-locale edge cases flagged in A5.

### B9 · SSE `streamFetch` · MED
search.ts + source-chat.ts adopt A4's `streamFetch`/`getAuthToken`. Note: unifying improves source-chat's thinner error path (behavior shift = arguably a fix) — verify the SSE error case.

### B8 · adopt UI primitives · MED · **site-by-site, NOT a sweep**
- `LoadingSpinner` over ~14–20 inline `Loader2 animate-spin` — **skip off-scale sizes** (h-3/3.5/5/12) and the `RefreshCcw` spinner in EpisodeCard.
- `EmptyState` over ~8 inline blocks — **delete the local `function EmptyState` in `ChatGallery.tsx:1078-1093` that shadows the shared one** (clearest win); others may need a `className`/`variant` prop for feature-specific markup.
- `ConfirmDialog` over 4 hand-rolled delete `AlertDialog`s — do C6/C8 split first where the trigger nesting (DropdownMenuItem) changes the open mechanism.

---

## PHASE C — Split the monster files (behavior-preserving)

Per existing convention (`components/sources/`): a feature folder with a barrel `index.ts` re-exporting components; shared hooks go in `lib/hooks/`.

### C6 · `ChatGallery.tsx` (1093) · MED · **PILOT**
→ `ChatCard.tsx`, `ChatRow.tsx`, `TagEditor.tsx` (~908-1057), `useChatFiltering.ts` (query/tag filter logic); **delete the shadowing `EmptyState` (~1078-1093)** and import `common/EmptyState`. Keep the `DeleteButton` (~1061-1076) co-located or move to common.

### C8 · `ChatPanel.tsx` (784) · MED
→ `useChatScrollAnchor.ts` (scroll/pin math ~233-300), `MessageList.tsx`, `ChatComposer.tsx` (textarea + upload + send). Fix the `handleAttach` error cast (~352) to use `toastApiError`.

### C9 · `useNotebookChat.ts` (642) · MED
→ `useNotebookChatSessions.ts` (create/update/delete mutations ~101-230), `useBuildNotebookContext.ts` (the 118-line `buildContext` ~232-350); keep send/stream in the parent hook. The 3 mutation `onError` blocks should already use `toastApiError` from B6.

### C7 · `SourceDetailContent.tsx` (860) · HIGH · **LAST**
→ `useSourceDetail.ts` (the 7 fetch/mutation `useCallback`s ~102-243 — **moved AS-IS, NOT converted to TanStack**), tab panels `SourceOverviewTab.tsx` / `SourceDetailsTab.tsx` / `SourceInsightsTab.tsx`, delete dialog → `ConfirmDialog`. **Behavior-preserving only — this is where it's tempting to "improve" the fetch logic; don't (that's the deferred T3-g plan).**

---

## Reuse map (don't reinvent)
- `lib/api/client.ts:37-44` — the auth-token parse (factor into `getAuthToken` in A4).
- `components/common/`: `EmptyState.tsx` (icon/title/description/action), `LoadingSpinner.tsx` (size sm/md/lg = h-4/6/8), `ConfirmDialog.tsx` (open/onOpenChange/title/description/confirmVariant/onConfirm/isLoading — self-rendering, no trigger child).
- `lib/utils/error-handler.ts`: `getApiErrorMessage`, `formatApiError` (wrap these, don't duplicate).
- `lib/utils/date-locale.ts`: `getDateLocale` (wrap in A5).
- Test style: `components/common/ConfirmDialog.test.tsx`, `lib/hooks/use-modal-manager.test.ts` (vitest + @testing-library/react; `src/test/setup.ts` mocks useTranslation/useAuth/next-navigation).
