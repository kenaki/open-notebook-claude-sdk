'use client'

import { FileText, Lightbulb, StickyNote } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { formatCompactNumber } from '@/lib/utils/format'

interface ContextIndicatorProps {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
  className?: string
}

export function ContextIndicator({
  sourcesInsights,
  sourcesFull,
  notesCount,
  tokenCount,
  charCount,
  className
}: ContextIndicatorProps) {
  const hasContext = (sourcesInsights + sourcesFull) > 0 || notesCount > 0

  if (!hasContext) {
    return (
      <div className={cn('flex-shrink-0 text-xs text-muted-foreground py-2 px-3 border-t', className)}>
        No sources or notes included in context. Toggle icons on cards to include them.
      </div>
    )
  }

  return (
    <div className={cn('flex-shrink-0 flex items-center justify-between gap-2 py-2 px-3 border-t bg-muted/30', className)}>
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">Context:</span>

        <div className="flex items-center gap-1.5">
          {sourcesInsights > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="text-xs flex items-center gap-1 px-1.5 py-0.5 text-amber-600 border-amber-600/50 cursor-default">
                  <Lightbulb className="h-3 w-3" />
                  <span>{sourcesInsights}</span>
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <p>Insights for {sourcesInsights} source{sourcesInsights !== 1 ? 's' : ''}</p>
              </TooltipContent>
            </Tooltip>
          )}

          {sourcesFull > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="text-xs flex items-center gap-1 px-1.5 py-0.5 text-primary border-primary/50 cursor-default">
                  <FileText className="h-3 w-3" />
                  <span>{sourcesFull}</span>
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <p>{sourcesFull} full source{sourcesFull !== 1 ? 's' : ''}</p>
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        {notesCount > 0 && (
          <>
            {(sourcesInsights > 0 || sourcesFull > 0) && (
              <span className="text-muted-foreground">•</span>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="text-xs flex items-center gap-1 px-1.5 py-0.5 text-primary border-primary/50 cursor-default">
                  <StickyNote className="h-3 w-3" />
                  <span>{notesCount}</span>
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <p>{notesCount} full note{notesCount !== 1 ? 's' : ''}</p>
              </TooltipContent>
            </Tooltip>
          </>
        )}
      </div>

      {(tokenCount !== undefined || charCount !== undefined) && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {tokenCount !== undefined && tokenCount > 0 && (
            <span>{formatCompactNumber(tokenCount)} tokens</span>
          )}
          {tokenCount !== undefined && charCount !== undefined && tokenCount > 0 && charCount > 0 && (
            <span>/</span>
          )}
          {charCount !== undefined && charCount > 0 && (
            <span>{formatCompactNumber(charCount)} chars</span>
          )}
        </div>
      )}
    </div>
  )
}
