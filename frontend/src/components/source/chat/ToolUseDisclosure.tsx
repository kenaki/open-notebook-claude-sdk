'use client'

import { ChevronRight, Search, FileText, StickyNote, BookOpen, Wrench } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ToolUseDisclosure as ToolUseData } from '@/lib/types/api'
import { useTranslation } from '@/lib/hooks/use-translation'

// Map a raw MCP tool name (Q-toolnames: backend sends raw names, the UI maps)
// to a friendly i18n key + an icon. Anything unrecognized falls back to a
// generic "Used a tool".
function describeTool(toolName: string): { key: string; Icon: typeof Search } {
  if (toolName.includes('search')) return { key: 'chat.searchedYourSources', Icon: Search }
  if (toolName.includes('note')) return { key: 'chat.readNote', Icon: StickyNote }
  if (toolName.includes('notebook')) return { key: 'chat.readNotebook', Icon: BookOpen }
  if (toolName.includes('source')) return { key: 'chat.readSources', Icon: FileText }
  return { key: 'chat.usedTool', Icon: Wrench }
}

// Pull a short, human-meaningful detail out of the tool arguments: the search
// query when present, otherwise the targeted record id, otherwise the first
// string value. Shown monospace next to each tool row.
function detailFor(toolInput: Record<string, unknown>): string | null {
  const candidate =
    toolInput.query ?? toolInput.q ?? toolInput.id ?? toolInput.source_id ?? toolInput.note_id ?? toolInput.notebook_id
  if (typeof candidate === 'string' && candidate.trim()) return candidate
  for (const value of Object.values(toolInput)) {
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

/**
 * Collapsible tool-use disclosure for an AI message produced by the Claude Agent
 * (Plan D / Chunk 10). Summary line ("Searched your sources" + count) expands to
 * a list of each MCP tool call with a friendly label + the searched target/query.
 * Renders nothing when there are no tool uses (Esperanto path / old sessions —
 * `tool_uses` is null there, so the caller gates on `tool_uses?.length`).
 */
export function ToolUseDisclosure({ toolUses }: { toolUses: ToolUseData[] }) {
  const { t } = useTranslation()
  if (!toolUses.length) return null

  // Headline = the first search tool if one ran (the handoff names the disclosure
  // "Searched your sources"), otherwise the friendly label of the first call.
  const headline = toolUses.find((tu) => tu.tool_name.includes('search')) ?? toolUses[0]
  const { Icon: HeadIcon, key: headKey } = describeTool(headline.tool_name)

  return (
    <Collapsible className="w-full">
      <CollapsibleTrigger className="group flex w-full items-center gap-1.5 rounded-lg border border-border-2 bg-panel-2 px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-accent-soft">
        <HeadIcon className="h-3.5 w-3.5 flex-shrink-0 text-text-3" aria-hidden="true" />
        <span className="font-medium text-foreground">{t(headKey)}</span>
        <span className="text-text-3">· {toolUses.length}</span>
        <ChevronRight
          className="ml-auto h-3.5 w-3.5 flex-shrink-0 text-text-3 transition-transform duration-[0.18s] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-1 flex flex-col gap-1 pl-1">
          {toolUses.map((tu) => {
            const { Icon, key } = describeTool(tu.tool_name)
            const detail = detailFor(tu.tool_input)
            return (
              <li key={tu.id} className="flex items-start gap-1.5 text-[11px] leading-snug">
                <Icon
                  className={`mt-0.5 h-3 w-3 flex-shrink-0 ${tu.is_error ? 'text-destructive' : 'text-text-3'}`}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className={tu.is_error ? 'text-destructive' : 'text-muted-foreground'}>{t(key)}</span>
                  {detail && (
                    <span className="ml-1.5 truncate font-mono text-text-3">{detail}</span>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}
