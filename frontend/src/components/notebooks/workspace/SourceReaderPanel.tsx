'use client'

import { AppWindow, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SourceDetailContent } from '@/components/source/detail/SourceDetailContent'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useChatWorkspaceStore } from '@/lib/stores/chat-workspace-store'
import { openNamedWindow } from '@/lib/utils/windows'

interface SourceReaderPanelProps {
  /** Full source record id (the panel token, e.g. "source:abc123"). */
  sourceId: string
  /** Owning notebook (Chunk C3) — threaded into the pop-out window's `nb` param. */
  notebookId: string
  onClose: () => void
  // Ask-AI wiring (Chunk A3): forwarded straight through to
  // `SourceDetailContent`, which hides the buttons itself when absent.
  onChatAboutHighlight?: (quote: string, annotationId?: string) => void
  onChatAboutHighlights?: (quotes: string[], tag: string, annotationIds?: string[]) => void
}

/**
 * Thin wrapper mounting the full source reader (tabs, annotations, highlighting,
 * PDF view) as a workspace track panel (cross-interface-study / Chunk A1).
 * Reuses `SourceDetailContent` as-is — no fork — in its `toolbar` layout, which
 * collapses the header into one line so the reader gets the rest of the height;
 * `PanelCard` already supplies the bounded-height flex parent it needs.
 *
 * Ask-AI handling (Chunk A3) is owned by `DeepDiveWorkspace`, which stages the
 * highlight into the dock composer — this component just relays the callbacks.
 *
 * Chunk C3: the toolbar also carries a "move to window" button — pops the
 * reader out into a named, chromeless (`?focus=1`) OS window (re-focused, never
 * duplicated, see `lib/utils/windows.ts`) and closes this in-panel copy, since
 * the window replaces it. `nb=<notebookId>` targets Chunk C4's cross-window
 * ask-AI intent at this notebook's chat window (Decisions #8).
 */
export function SourceReaderPanel({
  sourceId,
  notebookId,
  onClose,
  onChatAboutHighlight,
  onChatAboutHighlights,
}: SourceReaderPanelProps) {
  const { t } = useTranslation()
  const closeSourcePanel = useChatWorkspaceStore((s) => s.closeSourcePanel)

  const handleOpenInWindow = () => {
    openNamedWindow(`on-reader-${sourceId}`, `/sources/${sourceId}?focus=1&nb=${notebookId}`)
    closeSourcePanel(sourceId)
  }

  return (
    <SourceDetailContent
      sourceId={sourceId}
      layout="toolbar"
      onClose={onClose}
      onChatAboutHighlight={onChatAboutHighlight}
      onChatAboutHighlights={onChatAboutHighlights}
      toolbarTrailing={
        <>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleOpenInWindow}
            title={t('sources.openInWindow')}
            aria-label={t('sources.openInWindow')}
          >
            <AppWindow className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            title={t('common.close')}
            aria-label={t('common.close')}
          >
            <X className="h-4 w-4" />
          </Button>
        </>
      }
    />
  )
}
