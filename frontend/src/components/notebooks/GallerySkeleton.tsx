'use client'

/**
 * Page-level loading placeholder for a notebook route (Track B2). Rendered inside
 * {@link AppShell} while the workspace's notebook query is still in flight, so the
 * app chrome (sidebar, drawer, main frame) stays mounted and the content area
 * simply swaps a skeleton for real content — no full-screen spinner flash, no
 * shell unmount/remount. Coarse on purpose: it mirrors the gallery's overall
 * shape (header bar + title/toolbar + a card grid) without trying to be
 * card-accurate. Reused by both the Gallery and Deep-Dive routes.
 *
 * Lives outside `ChatGallery.tsx` so that file stays owned by Track A.
 */
export function GallerySkeleton() {
  return (
    <div className="flex flex-1 flex-col min-h-0" aria-hidden="true">
      {/* Header bar — mirrors the NotebookHeader strip above the gallery. */}
      <div className="flex-shrink-0 border-b border-border px-6 py-3">
        <div className="animate-pulse space-y-2">
          <div className="h-5 w-48 rounded bg-accent" />
          <div className="h-3 w-32 rounded bg-accent-soft" />
        </div>
      </div>

      {/* Gallery body — title/subtitle, toolbar, and a grid of card placeholders. */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <div className="mx-auto w-full max-w-5xl px-6 py-8">
          <div className="animate-pulse">
            <div className="mb-6 flex items-end justify-between gap-4">
              <div className="space-y-2">
                <div className="h-5 w-40 rounded bg-accent" />
                <div className="h-3 w-56 rounded bg-accent-soft" />
              </div>
              <div className="h-9 w-44 rounded-md bg-accent" />
            </div>

            <div className="mb-5 h-9 w-full max-w-sm rounded-md bg-accent-soft" />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4"
                >
                  <div className="flex items-start gap-2.5">
                    <div className="h-7 w-7 flex-shrink-0 rounded-lg bg-accent-soft" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="h-4 w-3/4 rounded bg-accent" />
                      <div className="h-3 w-1/3 rounded bg-accent-soft" />
                    </div>
                  </div>
                  <div className="mt-2 h-3 w-1/4 rounded bg-accent-soft" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
