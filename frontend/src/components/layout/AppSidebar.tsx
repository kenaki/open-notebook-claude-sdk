'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/hooks/use-auth'
import { useSidebarStore } from '@/lib/stores/sidebar-store'
import { useUtilityDrawerStore } from '@/lib/stores/utility-drawer-store'
// Import the hook from its own module, NOT the workspace barrel: the barrel
// re-exports DeepDiveWorkspace, which transitively pulls in the PDF viewer
// (SourceReaderPanel → SourceDetailContent), and this light layout component
// (and its test) must not drag that heavy CSS graph in.
import { useNotebookWorkspace } from '@/components/notebooks/workspace/NotebookWorkspaceProvider'
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { LanguageToggle } from '@/components/common/LanguageToggle'
import type { TFunction } from 'i18next'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  Activity,
  Book,
  Search,
  Mic,
  Bot,
  Shuffle,
  Settings,
  LogOut,
  ChevronLeft,
  Menu,
  FileText,
  Plus,
  Wrench,
  Command,
  StickyNote,
  PanelLeftClose,
} from 'lucide-react'

const getNavigation = (t: TFunction) => [
  {
    title: t('navigation.workspace'),
    items: [
      { name: t('navigation.sources'), href: '/sources', icon: FileText },
      { name: t('navigation.notebooks'), href: '/notebooks', icon: Book },
      { name: t('navigation.askAndSearch'), href: '/search', icon: Search },
      { name: t('navigation.podcasts'), href: '/podcasts', icon: Mic },
    ],
  },
  {
    title: t('navigation.system'),
    items: [
      { name: t('navigation.activity'), href: '/activity', icon: Activity },
      { name: t('navigation.models'), href: '/settings/api-keys', icon: Bot },
      { name: t('navigation.transformations'), href: '/transformations', icon: Shuffle },
      { name: t('navigation.settings'), href: '/settings', icon: Settings },
      { name: t('navigation.advanced'), href: '/advanced', icon: Wrench },
    ],
  },
] as const

type CreateTarget = 'source' | 'notebook' | 'podcast'

export function AppSidebar() {
  const { t } = useTranslation()
  const navigation = getNavigation(t)
  const pathname = usePathname()
  const { logout } = useAuth()
  const { isCollapsed, toggleCollapse } = useSidebarStore()
  const { openSourceDialog, openNotebookDialog, openPodcastDialog } = useCreateDialogs()
  // Notebook-scoped utility drawer (Sources / Notes). Toggles only render inside
  // a notebook, where the workspace provider supplies the drawer's content.
  const drawerPanel = useUtilityDrawerStore((s) => s.panel)
  const toggleDrawerPanel = useUtilityDrawerStore((s) => s.togglePanel)
  const inNotebook = useNotebookWorkspace() !== null

  const [createMenuOpen, setCreateMenuOpen] = useState(false)
  const [isMac, setIsMac] = useState(true) // Default to Mac for SSR

  // Detect platform for keyboard shortcut display
  useEffect(() => {
    setIsMac(navigator.platform.toLowerCase().includes('mac'))
  }, [])

  const handleCreateSelection = (target: CreateTarget) => {
    setCreateMenuOpen(false)

    if (target === 'source') {
      openSourceDialog()
    } else if (target === 'notebook') {
      openNotebookDialog()
    } else if (target === 'podcast') {
      openPodcastDialog()
    }
  }

  return (
    <TooltipProvider delayDuration={0}>
      <div
        className={cn(
          'app-sidebar flex h-full flex-col bg-sidebar border-sidebar-border border-r transition-[width] duration-300 [contain:layout_paint] will-change-[width]',
          isCollapsed ? 'w-16' : 'w-[236px]'
        )}
      >
        <div
          className={cn(
            'flex h-16 items-center group',
            isCollapsed ? 'justify-center px-2' : 'justify-between px-4'
          )}
        >
          {isCollapsed ? (
            <div className="relative flex items-center justify-center w-full">
              <Image
                src="/logo.svg"
                alt="Open Notebook"
                width={32}
                height={32}
                className="transition-opacity group-hover:opacity-0"
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="absolute text-sidebar-foreground hover:bg-sidebar-accent opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Menu className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Image src="/logo.svg" alt={t('common.appName')} width={32} height={32} />
                <span className="text-base font-medium text-sidebar-foreground">
                  {t('common.appName')}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="text-sidebar-foreground hover:bg-sidebar-accent"
                data-testid="sidebar-toggle"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>

        <nav
          className={cn(
            'flex-1 space-y-1 py-4',
            isCollapsed ? 'px-2' : 'px-3'
          )}
        >
          <div
            className={cn(
              'mb-4',
              isCollapsed ? 'px-0' : 'px-3'
            )}
          >
            <DropdownMenu open={createMenuOpen} onOpenChange={setCreateMenuOpen}>
              {isCollapsed ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                      <Button
                        onClick={() => setCreateMenuOpen(true)}
                        variant="default"
                        size="sm"
                        className="w-full justify-center px-2 bg-primary hover:bg-primary/90 text-primary-foreground border-0"
                        aria-label={t('common.create')}
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                   <TooltipContent side="right">{t('common.create')}</TooltipContent>
                </Tooltip>
              ) : (
                <DropdownMenuTrigger asChild>
                  <Button
                    onClick={() => setCreateMenuOpen(true)}
                    variant="default"
                    size="sm"
                    className="w-full justify-start bg-primary hover:bg-primary/90 text-primary-foreground border-0"
                   >
                    <Plus className="h-4 w-4 mr-2" />
                    {t('common.create')}
                  </Button>
                </DropdownMenuTrigger>
              )}

              <DropdownMenuContent
                align={isCollapsed ? 'end' : 'start'}
                side={isCollapsed ? 'right' : 'bottom'}
                className="w-48"
              >
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault()
                    handleCreateSelection('source')
                  }}
                  className="gap-2"
                >
                   <FileText className="h-4 w-4" />
                  {t('common.source')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault()
                    handleCreateSelection('notebook')
                  }}
                  className="gap-2"
                >
                   <Book className="h-4 w-4" />
                  {t('common.notebook')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault()
                    handleCreateSelection('podcast')
                  }}
                  className="gap-2"
                >
                   <Mic className="h-4 w-4" />
                  {t('common.podcast')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Notebook utility toggles: open the single drawer to Sources / Notes.
              Only shown inside a notebook (where the drawer has content). */}
          {inNotebook && (
            <div className={cn('mb-2', isCollapsed ? 'px-0' : 'px-0')}>
              {!isCollapsed && (
                <h3 className="mb-1.5 px-2 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-text-3">
                  {t('navigation.thisNotebook')}
                </h3>
              )}
              <div className="space-y-0.5">
                {[
                  { key: 'sources' as const, name: t('navigation.sources'), icon: FileText },
                  { key: 'notes' as const, name: t('common.notes'), icon: StickyNote },
                ].map((tool) => {
                  const isActive = drawerPanel === tool.key
                  const button = (
                    <Button
                      variant="ghost"
                      onClick={() => toggleDrawerPanel(tool.key)}
                      aria-pressed={isActive}
                      className={cn(
                        'w-full gap-2.5 font-medium sidebar-menu-item',
                        isActive ? 'bg-accent-soft text-primary' : 'text-muted-foreground',
                        isCollapsed ? 'justify-center px-2' : 'justify-start'
                      )}
                    >
                      <tool.icon className={cn('h-4 w-4', isActive ? 'text-primary' : 'text-text-3')} />
                      {!isCollapsed && <span>{tool.name}</span>}
                      {!isCollapsed && isActive && (
                        <PanelLeftClose className="ml-auto h-3.5 w-3.5 text-primary/70" />
                      )}
                    </Button>
                  )
                  return isCollapsed ? (
                    <Tooltip key={tool.key}>
                      <TooltipTrigger asChild>{button}</TooltipTrigger>
                      <TooltipContent side="right">{tool.name}</TooltipContent>
                    </Tooltip>
                  ) : (
                    <div key={tool.key}>{button}</div>
                  )
                })}
              </div>
            </div>
          )}

          {navigation.map((section, index) => (
            <div key={section.title} className={cn(index > 0 && !isCollapsed && 'pt-3')}>
              <div className="space-y-0.5">
                {!isCollapsed && (
                  <h3 className="mb-1.5 px-2 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-text-3">
                    {section.title}
                  </h3>
                )}

                {section.items
                  // Inside a notebook, the global "Sources" library link is
                  // redundant with the "This notebook → Sources" drawer toggle
                  // (same label + icon), so drop it here to kill the duplicate.
                  // It stays reachable from the global nav outside a notebook.
                  .filter((item) => !(inNotebook && item.href === '/sources'))
                  .map((item) => {
                  const isActive = pathname?.startsWith(item.href) || false
                  const button = (
                    <Button
                      variant="ghost"
                      className={cn(
                        'w-full gap-2.5 font-medium sidebar-menu-item',
                        isActive
                          ? 'bg-card text-foreground shadow-[var(--shadow)] hover:bg-card'
                          : 'text-muted-foreground',
                        isCollapsed ? 'justify-center px-2' : 'justify-start'
                      )}
                    >
                      <item.icon className={cn('h-4 w-4', isActive ? 'text-primary' : 'text-text-3')} />
                      {!isCollapsed && <span>{item.name}</span>}
                    </Button>
                  )

                  if (isCollapsed) {
                    return (
                      <Tooltip key={item.name}>
                        <TooltipTrigger asChild>
                          <Link href={item.href}>
                            {button}
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent side="right">{item.name}</TooltipContent>
                      </Tooltip>
                    )
                  }

                  return (
                    <Link key={item.name} href={item.href}>
                      {button}
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>

        <div
          className={cn(
            'border-t border-sidebar-border p-3 space-y-2',
            isCollapsed && 'px-2'
          )}
        >
          {/* Command Palette hint */}
          {!isCollapsed && (
            <div className="px-3 py-1.5 text-xs text-sidebar-foreground/60">
              <div className="flex items-center justify-between">
                 <span className="flex items-center gap-1.5">
                  <Command className="h-3 w-3" />
                  {t('common.quickActions')}
                </span>
                <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
                  {isMac ? <span className="text-xs">⌘</span> : <span>Ctrl+</span>}K
                </kbd>
              </div>
               <p className="mt-1 text-[10px] text-sidebar-foreground/40">
                {t('common.quickActionsDesc')}
              </p>
            </div>
          )}

           <div
            className={cn(
              'flex flex-col gap-2',
              isCollapsed ? 'items-center' : 'items-stretch'
            )}
          >
            {isCollapsed ? (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div>
                      <ThemeToggle iconOnly />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="right">{t('common.theme')}</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div>
                      <LanguageToggle iconOnly />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="right">{t('common.language')}</TooltipContent>
                </Tooltip>
              </>
            ) : (
              <>
                <ThemeToggle />
                <LanguageToggle />
              </>
            )}
          </div>

          {isCollapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  className="w-full justify-center sidebar-menu-item"
                  onClick={logout}
                  aria-label={t('common.signOut')}
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
               <TooltipContent side="right">{t('common.signOut')}</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="outline"
              className="w-full justify-start gap-3 sidebar-menu-item"
              onClick={logout}
              aria-label={t('common.signOut')}
             >
              <LogOut className="h-4 w-4" />
              {t('common.signOut')}
            </Button>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
