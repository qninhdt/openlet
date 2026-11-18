import { useEffect, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { createParser } from 'eventsource-parser';
import { reduceActivityStream, type StreamingItem } from './agent-stream';
import { useBackend } from './backend';
import {
  ApiError,
  queryString,
  type AgentResource,
  type ChatMessage,
  type HumanRequest,
  type ActivityEntry,
  type Page,
  type Cursor,
  type LiveEvent,
} from './agent-api';

export function useAgentLive(
  workspace: string,
  agent: string,
  active: boolean,
  resourceState?: string,
  activityAgent = agent,
) {
  const backend = useBackend();
  const { api, request, actorId } = backend;
  const client = useQueryClient();
  const activityOnly = activityAgent !== agent;
  const scope = ['agent', actorId, workspace, agent, activityAgent];
  const path = `/v1/workspaces/${workspace}/letas/${agent}`;
  const enabled = backend.enabled && active;
  const [connection, setConnection] = useState('Connecting');
  const [streaming, setStreaming] = useState<{ scope: string; items: StreamingItem[] }>({
    scope: '',
    items: [],
  });
  const streamScope = [actorId, workspace, agent, activityAgent].join(':');
  const profile = useQuery({
    queryKey: [...scope, 'profile'],
    enabled,
    queryFn: () => api!<AgentResource>(path),
    refetchInterval: enabled ? (resourceState === 'provisioning' ? 1000 : 30000) : false,
  });
  const manage = !!profile.data?.capabilities.can_view_activity;
  const processing = useQuery({
    queryKey: [...scope, 'processing'],
    enabled: enabled && !activityOnly,
    queryFn: () => api!<{ working: boolean; run_id: string | null }>(path + '/processing'),
    refetchInterval: enabled ? 3000 : false,
  });
  const chat = useInfiniteQuery({
    queryKey: [...scope, 'chat'],
    enabled: enabled && !activityOnly,
    initialPageParam: null as Cursor | null,
    queryFn: ({ pageParam }) =>
      api!<Page<ChatMessage>>(`${path}/messages?${queryString(pageParam)}`),
    getNextPageParam: (page) => page.next_cursor as Cursor | null,
    refetchInterval: enabled ? 30000 : false,
  });
  const requests = useInfiniteQuery({
    queryKey: [...scope, 'requests'],
    enabled: enabled && !activityOnly,
    initialPageParam: null as Cursor | null,
    queryFn: ({ pageParam }) =>
      api!<Page<HumanRequest>>(
        `/v1/hitl-requests?workspace_id=${workspace}&leta_id=${agent}&${queryString(pageParam)}`,
      ),
    getNextPageParam: (page) => page.next_cursor as Cursor | null,
    refetchInterval: enabled ? 30000 : false,
  });
  const activity = useInfiniteQuery({
    queryKey: [...scope, 'activity'],
    enabled: enabled && manage,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api!<Page<ActivityEntry>>(
        `${path}/agents/${activityAgent}/activity?${queryString(pageParam)}`,
      ),
    getNextPageParam: (page) => page.next_cursor as string | null,
    refetchInterval: enabled && manage ? 30000 : false,
  });
  const settings = useQuery({
    queryKey: [...scope, 'settings'],
    enabled: enabled && manage,
    queryFn: () =>
      api!<{ system_prompt: string; model_id: string; reasoning_effort: string }>(
        `${path}/agents/${activityAgent}/settings`,
      ),
  });

  useEffect(() => {
    if (!enabled || !request) return;
    const abort = new AbortController();
    let refresh: ReturnType<typeof setTimeout> | undefined;
    const invalidate = () => {
      if (refresh) return;
      refresh = setTimeout(() => {
        refresh = undefined;
        void client.invalidateQueries({ queryKey: scope });
        void client.invalidateQueries({ queryKey: ['box-graph', actorId, workspace] });
      }, 180);
    };
    const connect = async (owner: boolean) => {
      let cursor = '';
      let retries = 0;
      while (!abort.signal.aborted) {
        let reader: ReadableStreamDefaultReader<string> | undefined;
        try {
          const response = await request(path + (owner ? '/events' : '/messages/events'), {
            signal: abort.signal,
            headers: cursor ? { 'Last-Event-ID': cursor } : {},
          });
          if (!response.body) throw new Error('Empty event stream');
          setConnection('Live');
          retries = 0;
          invalidate();
          if (owner) setStreaming({ scope: streamScope, items: [] });
          const parser = createParser({
            maxBufferSize: 1_000_000,
            onError: () => {
              cursor = '';
              invalidate();
            },
            onEvent: (event) => {
              if (event.id) cursor = event.id;
              const data = JSON.parse(event.data) as LiveEvent;
              if (data.name === 'openlet.resync_required') {
                cursor = '';
                invalidate();
              }
              if (owner) {
                if (data.name === 'openlet.resync_required') {
                  setStreaming({ scope: streamScope, items: [] });
                } else
                  setStreaming((current) => ({
                    scope: streamScope,
                    items: reduceActivityStream(
                      current.scope === streamScope ? current.items : [],
                      data,
                      activityAgent,
                    ),
                  }));
              }
              // SQL is canonical; token deltas never become addressed chat deliveries.
              if (
                data.type === 'CUSTOM' ||
                data.type === 'RUN_STARTED' ||
                data.type === 'RUN_FINISHED' ||
                data.type === 'RUN_ERROR' ||
                data.type === 'TOOL_CALL_RESULT'
              )
                invalidate();
            },
          });
          reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          while (!abort.signal.aborted) {
            const chunk = await reader.read();
            if (chunk.done) break;
            parser.feed(chunk.value);
          }
        } catch (error) {
          if (abort.signal.aborted) return;
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
            client.removeQueries({ queryKey: [...scope, owner ? 'activity' : 'chat'] });
            if (owner) client.removeQueries({ queryKey: ['box-graph', actorId, workspace] });
            if (!owner) client.removeQueries({ queryKey: [...scope, 'requests'] });
            client.removeQueries({ queryKey: [...scope, 'settings'] });
            client.removeQueries({ queryKey: [...scope, 'inbox'] });
            void client.invalidateQueries({ queryKey: [...scope, 'profile'] });
            setConnection('Access changed');
            return;
          }
        } finally {
          await reader?.cancel().catch(() => {});
        }
        if (!abort.signal.aborted) {
          setConnection('Reconnecting');
          invalidate();
          await new Promise<void>((resolve) => {
            const done = () => {
              clearTimeout(timer);
              abort.signal.removeEventListener('abort', done);
              resolve();
            };
            const timer = setTimeout(done, Math.min(1000 * 2 ** retries++, 15000));
            abort.signal.addEventListener('abort', done, { once: true });
          });
        }
      }
    };
    if (!activityOnly) void connect(false);
    if (manage) void connect(true);
    return () => {
      abort.abort();
      clearTimeout(refresh);
    };
    // Scope values are stable primitive identities; query results do not restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, request, actorId, workspace, agent, activityAgent, activityOnly, manage, client]);
  return {
    ...backend,
    activityAgent,
    activityOnly,
    scope,
    path,
    profile,
    chat,
    requests,
    activity,
    settings,
    processing,
    connection,
    manage,
    streaming: streaming.scope === streamScope ? streaming.items : [],
    refresh: () => client.invalidateQueries({ queryKey: scope }),
  };
}
