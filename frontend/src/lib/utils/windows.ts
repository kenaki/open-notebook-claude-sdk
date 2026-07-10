/**
 * Named-window pop-out helper (cross-interface-study / Chunk C3).
 *
 * Opens (or re-focuses) a browser window identified by a stable `name` so
 * repeated pop-outs for the same target never spawn duplicates — clicking
 * "pop out" twice for the same reader/chat just refocuses the existing OS
 * window instead of opening a second one.
 *
 * Name scheme (documented here, not enforced — callers must be consistent):
 *   - `on-reader-<sourceId>`   — a source reader window (Chunk C3 reader button)
 *   - `on-chat-<notebookId>`   — a workspace/chat window (Chunk C3 chat button)
 *
 * Caveat (accepted, Decisions / c-windows.md Chunk C3): the module-scope
 * handle Map lives only as long as the OPENER window/tab. If the opener
 * reloads (or this module is re-evaluated), the Map is empty again — the
 * next `openNamedWindow` call for a previously-opened name will fall into
 * the `window.open` branch, which the browser resolves by re-navigating the
 * still-open window with that `name` (same-origin `name` reuse is a browser
 * primitive, not something this module tracks) rather than opening a new
 * one. So duplicates are still prevented; the cost is a reload of the target
 * window instead of a silent focus.
 */

const windowHandles = new Map<string, WindowProxy>()

/**
 * Open a browser window/tab named `name` at `url`, or focus it if a live
 * handle from THIS window is already tracked. `features` is intentionally
 * omitted so the browser's own tab/window preference applies (v1).
 */
export function openNamedWindow(name: string, url: string): void {
  const existing = windowHandles.get(name)
  if (existing && !existing.closed) {
    existing.focus()
    return
  }
  const handle = window.open(url, name)
  if (handle) {
    windowHandles.set(name, handle)
    handle.focus()
  }
}
