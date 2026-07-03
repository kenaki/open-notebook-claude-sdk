'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { chatApi } from '@/lib/api/chat'
import type { SourceListResponse, NoteResponse, BuildContextResponse } from '@/lib/types/api'
import type { ContextSelections } from '@/lib/types/notebook-context'

// Builds the context payload for notebook chat from the current source/note
// selections, and keeps token/char count estimates fresh as selections change.
// The first build fires immediately on mount; rapid toggling is debounced (250ms)
// so a burst of changes collapses into a single POST /chat/context.
export function useBuildNotebookContext({
  notebookId,
  sources,
  notes,
  contextSelections,
}: {
  notebookId: string
  sources: SourceListResponse[]
  notes: NoteResponse[]
  contextSelections: ContextSelections
}) {
  const [tokenCount, setTokenCount] = useState(0)
  const [charCount, setCharCount] = useState(0)
  // Last-built context payload, retained so the dock's meter can preview exactly
  // what's in the window on hover (the counts alone don't say what's inside).
  const [contextData, setContextData] = useState<BuildContextResponse['context'] | null>(null)

  const buildContext = useCallback(async () => {
    const context_config: { sources: Record<string, string>; notes: Record<string, string> } = {
      sources: {},
      notes: {},
    }

    sources.forEach((source) => {
      const mode = contextSelections.sources[source.id]
      if (mode === 'insights') {
        context_config.sources[source.id] = 'insights'
      } else if (mode === 'full') {
        context_config.sources[source.id] = 'full content'
      } else {
        context_config.sources[source.id] = 'not in'
      }
    })

    notes.forEach((note) => {
      const mode = contextSelections.notes[note.id]
      if (mode === 'full') {
        context_config.notes[note.id] = 'full content'
      } else {
        context_config.notes[note.id] = 'not in'
      }
    })

    const response = await chatApi.buildContext({ notebook_id: notebookId, context_config })
    setTokenCount(response.token_count)
    setCharCount(response.char_count)
    setContextData(response.context)
    return response.context
  }, [notebookId, sources, notes, contextSelections])

  const contextDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const contextCountsPrimedRef = useRef(false)

  useEffect(() => {
    const updateContextCounts = async () => {
      try {
        await buildContext()
      } catch (error) {
        console.error('Error updating context counts:', error)
      }
    }

    if (!contextCountsPrimedRef.current) {
      contextCountsPrimedRef.current = true
      updateContextCounts()
      return
    }

    if (contextDebounceRef.current) clearTimeout(contextDebounceRef.current)
    contextDebounceRef.current = setTimeout(updateContextCounts, 250)

    return () => {
      if (contextDebounceRef.current) {
        clearTimeout(contextDebounceRef.current)
        contextDebounceRef.current = null
      }
    }
  }, [buildContext])

  return { buildContext, tokenCount, charCount, contextData }
}
