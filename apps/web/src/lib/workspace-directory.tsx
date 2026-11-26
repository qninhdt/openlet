import { createContext, useContext, useEffect, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate, useParams, useSearch } from '@tanstack/react-router';
import { useMessageSound } from './message-sound';
import { useBackend, usePreferences } from './backend';
import { agentCapabilities, type AgentResource } from './agent-api';
import { chatApi, type ChatConversationDto } from './chat-api';
import { useRealtime } from './realtime';
import type { AgentAppearance } from '@/components/agent-appearance';
import { AppLoading, PageFailure } from '@/components/public/page-state';

export type Workspace = {
  id: string;
  name: string;
  canCreateAgent?: boolean;
  conversations?: ChatConversationDto[];
  agents: {
    id: string;
    name: string;
    role: string;
    handle?: string;
    appearance?: AgentAppearance;
    pinned: boolean;
    state?: string;
    running?: boolean;
    preview?: string | null;
    updated_at?: string | null;
    unread_count?: number;
    conversation_id?: string;
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
  custom_instructions?: string;
  system_prompt?: string;
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
  const realtime = useRealtime();
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
  const workspaceList = directory.data?.workspaces ?? [];
  const selected =
    workspaceList.find((w) => w.id === (params.workspaceId ?? search.workspace)) ??
    (params.workspaceId ? undefined : workspaceList[0]);
  const agents = useQuery({
    queryKey: ['agents', actorId, selected?.id],
    refetchInterval: 15000,
    enabled: !!selected && !!api,
    queryFn: async () => {
      const [letaPage, convPage] = await Promise.all([
        api!<{ items: AgentResource[]; can_create_agent?: boolean }>(
          `/v1/workspaces/${selected!.id}/letas`,
        ),
        chatApi(api!, selected!.id)
          .listConversations(100)
          .catch(() => ({ conversations: [] as ChatConversationDto[] })),
      ]);

      const convByAgent = new Map<string, ChatConversationDto>();
      for (const conv of convPage.conversations ?? []) {
        if (conv.type === 'dm') {
          const agentMember = conv.members?.find((m) => m.actorType === 'agent');
          if (agentMember) convByAgent.set(agentMember.actorId, conv);
        }
      }

      const items: (AgentResource & { conversation_id?: string })[] = (letaPage.items ?? []).map(
        (raw) => {
          const caps = agentCapabilities(raw);
          const dm = convByAgent.get(raw.id);
          const previewTime =
            dm?.lastMsgAt ??
            dm?.lastMessagePreview?.createdAt ??
            dm?.updatedAt ??
            raw.updated_at ??
            null;
          const previewMsgId = dm?.lastMessagePreview?.id ?? dm?.lastMessagePreview?.messageId;
          return {
            ...raw,
            capabilities: caps,
            conversation_id: dm?.id,
            preview: dm?.lastMessagePreview?.snippet ?? raw.preview ?? null,
            updated_at: previewTime,
            unread_count: Number(dm?.unreadCount ?? raw.unread_count ?? 0),
            latest_reply_id:
              dm?.lastMessagePreview?.senderType === 'agent'
                ? (previewMsgId ?? raw.latest_reply_id)
                : raw.latest_reply_id,
            latest_reply_at:
              dm?.lastMessagePreview?.senderType === 'agent'
                ? (previewTime ?? raw.latest_reply_at)
                : raw.latest_reply_at,
          };
        },
      );

      return {
        items,
        conversations: convPage.conversations ?? [],
        canCreateAgent: Boolean(letaPage.can_create_agent),
      };
    },
  });

  // Live refresh unread badges and previews on personal Centrifugo chat events.
  useEffect(() => {
    if (!selected) return;
    return realtime.onChatUserEvent((env) => {
      if (
        env.type === 'message.created' ||
        env.type === 'read_receipt' ||
        env.type === 'conversation.created' ||
        env.type === 'conversation.updated' ||
        env.type === 'conversation.removed'
      ) {
        void client.invalidateQueries({ queryKey: ['agents', actorId, selected.id] });
      }
    });
  }, [realtime, selected, actorId, client]);

  const agentItems = agents.data?.items ?? [];
  useMessageSound(
    `${actorId}:${selected?.id ?? ''}`,
    agents.data
      ? agentItems.flatMap((agent) =>
          agent.latest_reply_id && agent.latest_reply_at
            ? [
                {
                  id: agent.latest_reply_id,
                  role: 'assistant' as const,
                  created_at: agent.latest_reply_at,
                },
              ]
            : [],
        )
      : undefined,
    (!preview || window.parent === window) && preferences.messageSound,
  );
  const selectedAgent =
    agentItems.find((a) => a.id === (params.agentId ?? search.agent)) ??
    (params.agentId ? undefined : agentItems[0]);
  async function create(workspace: string, input: CreateAgent) {
    const payload = {
      request_id: input.request_id,
      name: input.name,
      title: input.title,
      appearance: input.appearance,
      description: input.description,
      custom_instructions: input.custom_instructions ?? input.system_prompt ?? '',
      model_id: input.model_id,
      reasoning_effort: input.reasoning_effort,
    };
    const result = await api!<{ id: string }>(`/v1/workspaces/${workspace}/letas`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    for (let attempt = 0; attempt < 60; attempt++) {
      await client.refetchQueries({ queryKey: ['agents', actorId, workspace] });
      const cached = client.getQueryData<{ items: AgentResource[] }>([
        'agents',
        actorId,
        workspace,
      ]);
      if (cached?.items?.some((a) => a.id === result.id && a.state === 'active')) return result.id;
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
  const workspaces: Workspace[] = workspaceList.map((w) => ({
    ...w,
    canCreateAgent: w.id === selected.id ? agents.data?.canCreateAgent : false,
    conversations: w.id === selected.id ? agents.data?.conversations : [],
    agents:
      w.id === selected.id
        ? (agents.data?.items ?? []).map((a) => {
            const caps = agentCapabilities(a);
            return {
              id: a.id,
              name: a.name,
              role: a.title ?? '',
              handle: a.handle,
              appearance: a.appearance,
              pinned: false,
              state: a.state,
              running: a.running,
              preview: a.preview,
              updated_at: a.updated_at,
              unread_count: a.unread_count,
              conversation_id: a.conversation_id,
              can_view_activity: caps.can_view_activity,
              can_edit_settings: caps.can_edit_settings,
              can_delete: caps.can_delete,
              paused: a.paused,
            };
          })
        : [],
  }));
  return (
    <CreateContext.Provider value={create}>
      <DirectoryContext.Provider value={workspaces}>{children}</DirectoryContext.Provider>
    </CreateContext.Provider>
  );
}
