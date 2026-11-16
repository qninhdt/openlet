import { useLocation, useMatches, useNavigate, useParams, useSearch } from '@tanstack/react-router';
import { useWorkspaces } from './workspace-directory';
import {
  type AgentTab,
  type Destination,
  type ShellLocation,
  settingsSections,
} from './shell-model';

declare module '@tanstack/react-router' {
  interface StaticDataRouteOption {
    view?: Destination;
    agentTab?: AgentTab;
  }
  interface HistoryState {
    shellAgent?: string;
    shellEntry?: boolean;
  }
}

export function useShellLocation(): ShellLocation {
  const params = useParams({ strict: false });
  const search = useSearch({ strict: false });
  const rememberedAgent = useLocation({ select: (location) => location.state.shellAgent });
  const meta = useMatches({
    select: (matches) => ({
      view: matches.findLast((m) => m.staticData.view)?.staticData.view ?? 'agents',
      tab: matches.findLast((m) => m.staticData.agentTab)?.staticData.agentTab,
    }),
  });
  const workspaces = useWorkspaces();
  const workspace = params.workspaceId ?? '';
  const agents = workspaces.find((w) => w.id === workspace)?.agents ?? [];
  return {
    workspace,
    view: meta.view,
    agent:
      params.agentId ?? agents.find((a) => a.id === rememberedAgent)?.id ?? agents[0]?.id ?? '',
    mainTab: params.letiId
      ? `leti:${params.letiId}`
      : (meta.tab ?? (meta.view === 'boxes' ? 'box' : 'agent')),
    section: settingsSections.find((s) => s === params.section) ?? 'general',
    storage: params.storageId ?? '',
    folder: params.folderId ?? (!params.storageId ? (search.folder ?? '') : ''),
    file: params.nodeId ?? (!params.storageId ? (search.file ?? '') : ''),
    boxAgent: meta.view === 'boxes' && search.scope !== 'all' ? (params.agentId ?? '') : '',
  };
}

// One typed destination contract for the rail, header tabs, file browser and legacy links.
export function shellTarget(location: ShellLocation) {
  const { workspace: workspaceId, agent: agentId, storage: storageId, mainTab } = location;
  const params = { workspaceId, agentId };
  if (location.view === 'settings')
    return {
      to: '/app/$workspaceId/settings/$section' as const,
      params: { workspaceId, section: location.section },
    };
  if (location.view === 'storage') {
    if (!storageId)
      return {
        to: '/app/$workspaceId/storage' as const,
        params: { workspaceId },
        search: { folder: location.folder, file: location.file },
      };
    if (location.file)
      return {
        to: '/app/$workspaceId/storage/$storageId/files/$nodeId' as const,
        params: { workspaceId, storageId, nodeId: location.file },
      };
    if (location.folder)
      return {
        to: '/app/$workspaceId/storage/$storageId/folders/$folderId' as const,
        params: { workspaceId, storageId, folderId: location.folder },
      };
    return {
      to: '/app/$workspaceId/storage/$storageId' as const,
      params: { workspaceId, storageId },
    };
  }
  if (location.view === 'boxes') {
    if (mainTab.startsWith('leti:'))
      return {
        to: '/app/$workspaceId/boxes/$agentId/letis/$letiId/activity' as const,
        params: { ...params, letiId: mainTab.slice(5) },
        search: { scope: location.boxAgent ? undefined : ('all' as const) },
      };
    return location.boxAgent
      ? {
          to: '/app/$workspaceId/boxes/$agentId' as const,
          params: { workspaceId, agentId: location.boxAgent },
        }
      : { to: '/app/$workspaceId/boxes' as const, params: { workspaceId } };
  }
  if (!agentId) return { to: '/app/$workspaceId/agents' as const, params: { workspaceId } };
  if (mainTab.startsWith('leti:'))
    return {
      to: '/app/$workspaceId/agents/$agentId/letis/$letiId/activity' as const,
      params: { ...params, letiId: mainTab.slice(5) },
    };
  if (mainTab === 'overview')
    return { to: '/app/$workspaceId/agents/$agentId/overview' as const, params };
  if (mainTab === 'activity')
    return { to: '/app/$workspaceId/agents/$agentId/activity' as const, params };
  if (mainTab === 'box') return { to: '/app/$workspaceId/agents/$agentId/box' as const, params };
  return { to: '/app/$workspaceId/agents/$agentId' as const, params };
}

export function useShellNavigate() {
  const current = useShellLocation();
  const navigate = useNavigate();
  return (next: Partial<ShellLocation>, options: { replace?: boolean } = {}) => {
    const target = { ...current, ...next };
    return navigate({
      search: {},
      ...shellTarget(target),
      ...options,
      state: (previous) => ({ ...previous, shellAgent: target.agent, shellEntry: false }),
      resetScroll: false,
    });
  };
}
