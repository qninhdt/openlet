import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useBackend } from './backend';
import { chatApi, type SidebarLayoutDto } from './chat-api';
import { useRealtime } from './realtime';

export type AgentFolder = { id: string; name: string; parent_id: string | null };
export type AgentLayout = {
  folders: AgentFolder[];
  assignments: Record<string, string>;
  pins: string[];
  order: string[];
  collapsed: string[];
};
type Snapshot = { revision: number; layout: AgentLayout; can_create_agent?: boolean };

function fromDto(dto?: SidebarLayoutDto): AgentLayout {
  return {
    folders: (dto?.folders ?? []).map((f) => ({
      id: f.id,
      name: f.name,
      parent_id: f.parentId ?? null,
    })),
    assignments: dto?.assignments ?? {},
    pins: dto?.pins ?? [],
    order: dto?.order ?? [],
    collapsed: dto?.collapsed ?? [],
  };
}

function toDto(layout: AgentLayout): SidebarLayoutDto {
  return {
    folders: layout.folders.map((f) => ({
      id: f.id,
      name: f.name,
      ...(f.parent_id ? { parentId: f.parent_id } : {}),
    })),
    assignments: layout.assignments,
    pins: layout.pins,
    order: layout.order,
    collapsed: layout.collapsed,
  };
}

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
  const realtime = useRealtime();
  const client = useQueryClient();
  const key = ['agent-sidebar', backend.actorId, workspace];
  const saving = useRef(false);

  const query = useQuery<Snapshot>({
    queryKey: key,
    enabled: backend.enabled && !!backend.api,
    queryFn: async () => {
      const chat = chatApi(backend.api!, workspace);
      const [sidebar, letasPage] = await Promise.all([
        chat.getSidebar(),
        backend.api!<{ can_create_agent?: boolean }>(`/v1/workspaces/${workspace}/letas`).catch(
          () => ({ can_create_agent: false }),
        ),
      ]);
      return {
        revision: Number(sidebar.revision ?? 0),
        layout: fromDto(sidebar.layout),
        can_create_agent: Boolean(letasPage.can_create_agent),
      };
    },
    refetchInterval: 60000,
  });

  // Real-time multi-tab sidebar sync via Centrifugo chat:user#{user_id}.
  useEffect(() => {
    if (!backend.enabled) return;
    return realtime.onChatUserEvent((event) => {
      if (event.type === 'sidebar.updated' && !saving.current) {
        void client.invalidateQueries({ queryKey: key });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend.enabled, realtime, workspace, backend.actorId, client]);

  const mutation = useMutation({
    mutationFn: async (layout: AgentLayout) => {
      const previous = client.getQueryData<Snapshot>(key);
      const chat = chatApi(backend.api!, workspace);
      const updated = await chat.updateSidebar(previous?.revision ?? 0, toDto(layout));
      return {
        revision: Number(updated.revision ?? 0),
        layout: fromDto(updated.layout),
        can_create_agent: previous?.can_create_agent,
      } satisfies Snapshot;
    },
    onMutate: async (layout) => {
      saving.current = true;
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Snapshot>(key);
      if (previous) client.setQueryData(key, { ...previous, layout });
      return previous;
    },
    onSuccess: (next, _layout, previous) =>
      client.setQueryData(key, { ...next, can_create_agent: previous?.can_create_agent }),
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
