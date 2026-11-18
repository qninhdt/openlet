import { useInfiniteQuery } from '@tanstack/react-query';
import type { AgentAppearance } from '@/components/agent-appearance';
import type { Json } from './agent-api';
import { useBackend } from './backend';

export type BoxAgent = {
  id: string;
  leta_id: string;
  box_id: string | null;
  name: string;
  title: string;
  appearance?: AgentAppearance;
  description: string;
  model_id: string | null;
  reasoning_effort?: string | null;
  status: 'working' | 'queued' | 'idle' | 'paused' | 'error' | 'unknown' | 'inactive';
  started_at?: string | null;
  run_id?: string | null;
  heartbeat_at?: string | null;
  tool_name?: string | null;
  activity_kind?: string | null;
};
export type AgentBox = {
  id: string;
  leta_id: string;
  name: string;
  description: string;
  representative_agent_id: string;
  state: string;
};
export type BoxSchedule = {
  id: string;
  leta_id: string;
  creator_agent_id: string;
  target_agent_id: string;
  title: string;
  content: string;
  type: string;
  spec: Record<string, Json>;
  paused: boolean;
  last_delivered_at?: string | null;
};
export type BoxGraph = {
  agents: BoxAgent[];
  boxes: AgentBox[];
  schedules: BoxSchedule[];
  edges: { box_id: string; agent_low_id: string; agent_high_id: string }[];
  roots: string[];
  next_cursor?: string | null;
};
export function useBoxGraph(workspace: string, root: string, enabled: boolean) {
  const backend = useBackend();
  return useInfiniteQuery({
    queryKey: ['box-graph', backend.actorId, workspace, root],
    enabled: backend.enabled && enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({
        ...(root ? { leta_id: root } : {}),
        ...(pageParam ? { cursor: pageParam } : {}),
      });
      return backend.api!<BoxGraph>(`/v1/workspaces/${workspace}/letas/box-view?${params}`);
    },
    getNextPageParam: (page) => page.next_cursor ?? null,
    refetchInterval: enabled ? 5000 : false,
  });
}
