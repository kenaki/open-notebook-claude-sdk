'use client'

import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Image as ImageIcon, Video as VideoIcon, Send, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { chatApi } from '@/lib/api/chat'
import { toastApiError } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { MediaItem } from '@/lib/types/api'
import type { RefObject } from 'react'

interface ChatComposerProps {
  inputValue: string
  onInputChange: (value: string) => void
  onSend: () => void
  isStreaming: boolean
  canSend: boolean
  isDock: boolean
  mediaEnabled: boolean
  pendingMedia: MediaItem[]
  onRemovePending?: (index: number) => void
  onAddPending?: (item: MediaItem) => void
  composerHeader?: ReactNode
  composerToolbar?: ReactNode
  composerMaxHeight?: number
  autoFocus?: boolean
  textareaRef: RefObject<HTMLTextAreaElement | null>
}

export function ChatComposer({
  inputValue,
  onInputChange,
  onSend,
  isStreaming,
  canSend,
  isDock,
  mediaEnabled,
  pendingMedia,
  onRemovePending,
  onAddPending,
  composerHeader,
  composerToolbar,
  composerMaxHeight,
  autoFocus = false,
  textareaRef,
}: ChatComposerProps) {
  const { t } = useTranslation()
  const chatInputId = useId()
  const imageInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const maxHeight = composerMaxHeight ?? (isDock ? 140 : 100)
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
  const keyHint = isMac ? '⌘+Enter' : 'Ctrl+Enter'

  // Focus the composer on mount when requested (a freshly-spawned sub-chat).
  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-grow the composer up to the cap, then scroll.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }, [inputValue, maxHeight, textareaRef])

  // Upload a picked file via POST /chat/media, then stage the returned MediaItem.
  const handleAttach = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !onAddPending) return
    setUploading(true)
    try {
      const item = await chatApi.uploadMedia(file)
      onAddPending(item)
    } catch (err: unknown) {
      toastApiError(err, t, 'chat.uploadFailed')
    } finally {
      setUploading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const isModifierPressed = isMac ? e.metaKey : e.ctrlKey
    if (e.key === 'Enter' && isModifierPressed) {
      e.preventDefault()
      onSend()
    }
  }

  return (
    <div className="flex-shrink-0 p-3 border-t">
      {composerHeader && <div className="mb-2.5">{composerHeader}</div>}

      <div className="rounded-xl border border-border bg-composer transition-[border-color,box-shadow] duration-200 focus-within:border-primary-soft-border focus-within:ring-2 focus-within:ring-accent-soft">
        {/* Staged attachments: monospace filename + remove ✕. */}
        {mediaEnabled && pendingMedia.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pt-3">
            {pendingMedia.map((item, index) => (
              <span
                key={`${item.url}-${index}`}
                className="inline-flex items-center gap-1 rounded-md bg-panel-2 border border-border pl-2 pr-1 py-1 text-[11px]"
              >
                {item.type === 'video' ? (
                  <VideoIcon className="h-3 w-3 text-text-3 flex-shrink-0" />
                ) : (
                  <ImageIcon className="h-3 w-3 text-text-3 flex-shrink-0" />
                )}
                <span className="font-mono truncate max-w-[140px] text-foreground">{item.label}</span>
                <button
                  type="button"
                  title={t('chat.removeAttachment')}
                  onClick={() => onRemovePending?.(index)}
                  className="p-0.5 rounded hover:bg-background text-text-3"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        <Textarea
          ref={textareaRef}
          id={chatInputId}
          name="chat-message"
          autoComplete="off"
          value={inputValue}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isDock
            ? t('chat.sendPlaceholder')
            : `${t('chat.sendPlaceholder')} (${t('chat.pressToSend').replace('{key}', keyHint)})`}
          disabled={isStreaming}
          className="w-full min-h-[60px] resize-none overflow-y-auto border-0 bg-transparent dark:bg-transparent px-3.5 py-3.5 leading-relaxed shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
          style={{ maxHeight }}
          rows={1}
        />

        <div className="flex items-center gap-1.5 px-2 pb-2 pt-0.5 min-w-0">
          {mediaEnabled && (
            <div className="flex items-center gap-0.5 flex-shrink-0">
              <input ref={imageInputRef} type="file" accept="image/*" className="hidden" onChange={handleAttach} />
              <input ref={videoInputRef} type="file" accept="video/*" className="hidden" onChange={handleAttach} />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-text-3"
                title={t('chat.attachImage')}
                disabled={isStreaming || uploading}
                onClick={() => imageInputRef.current?.click()}
              >
                <ImageIcon className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-text-3"
                title={t('chat.attachVideo')}
                disabled={isStreaming || uploading}
                onClick={() => videoInputRef.current?.click()}
              >
                {uploading ? <LoadingSpinner size="sm" /> : <VideoIcon className="h-4 w-4" />}
              </Button>
            </div>
          )}
          {composerToolbar && (
            <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
              {composerToolbar}
            </div>
          )}
          <div className="flex-1" />
          <Button
            onClick={onSend}
            disabled={!canSend}
            size="icon"
            className="h-8 w-8 flex-shrink-0 rounded-lg bg-[var(--primary-soft)] hover:bg-[var(--primary-soft)]"
          >
            {isStreaming ? <LoadingSpinner size="sm" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {isDock && (
        <p className="mt-2.5 text-[11px] text-text-3">
          {t('chat.pressToSend').replace('{key}', keyHint)}
        </p>
      )}
    </div>
  )
}
