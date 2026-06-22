'use client'

import { useState } from 'react'
import { NotebookResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Archive, ArchiveRestore, Trash2, ChevronDown, MoreHorizontal } from 'lucide-react'
import { useUpdateNotebook } from '@/lib/hooks/use-notebooks'
import { NotebookDeleteDialog } from './NotebookDeleteDialog'
import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import { InlineEdit } from '@/components/common/InlineEdit'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface NotebookHeaderProps {
  notebook: NotebookResponse
}

export function NotebookHeader({ notebook }: NotebookHeaderProps) {
  const { t, language } = useTranslation()
  const dfLocale = getDateLocale(language)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  
  const updateNotebook = useUpdateNotebook()

  const handleUpdateName = async (name: string) => {
    if (!name || name === notebook.name) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { name }
    })
  }

  const handleUpdateDescription = async (description: string) => {
    if (description === notebook.description) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { description: description || undefined }
    })
  }

  const handleArchiveToggle = () => {
    updateNotebook.mutate({
      id: notebook.id,
      data: { archived: !notebook.archived }
    })
  }

  const createdLabel = t('common.created').replace(
    '{time}',
    formatDistanceToNow(new Date(notebook.created), { addSuffix: true, locale: dfLocale })
  )
  const updatedLabel = t('common.updated').replace(
    '{time}',
    formatDistanceToNow(new Date(notebook.updated), { addSuffix: true, locale: dfLocale })
  )

  return (
    <>
      {/* One-line header: editable name + a details popover (description +
          timestamps) and an overflow menu (archive / delete). Keeps vertical
          chrome minimal so the panel track gets the height. */}
      <div className="flex items-center gap-2 min-h-[40px]">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <InlineEdit
            id="notebook-name"
            name="notebook-name"
            value={notebook.name}
            onSave={handleUpdateName}
            className="text-base font-semibold truncate"
            inputClassName="text-base font-semibold"
            placeholder={t('notebooks.namePlaceholder')}
          />
          {notebook.archived && (
            <Badge variant="secondary" className="flex-shrink-0">{t('notebooks.archived')}</Badge>
          )}

          {/* Details popover: description editor + created/updated. */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 flex-shrink-0 text-muted-foreground"
                title={t('notebooks.addDescription')}
              >
                <ChevronDown className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 space-y-3">
              <InlineEdit
                id="notebook-description"
                name="notebook-description"
                value={notebook.description || ''}
                onSave={handleUpdateDescription}
                className="text-sm text-muted-foreground"
                inputClassName="text-sm text-muted-foreground"
                placeholder={t('notebooks.addDescription')}
                multiline
                emptyText={t('notebooks.addDescription')}
              />
              <div className="text-xs text-muted-foreground border-t pt-2">
                {createdLabel} • {updatedLabel}
              </div>
            </PopoverContent>
          </Popover>
        </div>

        {/* Overflow menu: archive / delete. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 flex-shrink-0 text-muted-foreground"
              title={t('common.actions')}
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onSelect={handleArchiveToggle}>
              {notebook.archived ? (
                <>
                  <ArchiveRestore className="h-4 w-4 mr-2" />
                  {t('notebooks.unarchive')}
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4 mr-2" />
                  {t('notebooks.archive')}
                </>
              )}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => setShowDeleteDialog(true)}
              className="text-red-600 focus:text-red-700"
            >
              <Trash2 className="h-4 w-4 mr-2" />
              {t('common.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <NotebookDeleteDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        notebookId={notebook.id}
        notebookName={notebook.name}
        redirectAfterDelete
      />
    </>
  )
}