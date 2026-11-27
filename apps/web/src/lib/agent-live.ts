import { useEffect, useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { reduceActivityStream, type StreamingItem } from './agent-stream';
import { useBackend } from './backend';
import { chatApi, toUiChatMessage, type ChatConversationDto } from './chat-api';
import { useRealtime, useRealtimeStatus } from './realtime';
import {
  agentCapabilities,
  normalizeActivityEntry,
  queryString,
  type ActivityEntry,
  type AgentResource,
  type ChatMessage,
  type Cursor,
  type HumanRequest,
  type LiveEvent,
  type Page,
  type RawActivityRow,
  type RunRecord,
} from './agent-api';

export function useAgentLive(
  workspace: string,
  agent: string,
  active: boolean,
  resourceState?: string,
  activityAgent = agent,
) {
  const backend = useBackend();
  const realtime = useRealtime();
  const realtimeStatus = useRealtimeStatus();
  const { api, actorId } = backend;
  const client = useQueryClient();
  const activityOnly = activityAgent !== agent;
  const scope = ['agent', actorId, workspace, agent, activityAgent];
  const path = `/v1/workspaces/${workspace}/letas/${agent}`;
  const enabled = backend.enabled && active && Boolean(api);
  const chatClient = useMemo(() => (api ? chatApi(api, workspace) : null), [api, workspace]);

  const [streaming, setStreaming] = useState<{ scope: string; items: StreamingItem[] }>({
    scope: '',
    items: [],
  });
  const [typingActors, setTypingActors] = useState<Record<string, number>>({});
  const [liveAgentReadSeq, setLiveAgentReadSeq] = useState<{ convId: string; seq: number }>({
    convId: '',
    seq: 0,
  });
  const streamScope = [actorId, workspace, agent, activityAgent].join(':');

  const profile = useQuery({
    queryKey: [...scope, 'profile'],
    enabled,
    queryFn: async () => {
      const raw = await api!<AgentResource>(path);
      return { ...raw, capabilities: agentCapabilities(raw) };
    },
    refetchInterval: enabled ? (resourceState === 'provisioning' ? 1500 : 30000) : false,
  });

  const manage = Boolean(profile.data?.capabilities?.can_view_activity);

  const dmConversation = useQuery<ChatConversationDto>({
    queryKey: [...scope, 'dm-conversation'],
    enabled: enabled && !activityOnly && Boolean(chatClient),
    staleTime: 60_000,
    queryFn: () => chatClient!.createOrGetDM({ type: 'agent', id: agent }),
  });

  const conversationId = dmConversation.data?.id ?? '';

  const chat = useInfiniteQuery({
    queryKey: [...scope, 'chat', conversationId],
    enabled: enabled && !activityOnly && Boolean(conversationId && chatClient),
    initialPageParam: null as number | null,
    queryFn: async ({ pageParam }) => {
      const page = await chatClient!.listMessages(conversationId, {
        ...(pageParam ? { beforeSeq: pageParam } : {}),
        limit: 40,
      });
      const items: ChatMessage[] = (page.messages ?? []).map((m) => toUiChatMessage(m, actorId));
      const oldestSeq = items.reduce(
        (min, m) => (m.seq && (min === 0 || m.seq < min) ? m.seq : min),
        0,
      );
      return {
        items,
        next_cursor: page.hasBefore && oldestSeq > 1 ? oldestSeq : null,
      };
    },
    getNextPageParam: (page) => page.next_cursor,
    refetchInterval: enabled ? 30000 : false,
  });

  const requests = useInfiniteQuery({
    queryKey: [...scope, 'requests'],
    enabled: enabled && !activityOnly,
    initialPageParam: null as Cursor | null,
    queryFn: ({ pageParam }) =>
      api!<Page<HumanRequest>>(
        `/v1/hitl-requests?workspace_id=${workspace}&leta_id=${agent}&${queryString(pageParam, 'cursor')}`,
      ),
    getNextPageParam: (page) => page.next_cursor as Cursor | null,
    refetchInterval: enabled ? 30000 : false,
  });

  const activity = useInfiniteQuery({
    queryKey: [...scope, 'activity'],
    enabled: enabled && manage,
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const qs = pageParam ? `?before=${encodeURIComponent(pageParam)}` : '';
      const raw = await api!<Page<RawActivityRow | ActivityEntry>>(
        `${path}/agents/${activityAgent}/activity${qs}`,
      );
      const rawItems = raw.items ?? [];
      const items = rawItems
        .map(normalizeActivityEntry)
        .filter((e): e is ActivityEntry => e !== null);
      let nextCursor = raw.next_cursor ?? null;
      if (!nextCursor && rawItems.length >= 50) {
        const oldestSeq = items.reduce(
          (min, e) => (e.seq > 0 && (min === 0 || e.seq < min) ? e.seq : min),
          0,
        );
        if (oldestSeq > 1) nextCursor = String(oldestSeq);
      }
      return { items, next_cursor: nextCursor };
    },
    getNextPageParam: (page) => page.next_cursor as string | null,
    refetchInterval: enabled && manage ? 30000 : false,
  });

  const runs = useQuery({
    queryKey: [...scope, 'runs'],
    enabled: enabled && manage,
    queryFn: () => api!<{ items: RunRecord[] }>(`${path}/agents/${activityAgent}/runs?limit=10`),
    refetchInterval: enabled && manage ? 15000 : false,
  });

  const settings = useQuery({
    queryKey: [...scope, 'settings'],
    enabled: enabled && manage,
    queryFn: async () => {
      const data = await api!<{
        custom_instructions?: string;
        model_id: string;
        reasoning_effort: string | null;
      }>(`${path}/agents/${activityAgent}`);
      return {
        custom_instructions: data.custom_instructions ?? '',
        model_id: data.model_id,
        reasoning_effort: data.reasoning_effort ?? '',
      };
    },
  });

  // Subscribe lazily to active conversation room chat:conv:{conversationId}.
  useEffect(() => {
    if (!enabled || activityOnly || !conversationId || !chatClient) return;
    return realtime.subscribe(
      `chat:conv:${conversationId}`,
      async () => (await chatClient.getRealtimeToken(conversationId)).token,
      {
        onEvent: (env) => {
          if (env.type === 'typing') {
            const actorKey = `${String(env.data.actor_type ?? '')}:${String(env.data.actor_id ?? '')}`;
            if (env.data.actor_id === actorId) return;
            if (env.data.active) {
              setTypingActors((cur) => ({ ...cur, [actorKey]: Date.now() }));
            } else {
              setTypingActors((cur) => {
                const next = { ...cur };
                delete next[actorKey];
                return next;
              });
            }
            return;
          }
          if (env.type === 'read_receipt') {
            if (env.data.actor_type === 'agent') {
              const seq = Number(env.data.last_read_seq ?? env.data.seq ?? 0);
              if (seq > 0) {
                setLiveAgentReadSeq((cur) => ({
                  convId: conversationId,
                  seq: cur.convId === conversationId ? Math.max(cur.seq, seq) : seq,
                }));
              }
            }
            void client.invalidateQueries({ queryKey: [...scope, 'dm-conversation'] });
            void client.invalidateQueries({ queryKey: [...scope, 'chat', conversationId] });
            void client.invalidateQueries({ queryKey: [...scope, 'inbox'] });
            void client.invalidateQueries({ queryKey: ['agents', actorId, workspace] });
            return;
          }
          if (
            env.type === 'message.created' ||
            env.type === 'message.updated' ||
            env.type === 'message.deleted' ||
            env.type === 'reaction.added' ||
            env.type === 'reaction.removed'
          ) {
            void client.invalidateQueries({ queryKey: [...scope, 'chat', conversationId] });
            void client.invalidateQueries({ queryKey: ['agents', actorId, workspace] });
          }
        },
        onRecovered: (recovered) => {
          if (!recovered) {
            void client.invalidateQueries({ queryKey: [...scope, 'chat', conversationId] });
          }
        },
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, activityOnly, conversationId, chatClient, realtime, actorId, workspace, client]);

  // Clear stale typing indicators after 8s.
  useEffect(() => {
    if (!Object.keys(typingActors).length) return;
    const timer = setInterval(() => {
      const cutoff = Date.now() - 8000;
      setTypingActors((cur) => {
        const next: Record<string, number> = {};
        let changed = false;
        for (const [k, ts] of Object.entries(cur)) {
          if (ts > cutoff) next[k] = ts;
          else changed = true;
        }
        return changed ? next : cur;
      });
    }, 2000);
    return () => clearInterval(timer);
  }, [typingActors]);

  // Subscribe to leta:activity:{leta_id} when user can manage this Leta.
  useEffect(() => {
    if (!enabled || !manage || !api) return;
    return realtime.subscribe(
      `leta:activity:${agent}`,
      async () => {
        const res = await api<{ token: string }>(`${path}/realtime-token`, {
          method: 'POST',
          body: '{}',
        });
        return res.token;
      },
      {
        onEvent: (env) => {
          const liveEvent: LiveEvent = { type: env.type, data: env.data as LiveEvent['data'] };
          if (env.type.startsWith('stream.') || env.type === 'run.finished') {
            setStreaming((current) => {
              const items = reduceActivityStream(
                current.scope === streamScope ? current.items : [],
                liveEvent,
                activityAgent,
              );
              return current.scope === streamScope && current.items === items
                ? current
                : { scope: streamScope, items };
            });
          }
          if (
            env.type.startsWith('activity.') ||
            env.type === 'run.started' ||
            env.type === 'run.finished'
          ) {
            void client.invalidateQueries({ queryKey: [...scope, 'activity'] });
            void client.invalidateQueries({ queryKey: [...scope, 'runs'] });
            void client.invalidateQueries({ queryKey: [...scope, 'profile'] });
            void client.invalidateQueries({ queryKey: ['box-graph', actorId, workspace] });
          }
          if (
            env.type === 'subagent.spawned' ||
            env.type === 'subagent.stopped' ||
            env.type === 'schedule.updated'
          ) {
            void client.invalidateQueries({ queryKey: ['box-graph', actorId, workspace] });
          }
          if (env.type === 'hitl.updated') {
            void client.invalidateQueries({ queryKey: [...scope, 'requests'] });
            void client.invalidateQueries({ queryKey: ['human-requests', actorId] });
          }
        },
        onRecovered: (recovered) => {
          if (!recovered) {
            setStreaming({ scope: streamScope, items: [] });
            void client.invalidateQueries({ queryKey: [...scope, 'activity'] });
            void client.invalidateQueries({ queryKey: [...scope, 'runs'] });
          }
        },
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    enabled,
    manage,
    api,
    agent,
    activityAgent,
    path,
    realtime,
    streamScope,
    actorId,
    workspace,
    client,
  ]);

  // Also listen to personal leta:user#{actorId} for HITL updates even for non-owners.
  useEffect(() => {
    if (!enabled) return;
    return realtime.onLetaUserEvent((env) => {
      if (env.type === 'hitl.updated') {
        void client.invalidateQueries({ queryKey: [...scope, 'requests'] });
        void client.invalidateQueries({ queryKey: ['human-requests', actorId] });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, realtime, actorId, client]);

  const latestRun = runs.data?.items?.[0] ?? null;
  const dmAgentReadSeq = Number(
    dmConversation.data?.members?.find((m) => m.actorType === 'agent' && m.actorId === agent)
      ?.lastReadSeq ?? 0,
  );
  const agentLastReadSeq = Math.max(
    dmAgentReadSeq,
    liveAgentReadSeq.convId === conversationId ? liveAgentReadSeq.seq : 0,
  );
  const isTyping = Object.keys(typingActors).length > 0;
  const isWorking = Boolean(profile.data?.running || latestRun?.status === 'running' || isTyping);

  const connectionLabel =
    realtimeStatus === 'connected'
      ? 'Live'
      : realtimeStatus === 'reconnecting'
        ? 'Reconnecting'
        : 'Connecting';

  return {
    ...backend,
    activityAgent,
    activityOnly,
    scope,
    path,
    conversationId,
    agentLastReadSeq,
    chatClient,
    profile,
    chat,
    requests,
    activity,
    runs,
    latestRun,
    settings,
    processing: {
      data: {
        working: isWorking,
        run_id: latestRun?.status === 'running' ? latestRun.id : null,
      },
    },
    isTyping,
    connection: connectionLabel,
    manage,
    streaming: streaming.scope === streamScope ? streaming.items : [],
    refresh: () => client.invalidateQueries({ queryKey: scope }),
  };
}
