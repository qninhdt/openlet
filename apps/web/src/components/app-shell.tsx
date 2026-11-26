import { WorkspaceUsage } from './workspace-usage';
import { AccountMenu } from './shell-menus';
import { useShellLocation, useShellNavigate } from '@/lib/shell-navigation';
import { UploadsProvider } from './storage/uploads';
import { useEffect, useRef, useState, type ComponentProps } from 'react';
import { Outlet, useLocation, useRouter } from '@tanstack/react-router';
import { usePanelRef } from 'react-resizable-panels';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  ChevronRight,
  Palette,
  Plus,
  FolderPlus,
  Folder,
  Folders,
  CircleUserRound,
  Activity,
  PanelLeft,
  PanelRight,
  Search,
  Settings,
  Layers3,
  Users,
  X,
} from 'lucide-react';

import { PageHeader } from '@/components/page-header';
import { FileSessionsProvider } from '@/components/storage/file-sessions';
import { StorageProvider } from '@/components/storage/storage-context';
import { StorageSidebar } from '@/components/storage/storage-sidebar';
import { StorageTabs } from '@/components/storage/storage-page';
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
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { ScrollArea } from '@/components/ui/scroll-area';
import { AgentPreviewProvider, useAgentPreview } from '@/components/agents/agent-preview';
import { AgentSidebar } from '@/components/agents/agent-sidebar';
import { AgentPanel, AgentPanelHeader, AgentCreateDialog } from '@/components/agents/agent-panels';
import { HitlInboxBell } from '@/components/agents/hitl-inbox-bell';
import { BoxSidebar } from '@/components/agents/box-view';
import { Boxes } from 'lucide-react';
import { useWorkspaces } from '@/lib/workspace-directory';
import { EditorTabs } from '@/components/agents/editor-tabs';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useIsMobile } from '@/hooks/use-mobile';
import { type Destination, type ShellLocation } from '@/lib/shell-model';
import { cn } from '@/lib/utils';

const navigation = [
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'boxes', label: 'Box', icon: Boxes },
  { id: 'storage', label: 'Storage', icon: Folders },
] as const;

const titles: Record<Destination, string> = {
  agents: 'Agents',
  boxes: 'Box',
  storage: 'Storage',
  settings: 'Settings',
};

function IconAction({
  label,
  side = 'bottom',
  sideOffset = 6,
  ...props
}: ComponentProps<typeof Button> & {
  label: string;
  side?: ComponentProps<typeof TooltipContent>['side'];
  sideOffset?: number;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label} {...props} />
      </TooltipTrigger>
      <TooltipContent side={side} sideOffset={sideOffset} className="hidden md:block">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

export function AppShell() {
  const search = useShellLocation();
  const workspaces = useWorkspaces();
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  if (!workspace || (search.agent && !workspace.agents.some((agent) => agent.id === search.agent)))
    return (
      <p role="alert" className="p-8">
        This workspace or agent is unavailable.
      </p>
    );
  return (
    <UploadsProvider key={workspace.id} workspaceId={workspace.id}>
      <FileSessionsProvider>
        <AgentPreviewProvider>
          <StorageProvider workspace={workspace}>
            <WorkspaceShell />
          </StorageProvider>
        </AgentPreviewProvider>
      </FileSessionsProvider>
    </UploadsProvider>
  );
}

function WorkspaceShell() {
  const search = useShellLocation();
  const workspaces = useWorkspaces();
  const navigate = useShellNavigate();
  const router = useRouter();
  const isMobile = useIsMobile(721);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const headerRow = useRef<HTMLDivElement>(null);
  const sidebarPanel = usePanelRef();
  const entry = useLocation({ select: (location) => location.state.shellEntry });
  const [mobilePane, setMobilePane] = useState<'workspace' | 'conversation'>(() =>
    (entry || !search.agent) && search.view === 'agents' && window.innerWidth <= 720
      ? 'workspace'
      : 'conversation',
  );
  const [searchOpen, setSearchOpen] = useState(false);
  const preview = useAgentPreview();

  const { setPanelOpen } = preview;
  const panelOpen = !!search.agent && search.view === 'agents' && preview.panelOpen;
  const panelExpanded = panelOpen && preview.panelExpanded && !isMobile;
  const agentSurface = (search.view === 'agents' && !!search.agent) || search.view === 'boxes';
  const narrowWindow = useIsMobile(panelOpen ? 1125 : 765);
  const autoCompact = !isMobile && narrowWindow && search.view === 'agents';
  const folderEditing = preview.folderEditor !== null;
  const compactSidebar =
    !isMobile && !folderEditing && search.view === 'agents' && (autoCompact || sidebarCollapsed);
  const showSidebar = sidebarOpen || search.view === 'settings';
  useEffect(() => {
    if (isMobile || !showSidebar) return;
    const frame = requestAnimationFrame(() => {
      if (autoCompact && !folderEditing) sidebarPanel.current?.collapse();
      else sidebarPanel.current?.expand();
    });
    return () => cancelAnimationFrame(frame);
  }, [autoCompact, folderEditing, isMobile, showSidebar, sidebarPanel, search.view]);
  const [settingsFilter, setSettingsFilter] = useState('');
  const [historyState, setHistoryState] = useState(() => ({
    back: router.history.canGoBack(),
    forward: router.history.location.state.__TSR_index < router.history.length - 1,
  }));
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  const agent = workspace.agents.find((item) => item.id === search.agent);
  const heading = search.view === 'agents' ? (agent?.name ?? 'Agents') : titles[search.view];

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

  function go(next: Partial<ShellLocation>) {
    const workspaceChanged = !!next.workspace && next.workspace !== search.workspace;
    const view = next.view ?? search.view;
    const targetAgent =
      next.agent ??
      (workspaceChanged
        ? (workspaces.find((w) => w.id === next.workspace)?.agents[0]?.id ?? '')
        : search.agent);
    void navigate({
      ...next,
      agent: targetAgent,
      mainTab: next.mainTab ?? (view === 'agents' ? preview.mainTabFor(targetAgent) : 'box'),
      ...(workspaceChanged ? { storage: '', folder: '', file: '', boxAgent: '' } : {}),
    });
    if (next.agent || (next.view && next.view !== 'agents') || next.section)
      setMobilePane('conversation');
    else if (next.view === 'agents') setMobilePane('workspace');
    setSearchOpen(false);
  }

  function pageRail() {
    return (
      <nav
        aria-label="Workspace navigation"
        className="page-rail relative flex w-13 shrink-0 flex-col items-center gap-1.5 pt-[calc(var(--shell-header-height)+0.25rem)] pb-3 text-muted-foreground"
      >
        <Tooltip>
          <TooltipTrigger asChild>
            <a
              href="/"
              aria-label="Openlet home"
              className="absolute top-0 flex h-(--shell-header-height) w-full items-center justify-center rounded-md pt-0.5 focus-visible:outline-2 focus-visible:outline-ring"
            >
              <AppLogo />
            </a>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={8} className="hidden md:block">
            Home
          </TooltipContent>
        </Tooltip>
        {navigation.map(({ id, label, icon: Icon }) => (
          <IconAction
            key={id}
            label={label}
            side="right"
            sideOffset={8}
            size="icon-lg"
            variant={search.view === id ? 'secondary' : 'ghost'}
            aria-current={search.view === id ? 'page' : undefined}
            onClick={() => go({ view: id })}
          >
            <Icon />
          </IconAction>
        ))}
        <div className="mt-auto flex flex-col items-center gap-2">
          <HitlInboxBell workspaceId={workspace.id} />
          <WorkspaceUsage workspace={workspace.id} />
          <IconAction
            label="Settings"
            side="right"
            sideOffset={8}
            size="icon-lg"
            aria-current={search.view === 'settings' ? 'page' : undefined}
            variant={search.view === 'settings' ? 'secondary' : 'ghost'}
            onClick={() => go({ view: 'settings', section: 'general' })}
          >
            <Settings />
          </IconAction>
          <AccountMenu workspace={workspace.id} />
        </div>
      </nav>
    );
  }

  function agentList() {
    if (search.view === 'boxes')
      return (
        <BoxSidebar
          selected={search.boxAgent}
          onSelect={(boxAgent) => {
            go({
              view: 'boxes',
              boxAgent,
              mainTab: 'box',
              ...(boxAgent ? { agent: boxAgent } : {}),
            });
          }}
        />
      );
    if (search.view === 'storage')
      return <StorageSidebar onNavigate={() => setMobilePane('conversation')} />;
    if (search.view === 'settings') {
      return (
        <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-sidebar text-sidebar-foreground">
          <h2 className="flex shrink-0 items-center gap-2 truncate px-4 pt-4 pb-4 text-sm font-medium">
            {search.section === 'workspace' || search.section === 'members' ? (
              <>
                <Layers3 className="size-4 shrink-0" />
                <span className="truncate">{workspace.name}</span>
              </>
            ) : (
              'Your settings'
            )}
          </h2>
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
          <nav
            aria-label="Settings sections"
            className="flex min-h-0 min-w-0 flex-1 flex-col gap-1 overflow-y-auto px-2"
          >
            {(search.section === 'workspace' || search.section === 'members'
              ? [
                  { id: 'workspace' as const, label: 'General', icon: Settings },
                  { id: 'members' as const, label: 'Members', icon: Users },
                ]
              : [
                  { id: 'profile' as const, label: 'Your profile', icon: CircleUserRound },
                  { id: 'general' as const, label: 'General', icon: Settings },
                  { id: 'appearance' as const, label: 'Appearance', icon: Palette },
                ]
            )
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
          <div className="mt-auto min-w-0 shrink-0 border-t p-2">
            <Button
              variant="ghost"
              className="w-full min-w-0 justify-start"
              onClick={() =>
                go({
                  section:
                    search.section === 'workspace' || search.section === 'members'
                      ? 'general'
                      : 'workspace',
                })
              }
            >
              {search.section === 'workspace' || search.section === 'members' ? (
                <CircleUserRound data-icon="inline-start" />
              ) : (
                <Layers3 data-icon="inline-start" />
              )}
              <span className="min-w-0 flex-1 truncate text-left">
                {search.section === 'workspace' || search.section === 'members'
                  ? 'Your settings'
                  : `${workspace.name} settings`}
              </span>
              <ChevronRight className="ml-auto" />
            </Button>
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-sidebar text-sidebar-foreground">
        <div
          className={cn(
            'flex items-center gap-1.5 px-3 pt-2 pb-1.5',
            compactSidebar && 'flex-wrap',
            compactSidebar && 'justify-center',
          )}
        >
          <Button
            variant={compactSidebar ? 'ghost' : 'outline'}
            size={compactSidebar ? 'icon' : 'default'}
            className={
              compactSidebar
                ? undefined
                : 'h-8 min-w-0 flex-1 justify-start bg-muted px-2.5 font-normal text-muted-foreground'
            }
            aria-label="Search workspace"
            onClick={() => setSearchOpen(true)}
          >
            <Search data-icon="inline-start" />
            {!compactSidebar && (
              <>
                <span className="flex-1 text-left">Search</span>
              </>
            )}
          </Button>
          {search.view === 'agents' && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="New agent or folder"
                  disabled={!preview.organization.ready || preview.organization.busy}
                >
                  <Plus />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  {preview.organization.canCreate && (
                    <DropdownMenuItem onSelect={() => preview.setCreateOpen(true)}>
                      <Bot />
                      New agent
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem
                    onSelect={() => {
                      if (compactSidebar) {
                        sidebarPanel.current?.expand();
                      }
                      preview.setFolderEditor({ id: null, parent_id: null, name: '' });
                    }}
                  >
                    <FolderPlus />
                    New folder
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
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
    return <Outlet />;
  }

  const showWorkspace = isMobile && mobilePane === 'workspace';
  return (
    <div
      className={cn(
        'flex h-dvh overflow-hidden bg-background text-foreground',
        isMobile && 'flex-col pb-[env(safe-area-inset-bottom)]',
      )}
    >
      <div className="flex min-h-0 min-w-0 flex-1">
        {(!isMobile || showWorkspace) && pageRail()}
        <div className={cn('flex min-w-0 flex-1 flex-col pb-1 pr-2', isMobile && 'p-0')}>
          {!showWorkspace && (
            <div
              ref={headerRow}
              className="shell-top-row flex h-(--shell-header-height) shrink-0 text-muted-foreground"
            >
              <div
                className="shell-top-navigation flex shrink-0 items-center gap-1 px-2 max-[721px]:px-1"
                style={{
                  width: !isMobile && showSidebar ? 'var(--agent-sidebar-width, 280px)' : undefined,
                }}
              >
                {isMobile ? (
                  <IconAction
                    label={panelOpen && agentSurface ? 'Back to chat' : 'Back to workspace'}
                    onClick={() =>
                      panelOpen && agentSurface ? setPanelOpen(false) : setMobilePane('workspace')
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
              {agentSurface ? (
                isMobile && panelOpen ? (
                  <div className="min-w-0 flex-1">
                    <AgentPanelHeader />
                  </div>
                ) : (
                  <>
                    <div
                      className={cn('flex min-w-0 flex-1 items-center', panelExpanded && 'hidden')}
                      inert={panelExpanded || undefined}
                    >
                      <EditorTabs
                        label="Agent tabs"
                        selected={
                          search.view === 'boxes' && !preview.session.mainTab.startsWith('leti:')
                            ? 'box'
                            : preview.session.mainTab
                        }
                        onSelect={(tab) =>
                          preview.selectMainTab(tab as typeof preview.session.mainTab)
                        }
                        items={[
                          ...(search.view === 'agents'
                            ? [
                                {
                                  id: 'agent',
                                  label: preview.profile.name,
                                  icon: (
                                    <AgentAvatar
                                      name={preview.profile.name}
                                      agentId={preview.resource.id}
                                      appearance={preview.profile.appearance}
                                      className="size-5"
                                    />
                                  ),
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
                                  icon: <CircleUserRound />,
                                },
                                ...(preview.capabilities.can_view_activity
                                  ? [
                                      { id: 'activity', label: 'Activity', icon: <Activity /> },
                                      { id: 'box', label: 'Box', icon: <Boxes /> },
                                    ]
                                  : []),
                              ]
                            : [
                                {
                                  id: 'box',
                                  label: search.boxAgent ? preview.profile.name : 'Box',
                                  icon: search.boxAgent ? (
                                    <AgentAvatar
                                      name={preview.profile.name}
                                      agentId={preview.resource.id}
                                      appearance={preview.profile.appearance}
                                      className="size-5"
                                    />
                                  ) : (
                                    <Boxes />
                                  ),
                                  title: search.boxAgent ? (
                                    <span className="truncate">
                                      {preview.profile.name}
                                      <span className="text-muted-foreground">
                                        {' '}
                                        · {preview.profile.title}
                                      </span>
                                    </span>
                                  ) : undefined,
                                },
                              ]),
                          ...(preview.capabilities.can_view_activity
                            ? preview.session.letis.map((leti) => ({
                                id: `leti:${leti.id}`,
                                label: `${leti.name} · ${leti.title}`,
                                icon: (
                                  <AgentAvatar
                                    name={leti.name}
                                    agentId={leti.id}
                                    appearance={leti.appearance}
                                    className="size-5"
                                  />
                                ),
                                title: (
                                  <span className="flex min-w-0 items-center gap-1">
                                    <span className="truncate">{leti.name}</span>
                                    <span className="truncate text-muted-foreground">
                                      · {leti.title}
                                    </span>
                                  </span>
                                ),
                                onClose: () => preview.closeLeti(leti.id),
                              }))
                            : []),
                        ]}
                      />
                      <div className="flex shrink-0 items-center gap-0.5 pr-2">
                        {search.view === 'agents' && (
                          <IconAction
                            label="Toggle side panel"
                            aria-expanded={panelOpen}
                            onClick={preview.togglePanel}
                          >
                            <PanelRight />
                          </IconAction>
                        )}
                      </div>
                    </div>
                    {!isMobile && panelOpen && (
                      <div
                        className={panelExpanded ? 'min-w-0 flex-1' : 'shrink-0'}
                        style={{
                          width: panelExpanded ? undefined : 'var(--agent-panel-width, 360px)',
                        }}
                      >
                        <AgentPanelHeader />
                      </div>
                    )}
                  </>
                )
              ) : search.view === 'storage' ? (
                <StorageTabs />
              ) : (
                <PageHeader title={search.view === 'settings' ? '' : heading}>
                  {search.view === 'settings' ? (
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
                      {(search.section === 'workspace' || search.section === 'members'
                        ? [
                            { id: 'workspace' as const, label: 'General' },
                            { id: 'members' as const, label: 'Members' },
                          ]
                        : [
                            { id: 'profile' as const, label: 'Profile' },
                            { id: 'general' as const, label: 'General' },
                            { id: 'appearance' as const, label: 'Appearance' },
                          ]
                      ).map(({ id, label }) => (
                        <Button
                          key={id}
                          variant={search.section === id ? 'secondary' : 'ghost'}
                          onClick={() => go({ section: id })}
                        >
                          {label}
                        </Button>
                      ))}
                    </nav>
                  )}
                  <div className="min-h-0 flex-1">
                    {agentSurface ? (
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
                      onResize={(size) => {
                        // Mirror geometry without rerendering both transcripts on every drag step.
                        headerRow.current?.style.setProperty(
                          '--agent-sidebar-width',
                          `${size.inPixels}px`,
                        );
                        setSidebarCollapsed(size.inPixels < 118);
                      }}
                      style={{ overflow: 'hidden' }}
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
                        className="h-full min-w-0"
                      >
                        {agentList()}
                      </aside>
                    </ResizablePanel>
                    <ResizableHandle aria-label="Resize sidebar" />
                  </>
                )}
                <ResizablePanel id="page" minSize={panelOpen && agentSurface ? '540px' : '280px'}>
                  <ResizablePanelGroup orientation="horizontal" className="relative">
                    <ResizablePanel
                      id="conversation"
                      minSize="280px"
                      className={panelExpanded ? 'invisible pointer-events-none' : undefined}
                      inert={panelExpanded || undefined}
                    >
                      {content()}
                    </ResizablePanel>
                    {panelOpen && agentSurface && (
                      <>
                        <ResizableHandle
                          aria-label="Resize side panel"
                          className={panelExpanded ? 'invisible pointer-events-none' : undefined}
                        />
                        <ResizablePanel
                          id="context"
                          className={
                            panelExpanded
                              ? 'absolute! inset-0! z-20 w-full! max-w-none!'
                              : undefined
                          }
                          defaultSize="360px"
                          minSize="260px"
                          maxSize="600px"
                          onResize={(size) =>
                            !panelExpanded &&
                            headerRow.current?.style.setProperty(
                              '--agent-panel-width',
                              `${size.inPixels}px`,
                            )
                          }
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
      <AgentCreateDialog />
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
