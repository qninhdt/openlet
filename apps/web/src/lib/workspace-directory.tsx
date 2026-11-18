import { createContext, useContext, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate, useParams, useSearch } from '@tanstack/react-router';
import { useMessageSound } from './message-sound';
import { useBackend, usePreferences } from './backend';
import type { AgentResource } from './agent-api';
import type { AgentAppearance } from '@/components/agent-appearance';
import { AppLoading, PageFailure } from '@/components/public/page-state';

export type Workspace = {
  id: string;
  name: string;
  agents: {
    id: string;
    name: string;
    role: string;
    appearance?: AgentAppearance;
    pinned: boolean;
    state?: string;
    preview?: string | null;
    updated_at?: string | null;
    unread_count?: number;
    can_view_activity?: boolean;
    can_edit_settings?: boolean;
    can_delete?: boolean;
    paused?: boolean;
  }[];
};
export type CreateAgent = {
  request_id: string;
  name: string;
  title?: string;
  appearance?: AgentAppearance;
  description: string;
  system_prompt: string;
  model_id: string | null;
  reasoning_effort: string | null;
};
const CreateContext = createContext<
  ((workspace: string, input: CreateAgent) => Promise<string>) | null
>(null);
export function useCreateAgent() {
  return useContext(CreateContext)!;
}
const DirectoryContext = createContext<Workspace[]>([]);
export const useWorkspaces = () => useContext(DirectoryContext);

export function WorkspaceDirectory({ children }: { children: ReactNode }) {
  const { api, actorId, preview } = useBackend();
  const preferences = usePreferences();
  const client = useQueryClient();
  const search = useSearch({ strict: false });
  const params = useParams({ strict: false });
  const directory = useQuery({
    queryKey: ['workspaces', actorId],
    queryFn: async () => {
      const workspaces: { id: string; name: string }[] = [];
      let token = '';
      do {
        const page: { workspaces?: { id: string; name: string }[]; nextPageToken?: string } =
          await api!(
            '/v1/workspaces?' + new URLSearchParams({ page_size: '100', page_token: token }),
          );
        workspaces.push(...(page.workspaces ?? []));
        token = page.nextPageToken ?? '';
      } while (token);
      return { workspaces };
    },
  });
  const selected =
    directory.data?.workspaces.find((w) => w.id === (params.workspaceId ?? search.workspace)) ??
    (params.workspaceId ? undefined : directory.data?.workspaces[0]);
  const agents = useQuery({
    queryKey: ['agents', actorId, selected?.id],
    refetchInterval: 5000,
    enabled: !!selected,
    queryFn: async () => {
      const items: AgentResource[] = [];
      let cursor: string | null = null;
      do {
        const page: { items: AgentResource[]; next_cursor: string | null } = await api!(
          `/v1/workspaces/${selected!.id}/letas${cursor ? `?cursor=${cursor}` : ''}`,
        );
        items.push(...page.items);
        cursor = page.next_cursor;
      } while (cursor);
      return items;
    },
  });
  useMessageSound(
    `${actorId}:${selected?.id ?? ''}`,
    agents.data?.flatMap((agent) =>
      agent.latest_reply_id && agent.latest_reply_at
        ? [
            {
              id: agent.latest_reply_id,
              role: 'assistant' as const,
              created_at: agent.latest_reply_at,
            },
          ]
        : [],
    ),
    // The embedded landing demo stays silent; the standalone playground supports interaction sounds.
    (!preview || window.parent === window) && preferences.messageSound,
  );
  const selectedAgent =
    agents.data?.find((a) => a.id === (params.agentId ?? search.agent)) ??
    (params.agentId ? undefined : agents.data?.[0]);
  async function create(workspace: string, input: CreateAgent) {
    const result = await api!<{ id: string }>(`/v1/workspaces/${workspace}/letas`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
    // Provisioning grants access asynchronously; navigate only after the directory can resolve it.
    for (let attempt = 0; attempt < 60; attempt++) {
      await client.refetchQueries({ queryKey: ['agents', actorId, workspace] });
      if (
        client
          .getQueryData<AgentResource[]>(['agents', actorId, workspace])
          ?.some((a) => a.id === result.id && a.state === 'active')
      )
        return result.id;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error('The agent is still being prepared. Retry to check its progress.');
  }
  if (directory.error || agents.error)
    return (
      <PageFailure
        title="Workspace unavailable"
        message={(directory.error ?? agents.error)!.message}
        retry={() => {
          void directory.refetch();
          void agents.refetch();
        }}
      />
    );
  if (directory.isPending || (selected && agents.isPending))
    return <AppLoading label="Loading agents…" />;
  if ((params.workspaceId && !selected) || (params.agentId && !selectedAgent))
    return (
      <PageFailure
        title="Workspace unavailable"
        message="This workspace or agent does not exist, or you no longer have access."
      />
    );
  if (!selected) return <Navigate to="/workspaces" replace />;
  const workspaces = directory.data!.workspaces.map((w) => ({
    ...w,
    agents:
      w.id === selected.id
        ? agents.data!.map((a) => ({
            id: a.id,
            name: a.name,
            role: a.title ?? '',
            appearance: a.appearance,
            pinned: false,
            state: a.state,
            preview: a.preview,
            updated_at: a.updated_at,
            unread_count: a.unread_count,
            can_view_activity: a.capabilities.can_view_activity,
            can_edit_settings: a.capabilities.can_edit_settings,
            can_delete: a.capabilities.can_delete,
            paused: a.paused,
          }))
        : [],
  }));
  return (
    <CreateContext.Provider value={create}>
      <DirectoryContext.Provider value={workspaces}>{children}</DirectoryContext.Provider>
    </CreateContext.Provider>
  );
}
