'use client'

import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SourcesColumn } from '@/app/(dashboard)/notebooks/components/SourcesColumn'
import { NotesColumn } from '@/app/(dashboard)/notebooks/components/NotesColumn'
import { useUtilityDrawerStore } from '@/lib/stores/utility-drawer-store'
import { useNotebookWorkspace } from '@/components/notebooks/NotebookWorkspaceProvider'
import { useTranslation } from '@/lib/hooks/use-translation'

const DRAWER_WIDTH = 340

/**
 * The single utility drawer (UI refactor). Slides out immediately to the right
 * of the global nav rail and shows EITHER Sources or Notes — toggling between
 * them swaps the content in place rather than opening a second column. Renders
 * only inside a notebook (where {@link useNotebookWorkspace} resolves); collapses
 * to zero width when shut so the chat canvas reclaims the space.
 */
export function UtilityDrawer() {
  const { t } = useTranslation()
  const panel = useUtilityDrawerStore((s) => s.panel)
  const close = useUtilityDrawerStore((s) => s.close)
  const workspace = useNotebookWorkspace()

  // No notebook context → nothing to show (the rail hides the toggles too).
  const open = !!workspace && panel !== null

  return (
    <div
      className={cn(
        'flex-shrink-0 overflow-hidden border-r border-border bg-card transition-[width] duration-300 ease-out [contain:layout_paint] will-change-[width]',
        open ? 'w-[340px]' : 'w-0'
      )}
      aria-hidden={!open}
    >
      {workspace && (
        <div className="flex h-full flex-col" style={{ width: DRAWER_WIDTH }}>
          {/* Slim header: panel label + close. Sources/Notes carry their own
              toolbars below, so this stays minimal. */}
          <div className="flex flex-shrink-0 items-center justify-between border-b border-border px-3 py-2">
            <span className="text-[13px] font-semibold text-foreground">
              {panel === 'notes' ? t('common.notes') : t('navigation.sources')}
            </span>
            <button
              type="button"
              onClick={close}
              title={t('common.close')}
              aria-label={t('common.close')}
              className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1">
            {panel === 'sources' && (
              <SourcesColumn
                sources={workspace.sources}
                isLoading={workspace.sourcesLoading}
                notebookId={workspace.notebookId}
                notebookName={workspace.notebook?.name}
                onRefresh={workspace.refetchSources}
                contextSelections={workspace.contextSelections.sources}
                onContextModeChange={(sourceId, mode) =>
                  workspace.handleContextModeChange(sourceId, mode, 'source')
                }
                onBulkContextModeChange={workspace.handleBulkSourceContext}
                hasNextPage={workspace.hasNextPage}
                isFetchingNextPage={workspace.isFetchingNextPage}
                fetchNextPage={workspace.fetchNextPage}
              />
            )}
            {panel === 'notes' && (
              <NotesColumn
                notes={workspace.notes}
                isLoading={workspace.notesLoading}
                notebookId={workspace.notebookId}
                contextSelections={workspace.contextSelections.notes}
                onContextModeChange={(noteId, mode) =>
                  workspace.handleContextModeChange(noteId, mode, 'note')
                }
                onBulkContextModeChange={workspace.handleBulkNoteContext}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
