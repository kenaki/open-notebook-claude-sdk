'use client'

import { Trash2 } from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { buttonVariants } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'

interface DeleteChatButtonProps {
  // Permanently delete the chat (existing chat.deleteSession). Runs only after
  // the user confirms.
  onDelete: () => void
  className?: string
}

/**
 * Trash (delete) control for a chat (Sidebar redesign / Chunk 3). The X button
 * elsewhere only HIDES a chat; this is the single destructive affordance, gated
 * behind an AlertDialog confirm. Shared by the sidebar row (main chats) and the
 * popped-panel header (side chats). Stops propagation so it doesn't trigger the
 * row's open-on-click.
 */
export function DeleteChatButton({ onDelete, className }: DeleteChatButtonProps) {
  const { t } = useTranslation()
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <button
          type="button"
          title={t('chat.deleteChat')}
          aria-label={t('chat.deleteChat')}
          className={cn(
            'p-0.5 rounded text-muted-foreground hover:bg-background hover:text-destructive',
            className
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </AlertDialogTrigger>
      <AlertDialogContent onClick={(e) => e.stopPropagation()}>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('chat.deleteChat')}</AlertDialogTitle>
          <AlertDialogDescription>{t('chat.deleteChatConfirm')}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction
            className={buttonVariants({ variant: 'destructive' })}
            onClick={() => onDelete()}
          >
            {t('chat.deleteChat')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
