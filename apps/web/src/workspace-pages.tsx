import { Navigate, Outlet, useLocation, useParams, useSearch } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useWorkspaces } from '@/lib/workspace-directory';
import { parseLegacySearch } from '@/lib/shell-model';
import { shellTarget, useShellLocation } from '@/lib/shell-navigation';
import { AgentChat } from '@/components/agents/agent-chat';
import { AgentActivity } from '@/components/agents/agent-conversation';
import { useAgentPreview } from '@/components/agents/agent-preview';
import { BoxView } from '@/components/agents/box-view';
import { StoragePage } from '@/components/storage/storage-page';
import { useStorageBrowser } from '@/components/storage/storage-context';
import { AppSettings } from '@/components/app-settings';

export function LegacyWorkspaceEntry() {
  const raw = useSearch({ strict: false });
  const entry = useLocation({
    select: (location) => {
      const query = new URLSearchParams(location.searchStr);
      return !query.has('view') && !query.has('agent');
    },
  });
  const workspaces = useWorkspaces();
  const legacy = parseLegacySearch(raw);
  const workspace = workspaces.find((w) => w.id === raw.workspace) ?? workspaces[0];
  const agent = workspace.agents.find((a) => a.id === raw.agent) ?? workspace.agents[0];
  return (
    <Navigate
      {...shellTarget({
        ...legacy,
        workspace: workspace.id,
        agent: agent.id,
        mainTab: legacy.view === 'boxes' ? 'box' : 'agent',
      })}
      state={{ shellEntry: entry, shellAgent: agent.id }}
      replace
    />
  );
}

export function WorkspaceEntry() {
  const location = useShellLocation();
  return <Navigate {...shellTarget({ ...location, view: 'agents', mainTab: 'agent' })} replace />;
}

export function AgentLayout() {
  const p = useAgentPreview();
  return (
    <div key={p.fixture.id} className="h-full min-h-0">
      <Outlet />
    </div>
  );
}

export { AgentChat };

function AgentAccess({ children }: { children: ReactNode }) {
  const p = useAgentPreview();
  const { letiId } = useParams({ strict: false });
  if (p.live.enabled && p.live.profile.isPending)
    return (
      <p role="status" className="p-6 text-sm text-muted-foreground">
        Loading agent…
      </p>
    );
  if (p.live.profile.error || !p.capabilities.can_view_activity)
    return (
      <p role="alert" className="p-6 text-sm">
        This agent activity is unavailable.
      </p>
    );
  if (letiId) {
    if (p.live.enabled && p.graphQuery.isPending)
      return (
        <p role="status" className="p-6 text-sm text-muted-foreground">
          Loading agent…
        </p>
      );
    if (!p.graph.agents.some((a) => a.id === letiId && a.leta_id === p.fixture.id && a.box_id))
      return (
        <p role="alert" className="p-6 text-sm">
          This agent is unavailable.
        </p>
      );
  }
  return children;
}

export function ActivityPage() {
  const p = useAgentPreview();
  return (
    <AgentAccess>
      <AgentActivity key={p.activityAgent.id} />
    </AgentAccess>
  );
}

export function AgentBoxPage() {
  const p = useAgentPreview();
  return (
    <AgentAccess>
      <BoxView root={p.fixture.id} />
    </AgentAccess>
  );
}

export function BoxPage() {
  const location = useShellLocation();
  return <BoxView root={location.boxAgent} />;
}

export function StorageEntry() {
  const location = useShellLocation();
  const b = useStorageBrowser();
  if (b.query.isPending)
    return (
      <p role="status" className="p-6 text-sm text-muted-foreground">
        Loading files…
      </p>
    );
  if (b.query.error)
    return (
      <p role="alert" className="p-6 text-sm">
        {b.query.error.message}
      </p>
    );
  if (b.unavailable)
    return (
      <p role="alert" className="p-6 text-sm">
        This storage is unavailable.
      </p>
    );
  return (
    <Navigate
      {...shellTarget({
        ...location,
        storage: b.storage.id,
        folder: location.folder || b.resumeLocation.folder,
        file: location.file || b.resumeLocation.file,
      })}
      replace
    />
  );
}

export { StoragePage };

export function SettingsPage() {
  const { section } = useParams({ strict: false });
  const location = useShellLocation();
  if (!section)
    return (
      <Navigate {...shellTarget({ ...location, view: 'settings', section: 'general' })} replace />
    );
  if (section !== 'general' && section !== 'appearance')
    return (
      <p role="alert" className="p-6 text-sm">
        This settings page is unavailable.
      </p>
    );
  return <AppSettings section={section} />;
}
