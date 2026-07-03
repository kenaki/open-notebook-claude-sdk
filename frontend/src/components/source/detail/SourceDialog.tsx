'use client'

import { useRouter } from 'next/navigation'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { SourceDetailContent } from './SourceDetailContent'
import { useTranslation } from '@/lib/hooks/use-translation'

interface SourceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  sourceId: string | null
  /** Decision #20: open the inline PDF at this physical page (from a `#p=N` citation). */
  initialPage?: number
}

/**
 * Source Dialog Component
 *
 * Displays source details in a modal dialog.
 * Includes a "Chat with source" button that navigates to the full source page in-app.
 */
export function SourceDialog({ open, onOpenChange, sourceId, initialPage }: SourceDialogProps) {
  const { t } = useTranslation()
  const router = useRouter()
  // Ensure source ID has 'source:' prefix for API calls and routing
  const sourceIdWithPrefix = sourceId
    ? (sourceId.includes(':') ? sourceId : `source:${sourceId}`)
    : null

  const handleChatClick = () => {
    if (sourceIdWithPrefix) {
      onOpenChange(false)
      router.push(`/sources/${sourceIdWithPrefix}`)
    }
  }

  const handleClose = () => {
    onOpenChange(false)
  }

  if (!sourceIdWithPrefix) {
    return null
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[88vh] max-h-[88vh] w-[92vw] flex-col gap-0 p-0 sm:max-w-6xl">
        {/* Accessibility title (hidden visually but read by screen readers) */}
        <DialogTitle className="sr-only">{t('sources.detailsTitle')}</DialogTitle>

        {/* Source detail content */}
        <div className="flex min-h-0 flex-1 flex-col">
          <SourceDetailContent
            sourceId={sourceIdWithPrefix}
            showChatButton={true}
            onChatClick={handleChatClick}
            onClose={handleClose}
            initialPage={initialPage}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}
