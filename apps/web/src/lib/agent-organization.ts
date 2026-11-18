import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createParser } from 'eventsource-parser';
import { toast } from 'sonner';
import { useBackend } from './backend';
import { ApiError } from './agent-api';

export type AgentFolder = { id: string; name: string; parent_id: string | null };
export type AgentLayout = {
  folders: AgentFolder[];
  assignments: Record<string, string>;
  pins: string[];
  order: string[];
  collapsed: string[];
};
type Snapshot = { revision: number; layout: AgentLayout; can_create_agent?: boolean };
export function folderLabel(folders: AgentFolder[], id: string): string {
  const folder = folders.find((item) => item.id === id);
  if (!folder) return '';
  return folder.parent_id
    ? `${folderLabel(folders, folder.parent_id)} / ${folder.name}`
    : folder.name;
}
export function folderDestination(folders: AgentFolder[], id: string, parent: string | null) {
  let depth = 1;
  let current = parent;
  const seen = new Set([id]);
  while (current) {
    if (seen.has(current)) return false;
    seen.add(current);
    const folder = folders.find((f) => f.id === current);
    if (!folder) return false;
    current = folder.parent_id;
    depth++;
  }
  const height = (node: string): number =>
    1 + Math.max(0, ...folders.filter((f) => f.parent_id === node).map((f) => height(f.id)));
  return depth + height(id) - 1 <= 3;
}
export function useAgentOrganization(workspace: string) {
  const backend = useBackend();
  const client = useQueryClient();
  const key = ['agent-sidebar', backend.actorId, workspace];
  const path = `/v1/workspaces/${workspace}/letas/sidebar`;
  const saving = useRef(false);
  const query = useQuery<Snapshot>({
    queryKey: key,
    queryFn: () => backend.api!<Snapshot>(path),
    refetchInterval: 30000,
  });
  useEffect(() => {
    if (!backend.enabled || !backend.request) return;
    const abort = new AbortController();
    let retry: ReturnType<typeof setTimeout>;
    const connect = async () => {
      try {
        const response = await backend.request!(path + '/events', { signal: abort.signal });
        if (!response.body) throw new Error('Empty sidebar stream');
        void client.invalidateQueries({ queryKey: key });
        const parser = createParser({
          onEvent: () => {
            if (!saving.current) void client.invalidateQueries({ queryKey: key });
          },
        });
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        try {
          while (!abort.signal.aborted) {
            const chunk = await reader.read();
            if (chunk.done) break;
            parser.feed(chunk.value);
          }
        } finally {
          await reader.cancel().catch(() => {});
        }
      } catch (error) {
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
          client.removeQueries({ queryKey: key });
          return;
        }
      }
      if (!abort.signal.aborted) retry = setTimeout(() => void connect(), 2000);
    };
    void connect();
    return () => {
      abort.abort();
      clearTimeout(retry);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend.enabled, backend.request, backend.actorId, workspace, client]);
  const mutation = useMutation({
    mutationFn: async (layout: AgentLayout) => {
      const previous = client.getQueryData<Snapshot>(key)!;
      return backend.api!<Snapshot>(path, {
        method: 'PUT',
        body: JSON.stringify({ revision: previous.revision, layout }),
      });
    },
    onMutate: async (layout) => {
      saving.current = true;
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Snapshot>(key)!;
      client.setQueryData(key, { ...previous, layout });
      return previous;
    },
    onSuccess: (next, _layout, previous) =>
      client.setQueryData(key, { ...next, can_create_agent: previous.can_create_agent }),
    onError: (error, _layout, previous) => {
      if (previous) client.setQueryData(key, previous);
      toast.error(error.message);
    },
    onSettled: () => {
      saving.current = false;
      if (backend.enabled) void client.invalidateQueries({ queryKey: key });
    },
  });
  return {
    layout: query.data?.layout ?? {
      folders: [],
      assignments: {},
      pins: [],
      order: [],
      collapsed: [],
    },
    ready: !!query.data,
    error: query.error,
    busy: mutation.isPending,
    canCreate: !!query.data?.can_create_agent,
    save: async (layout: AgentLayout) => {
      if (saving.current || !query.data) {
        const error = new Error('Wait for the sidebar to finish saving.');
        toast.error(error.message);
        throw error;
      }
      saving.current = true;
      return mutation.mutateAsync(layout);
    },
  };
}
