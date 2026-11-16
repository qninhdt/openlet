import { createContext, useContext, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams, useSearch } from '@tanstack/react-router';
import { workspaces as previewWorkspaces } from './shell-model';
import { useBackend } from './backend';
import type { AgentResource } from './agent-api';
import type { AgentAppearance } from '@/components/agent-appearance';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

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
const DirectoryContext = createContext<Workspace[]>(previewWorkspaces);
export const useWorkspaces = () => useContext(DirectoryContext);

export function WorkspaceDirectory({ children }: { children: ReactNode }) {
  const backend = useBackend();
  return backend.enabled ? (
    <LiveDirectory>{children}</LiveDirectory>
  ) : (
    <PreviewDirectory>{children}</PreviewDirectory>
  );
}
function PreviewDirectory({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>(() => {
    try {
      const saved: unknown = JSON.parse(localStorage.getItem('openlet-preview-agents') ?? 'null');
      if (Array.isArray(saved))
        return previewWorkspaces.map((w) => ({
          ...w,
          agents: [
            ...w.agents,
            ...saved
              .filter(
                (a) =>
                  a &&
                  a.workspace === w.id &&
                  typeof a.id === 'string' &&
                  typeof a.name === 'string',
              )
              .map((a) => ({
                id: a.id,
                name: a.name,
                role: typeof a.role === 'string' ? a.role : 'Assistant',
                appearance: a.appearance,
                pinned: false,
                state: a.state,
              })),
          ],
        }));
    } catch {
      /* Preview starts with the default directory when storage is unavailable. */
    }
    return previewWorkspaces;
  });
  return (
    <CreateContext.Provider
      value={async (workspace, input) => {
        const agent = {
          id: input.request_id,
          name: input.name,
          role: input.title ?? 'Assistant',
          appearance: input.appearance,
          pinned: false,
        };
        const next = workspaces.map((w) =>
          w.id === workspace ? { ...w, agents: [...w.agents, agent] } : w,
        );
        localStorage.setItem(
          'openlet-preview-agents',
          JSON.stringify(
            next.flatMap((w) =>
              w.agents
                .filter(
                  (a) =>
                    !previewWorkspaces
                      .find((p) => p.id === w.id)
                      ?.agents.some((p) => p.id === a.id),
                )
                .map((a) => ({ ...a, workspace: w.id })),
            ),
          ),
        );
        setWorkspaces(next);
        return agent.id;
      }}
    >
      <DirectoryContext.Provider value={workspaces}>{children}</DirectoryContext.Provider>
    </CreateContext.Provider>
  );
}
function LiveDirectory({ children }: { children: ReactNode }) {
  const { api, actorId } = useBackend();
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
      <p role="alert" className="p-8">
        {(directory.error ?? agents.error)?.message}
      </p>
    );
  if (directory.isPending || (selected && agents.isPending))
    return (
      <p role="status" className="p-8 text-muted-foreground">
        Loading agents…
      </p>
    );
  if ((params.workspaceId && !selected) || (params.agentId && !selectedAgent))
    return (
      <p role="alert" className="p-8">
        This workspace or agent is unavailable.
      </p>
    );
  if (!selected)
    return (
      <div className="grid min-h-dvh place-items-center">
        <p className="text-sm text-muted-foreground">There are no workspaces available.</p>
      </div>
    );
  if (!selectedAgent) return <EmptyWorkspace workspace={selected} create={create} />;
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
          }))
        : [],
  }));
  return (
    <CreateContext.Provider value={create}>
      <DirectoryContext.Provider value={workspaces}>{children}</DirectoryContext.Provider>
    </CreateContext.Provider>
  );
}

function EmptyWorkspace({
  workspace,
  create,
}: {
  workspace: { id: string; name: string };
  create: (workspace: string, input: CreateAgent) => Promise<string>;
}) {
  const { api, actorId } = useBackend();
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const creation = useRef<{ name: string; id: string } | null>(null);
  const permission = useQuery({
    queryKey: ['agent-sidebar', actorId, workspace.id],
    queryFn: () =>
      api!<{ can_create_agent: boolean }>(`/v1/workspaces/${workspace.id}/letas/sidebar`),
  });
  return (
    <div className="grid min-h-dvh place-items-center p-6">
      <form
        className="w-full max-w-sm space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim()) return;
          setSaving(true);
          setError('');
          if (creation.current?.name !== name.trim())
            creation.current = { name: name.trim(), id: crypto.randomUUID() };
          try {
            await create(workspace.id, {
              request_id: creation.current.id,
              name: name.trim(),
              description: '',
              system_prompt: '',
              model_id: null,
              reasoning_effort: null,
            });
          } catch (error) {
            setError(error instanceof Error ? error.message : 'Could not create agent.');
          } finally {
            setSaving(false);
          }
        }}
      >
        <h1 className="text-lg font-medium">{workspace.name}</h1>
        <p className="text-sm text-muted-foreground">There are no agents in this workspace yet.</p>
        {permission.data?.can_create_agent && (
          <>
            <Input
              aria-label="Agent name"
              placeholder="Agent name"
              maxLength={255}
              value={name}
              disabled={saving}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <Button type="submit" disabled={saving || !name.trim()}>
              {saving ? 'Preparing agent…' : 'Create agent'}
            </Button>
          </>
        )}
        {(error || permission.error) && (
          <p role="alert" className="text-sm text-destructive">
            {error || permission.error?.message}
          </p>
        )}
      </form>
    </div>
  );
}
