import { useEffect, useState, type ComponentProps } from 'react';
import { useNavigate, useRouter, useSearch } from '@tanstack/react-router';
import { useTheme } from 'next-themes';
import { usePanelRef } from 'react-resizable-panels';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarClock,
  Check,
  ChevronRight,
  Palette,
  Folder,
  HardDrive,
  ChevronsUpDown,
  Globe2,
  MessageCircle,
  ListTodo,
  Moon,
  PanelLeft,
  PanelRight,
  Search,
  Settings,
  Sun,
  Users,
  X,
} from 'lucide-react';

import { PageHeader } from '@/components/page-header';
import { StorageProvider } from '@/components/storage/storage-context';
import { StorageSidebar } from '@/components/storage/storage-sidebar';
import {
  StoragePage,
  StorageIdentity,
  StorageHeaderTools,
} from '@/components/storage/storage-page';
import { AppLogo } from '@/components/app-logo';
import { AgentAvatar } from '@/components/agent-avatar';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { AppSettings } from '@/components/app-settings';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { AgentPreviewProvider, useAgentPreview } from '@/components/agents/agent-preview';
import { AgentSidebar } from '@/components/agents/agent-sidebar';
import { AgentConversation } from '@/components/agents/agent-conversation';
import {
  AgentPanel,
  AgentPanelHeader,
  AgentModelPicker,
  AgentSettingsDialog,
} from '@/components/agents/agent-panels';
import { AgentOverview } from '@/components/agents/agent-overview';
import { Badge } from '@/components/ui/badge';
import { EditorTabs } from '@/components/agents/editor-tabs';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useIsMobile } from '@/hooks/use-mobile';
import { workspaces, type Destination, type ShellSearch } from '@/lib/shell-model';
import { cn } from '@/lib/utils';

const navigation = [
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'schedule', label: 'Schedule', icon: CalendarClock },
  { id: 'storage', label: 'Storage', icon: HardDrive },
] as const;

const titles: Record<Destination, string> = {
  agents: 'Agents',
  schedule: 'Schedule',
  storage: 'Storage',
  settings: 'Settings',
};

function IconAction({ label, ...props }: ComponentProps<typeof Button> & { label: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label} {...props} />
      </TooltipTrigger>
      <TooltipContent side="bottom" className="hidden md:block">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

export function AppShell() {
  const search = useSearch({ from: '/app' });
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  return (
    <AgentPreviewProvider key={workspace.id}>
      <StorageProvider workspace={workspace}>
        <WorkspaceShell />
      </StorageProvider>
    </AgentPreviewProvider>
  );
}

function WorkspaceShell() {
  const search = useSearch({ from: '/app' });
  const navigate = useNavigate();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const isMobile = useIsMobile(721);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const sidebarPanel = usePanelRef();
  const [mobilePane, setMobilePane] = useState<'workspace' | 'conversation'>(() =>
    search.view === 'agents' && window.innerWidth <= 720 ? 'workspace' : 'conversation',
  );
  const [searchOpen, setSearchOpen] = useState(false);
  const preview = useAgentPreview();
  const overviewPending = preview.pendingRequests;
  const { panelOpen, setPanelOpen } = preview;
  const narrowWindow = useIsMobile(panelOpen ? 1125 : 765);
  const autoCompact = !isMobile && narrowWindow && search.view === 'agents';
  const compactSidebar =
    !isMobile && search.view === 'agents' && (autoCompact || sidebarWidth < 118);
  const showSidebar = sidebarOpen || search.view === 'settings';
  useEffect(() => {
    if (isMobile || !showSidebar) return;
    const frame = requestAnimationFrame(() => {
      if (autoCompact) sidebarPanel.current?.collapse();
      else sidebarPanel.current?.expand();
    });
    return () => cancelAnimationFrame(frame);
  }, [autoCompact, isMobile, showSidebar, sidebarPanel, search.view]);
  const [settingsFilter, setSettingsFilter] = useState('');
  const [historyState, setHistoryState] = useState(() => ({
    back: router.history.canGoBack(),
    forward: router.history.location.state.__TSR_index < router.history.length - 1,
  }));
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  const agent = workspace.agents.find((item) => item.id === search.agent)!;
  const heading = search.view === 'agents' ? agent.name : titles[search.view];

  useEffect(
    () =>
      router.history.subscribe(() =>
        setHistoryState({
          back: router.history.canGoBack(),
          forward: router.history.location.state.__TSR_index < router.history.length - 1,
        }),
      ),
    [router],
  );
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  function go(next: Partial<ShellSearch>) {
    void navigate({ to: '/app', search: { ...search, ...next } });
    if (next.agent || (next.view && next.view !== 'agents') || next.section)
      setMobilePane('conversation');
    else if (next.view === 'agents') setMobilePane('workspace');
    setSearchOpen(false);
  }

  function workspaceMenu(topbar = false) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size={topbar ? 'sm' : 'icon-lg'}
            aria-label="Switch workspace"
            className={topbar ? 'max-w-full justify-start' : undefined}
          >
            {topbar ? (
              <>
                <span className="truncate">{workspace.name}</span>
                <ChevronsUpDown data-icon="inline-end" />
              </>
            ) : (
              <AppLogo className="size-6" />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side={topbar ? 'bottom' : 'right'}
          align={topbar ? 'start' : 'end'}
          className="w-64"
        >
          <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
          <DropdownMenuGroup>
            {workspaces.map((item) => (
              <DropdownMenuItem
                key={item.id}
                onSelect={() => go({ workspace: item.id, agent: item.agents[0].id })}
              >
                <Users />
                {item.name}
                {item.id === workspace.id && <Check className="ml-auto" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onSelect={() => go({ view: 'settings' })}>
              <Settings />
              Workspace settings
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  function pageRail() {
    return (
      <nav
        aria-label="Workspace navigation"
        className="page-rail relative flex w-13 shrink-0 flex-col items-center gap-1.5 pt-[calc(var(--shell-header-height)+0.25rem)] pb-3 text-muted-foreground"
      >
        <a
          href="/"
          aria-label="Openlet home"
          className="absolute top-0 flex h-(--shell-header-height) w-full items-center justify-center rounded-md pt-0.5 focus-visible:outline-2 focus-visible:outline-ring"
        >
          <AppLogo />
        </a>
        {navigation.map(({ id, label, icon: Icon }) => (
          <IconAction
            key={id}
            label={label}
            size="icon-lg"
            variant={search.view === id ? 'secondary' : 'ghost'}
            aria-current={search.view === id ? 'page' : undefined}
            onClick={() => go({ view: id })}
          >
            <Icon />
          </IconAction>
        ))}
        <div className="mt-auto flex flex-col items-center gap-2">
          <IconAction
            label={resolvedTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            size="icon-lg"
            onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
          >
            {resolvedTheme === 'dark' ? <Sun /> : <Moon />}
          </IconAction>
          <IconAction
            label="Settings"
            size="icon-lg"
            aria-current={search.view === 'settings' ? 'page' : undefined}
            variant={search.view === 'settings' ? 'secondary' : 'ghost'}
            onClick={() => go({ view: 'settings' })}
          >
            <Settings />
          </IconAction>
          <Separator className="my-1 max-w-6" />
          {workspaceMenu()}
        </div>
      </nav>
    );
  }

  function agentList() {
    if (search.view === 'storage')
      return <StorageSidebar onNavigate={() => setMobilePane('conversation')} />;
    if (search.view === 'settings') {
      return (
        <div className="flex h-full min-h-0 flex-col bg-sidebar text-sidebar-foreground">
          <h2 className="px-4 pt-3 pb-4 text-lg font-semibold">Your settings</h2>
          <div className="px-2 pb-4">
            <InputGroup className="rounded-full">
              <InputGroupInput
                aria-label="Search settings"
                placeholder="Search settings…"
                value={settingsFilter}
                onChange={(event) => setSettingsFilter(event.target.value)}
              />
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
            </InputGroup>
          </div>
          <nav aria-label="Settings sections" className="flex flex-col gap-1 px-2">
            {[
              { id: 'general' as const, label: 'General', icon: Settings },
              { id: 'appearance' as const, label: 'Appearance', icon: Palette },
            ]
              .filter((item) => item.label.toLowerCase().includes(settingsFilter.toLowerCase()))
              .map(({ id, label, icon: Icon }) => (
                <Button
                  key={id}
                  variant={search.section === id ? 'secondary' : 'ghost'}
                  className="justify-start font-normal"
                  aria-current={search.section === id ? 'page' : undefined}
                  onClick={() => go({ section: id })}
                >
                  <Icon data-icon="inline-start" />
                  {label}
                </Button>
              ))}
          </nav>
          <div className="mt-auto border-t p-2">
            <Button
              variant="ghost"
              className="w-full justify-start"
              onClick={() => go({ view: 'agents' })}
            >
              <Users data-icon="inline-start" />
              <span className="truncate">{workspace.name}</span>
              <ChevronRight className="ml-auto" />
            </Button>
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full min-h-0 flex-col bg-sidebar text-sidebar-foreground">
        {isMobile && (
          <div className="flex h-(--shell-header-height) shrink-0 items-center border-b px-2">
            {workspaceMenu(true)}
          </div>
        )}
        <div
          className={cn(
            'flex items-center gap-1 px-3 pt-2 pb-1.5',
            compactSidebar && 'justify-center',
          )}
        >
          <Button
            variant={compactSidebar ? 'ghost' : 'outline'}
            size={compactSidebar ? 'icon' : 'default'}
            className={compactSidebar ? undefined : 'min-w-0 flex-1 justify-start font-normal'}
            aria-label="Search workspace"
            onClick={() => setSearchOpen(true)}
          >
            <Search data-icon="inline-start" />
            {!compactSidebar && (
              <>
                <span className="flex-1 text-left">Search</span>
                <span className="text-caption text-muted-foreground">⌘ K</span>
              </>
            )}
          </Button>
        </div>
        <ScrollArea className="min-h-0 flex-1 px-3 pt-1">
          {search.view === 'agents' ? (
            <AgentSidebar
              compact={compactSidebar}
              onSelect={(agent) => go({ view: 'agents', agent })}
            />
          ) : (
            <div className="flex flex-col gap-1 pt-1">
              <p className="px-2 py-2 text-xs font-medium text-muted-foreground">
                {titles[search.view]}
              </p>
              <Button variant="secondary" className="justify-start">
                <Folder data-icon="inline-start" />
                All schedules
              </Button>
            </div>
          )}
        </ScrollArea>
      </div>
    );
  }

  function panel() {
    return <AgentPanel />;
  }

  function content() {
    return search.view === 'storage' ? (
      <StoragePage />
    ) : search.view === 'settings' ? (
      <AppSettings section={search.section} />
    ) : search.view === 'agents' ? (
      <div key={agent.id} className="h-full min-h-0">
        <div hidden={preview.session.mainTab !== 'agent'} className="h-full">
          <AgentConversation />
        </div>
        <div hidden={preview.session.mainTab !== 'overview'} className="h-full">
          <AgentOverview />
        </div>
      </div>
    ) : (
      <section aria-label={heading} className="h-full" />
    );
  }

  const showWorkspace = isMobile && mobilePane === 'workspace';
  return (
    <div
      className={cn(
        'flex h-dvh overflow-hidden bg-background text-foreground',
        isMobile && 'flex-col',
      )}
    >
      <div className="flex min-h-0 min-w-0 flex-1">
        {(!isMobile || showWorkspace) && pageRail()}
        <div className={cn('flex min-w-0 flex-1 flex-col pb-1 pr-2', isMobile && 'p-0')}>
          {!showWorkspace && (
            <div className="shell-top-row flex h-(--shell-header-height) shrink-0 text-muted-foreground">
              <div
                className="shell-top-navigation flex shrink-0 items-center gap-1 px-2 max-[721px]:px-1"
                style={{
                  width: !isMobile && showSidebar ? sidebarWidth : undefined,
                }}
              >
                {isMobile ? (
                  <IconAction
                    label={
                      panelOpen && search.view === 'agents' ? 'Back to chat' : 'Back to workspace'
                    }
                    onClick={() =>
                      panelOpen && search.view === 'agents'
                        ? setPanelOpen(false)
                        : setMobilePane('workspace')
                    }
                  >
                    <ArrowLeft />
                  </IconAction>
                ) : (
                  <>
                    {!compactSidebar && (
                      <>
                        <IconAction
                          label="Go back"
                          disabled={!historyState.back}
                          onClick={() => router.history.back()}
                        >
                          <ArrowLeft />
                        </IconAction>
                        <IconAction
                          label="Go forward"
                          disabled={!historyState.forward}
                          onClick={() => router.history.forward()}
                        >
                          <ArrowRight />
                        </IconAction>
                      </>
                    )}
                    <IconAction
                      label={showSidebar ? 'Hide sidebar' : 'Show sidebar'}
                      aria-expanded={sidebarOpen}
                      onClick={() => setSidebarOpen((open) => !open)}
                    >
                      <PanelLeft />
                    </IconAction>
                  </>
                )}
              </div>
              {search.view === 'agents' ? (
                isMobile && panelOpen ? (
                  <div className="min-w-0 flex-1">
                    <AgentPanelHeader />
                  </div>
                ) : (
                  <>
                    <div className="flex min-w-0 flex-1 items-center">
                      <EditorTabs
                        label="Agent tabs"
                        selected={preview.session.mainTab}
                        onSelect={(mainTab) =>
                          preview.updateSession({ mainTab: mainTab as 'agent' | 'overview' })
                        }
                        items={[
                          {
                            id: 'agent',
                            label: preview.profile.name,
                            icon: <AgentAvatar name={agent.name} className="size-5" />,
                            title: (
                              <h1
                                aria-label={preview.profile.name}
                                className="flex min-w-0 items-center gap-1 font-normal"
                              >
                                <span className="truncate">{preview.profile.name}</span>
                                <span className="truncate text-muted-foreground max-[1000px]:hidden">
                                  · {preview.profile.title}
                                </span>
                              </h1>
                            ),
                          },
                          {
                            id: 'overview',
                            label: 'Overview',
                            icon: <ListTodo />,
                            title: (
                              <span className="flex items-center gap-1.5">
                                Overview
                                {overviewPending > 0 && (
                                  <Badge
                                    aria-hidden="true"
                                    variant="secondary"
                                    className="h-4 min-w-4 px-1 text-caption font-normal tabular-nums"
                                  >
                                    {overviewPending}
                                  </Badge>
                                )}
                              </span>
                            ),
                          },
                        ]}
                      />
                      <div className="flex shrink-0 items-center gap-0.5 pr-2">
                        {preview.session.mainTab === 'agent' && <AgentModelPicker />}
                        <IconAction
                          label="Toggle side panel"
                          aria-expanded={panelOpen}
                          disabled={!preview.session.files.length}
                          onClick={preview.togglePanel}
                        >
                          <PanelRight />
                        </IconAction>
                      </div>
                    </div>
                    {!isMobile && panelOpen && (
                      <div className="shrink-0" style={{ width: preview.panelWidth }}>
                        <AgentPanelHeader />
                      </div>
                    )}
                  </>
                )
              ) : (
                <PageHeader
                  title={search.view === 'settings' ? '' : heading}
                  identity={search.view === 'storage' ? <StorageIdentity /> : undefined}
                >
                  {search.view === 'storage' ? (
                    <StorageHeaderTools />
                  ) : search.view === 'settings' ? (
                    <IconAction label="Close settings" onClick={() => go({ view: 'agents' })}>
                      <X />
                    </IconAction>
                  ) : (
                    <>
                      <IconAction label="Search workspace" onClick={() => setSearchOpen(true)}>
                        <Search />
                      </IconAction>
                    </>
                  )}
                </PageHeader>
              )}
            </div>
          )}
          <main
            id="main-content"
            tabIndex={-1}
            className={cn(
              'min-h-0 min-w-0 flex-1 overflow-hidden bg-sidebar',
              !isMobile && 'rounded-2xl border',
            )}
          >
            {isMobile ? (
              showWorkspace ? (
                agentList()
              ) : (
                <div className="flex h-full flex-col">
                  {search.view === 'settings' && (
                    <nav
                      aria-label="Settings sections"
                      className="flex shrink-0 gap-1 overflow-auto border-b p-2"
                    >
                      <Button
                        variant={search.section === 'general' ? 'secondary' : 'ghost'}
                        onClick={() => go({ section: 'general' })}
                      >
                        <Settings data-icon="inline-start" />
                        General
                      </Button>
                      <Button
                        variant={search.section === 'appearance' ? 'secondary' : 'ghost'}
                        onClick={() => go({ section: 'appearance' })}
                      >
                        <Palette data-icon="inline-start" />
                        Appearance
                      </Button>
                    </nav>
                  )}
                  <div className="min-h-0 flex-1">
                    {search.view === 'agents' ? (
                      <>
                        <div hidden={panelOpen} className="h-full">
                          {content()}
                        </div>
                        {panelOpen && panel()}
                      </>
                    ) : (
                      content()
                    )}
                  </div>
                </div>
              )
            ) : (
              <ResizablePanelGroup orientation="horizontal">
                {showSidebar && (
                  <>
                    <ResizablePanel
                      id="agent-list"
                      panelRef={sidebarPanel}
                      defaultSize="280px"
                      groupResizeBehavior="preserve-pixel-size"
                      collapsible={search.view === 'agents'}
                      collapsedSize="88px"
                      collapsedThreshold="18px"
                      onResize={(size) => setSidebarWidth(size.inPixels)}
                      minSize={search.view === 'settings' ? '220px' : '128px'}
                      maxSize="400px"
                    >
                      <aside
                        aria-label={
                          search.view === 'settings'
                            ? 'Settings sidebar'
                            : search.view === 'storage'
                              ? 'Storage sidebar'
                              : 'Agent sidebar'
                        }
                        className="h-full"
                      >
                        {agentList()}
                      </aside>
                    </ResizablePanel>
                    <ResizableHandle aria-label="Resize sidebar" />
                  </>
                )}
                <ResizablePanel
                  id="page"
                  minSize={panelOpen && search.view === 'agents' ? '540px' : '280px'}
                >
                  <ResizablePanelGroup orientation="horizontal">
                    <ResizablePanel id="conversation" minSize="280px">
                      {content()}
                    </ResizablePanel>
                    {panelOpen && search.view === 'agents' && (
                      <>
                        <ResizableHandle aria-label="Resize side panel" />
                        <ResizablePanel
                          id="context"
                          defaultSize="360px"
                          minSize="260px"
                          maxSize="600px"
                          onResize={(size) => preview.setPanelWidth(size.inPixels)}
                        >
                          {panel()}
                        </ResizablePanel>
                      </>
                    )}
                  </ResizablePanelGroup>
                </ResizablePanel>
              </ResizablePanelGroup>
            )}
          </main>
        </div>
      </div>
      {isMobile && (
        <nav
          aria-label="Mobile pane navigation"
          className="flex min-h-16 shrink-0 items-center justify-center border-t bg-sidebar px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]"
        >
          <div className="grid w-full max-w-90 grid-cols-2 gap-1">
            <Button
              variant={mobilePane === 'conversation' ? 'secondary' : 'ghost'}
              className="min-h-11"
              aria-pressed={mobilePane === 'conversation'}
              onClick={() => setMobilePane('conversation')}
            >
              <MessageCircle data-icon="inline-start" />
              {search.view === 'storage' ? 'Storage' : 'Chat'}
            </Button>
            <Button
              variant={mobilePane === 'workspace' ? 'secondary' : 'ghost'}
              className="min-h-11"
              aria-pressed={mobilePane === 'workspace'}
              onClick={() => setMobilePane('workspace')}
            >
              <Globe2 data-icon="inline-start" />
              Workspace
            </Button>
          </div>
        </nav>
      )}
      <AgentSettingsDialog />
      <CommandDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        title="Search workspace"
        description="Jump to an agent or workspace page."
      >
        <Command>
          <CommandInput placeholder="Search agents and pages…" />
          <CommandList>
            <CommandEmpty>No matching agents or pages.</CommandEmpty>
            <CommandGroup heading="Agents">
              {workspace.agents.map((item) => (
                <CommandItem
                  key={item.id}
                  value={`${item.name} ${item.role}`}
                  onSelect={() => go({ view: 'agents', agent: item.id })}
                >
                  <Bot />
                  {item.name}
                  <span className="ml-auto text-xs text-muted-foreground">{item.role}</span>
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandGroup heading="Pages">
              {navigation.map(({ id, label, icon: Icon }) => (
                <CommandItem key={id} onSelect={() => go({ view: id })}>
                  <Icon />
                  {label}
                </CommandItem>
              ))}
              <CommandItem onSelect={() => go({ view: 'settings' })}>
                <Settings />
                Settings
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </div>
  );
}
