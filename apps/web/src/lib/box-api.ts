import { useInfiniteQuery } from '@tanstack/react-query';
import type { AgentAppearance } from '@/components/agent-appearance';
import type { AgentResource, Json } from './agent-api';
import { useBackend } from './backend';

export type BoxAgent = {
  id: string;
  leta_id: string;
  parent_agent_id?: string | null;
  depth?: number;
  box_id: string | null;
  name: string;
  handle?: string;
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
  handle?: string;
  description: string;
  leader_agent_id: string;
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
  additional_links: { box_id: string; agent_low_id: string; agent_high_id: string }[];
  letas: string[];
  next_cursor?: string | null;
};

type RawSubagentRow = {
  id: string;
  leta_id: string;
  parent_agent_id: string | null;
  depth: number;
  name: string;
  title: string;
  handle: string;
  description: string;
  appearance?: AgentAppearance;
  model_id: string | null;
  reasoning_effort?: string | null;
  state: string;
  running?: boolean;
};

export function useBoxGraph(workspace: string, root: string, enabled: boolean) {
  const backend = useBackend();
  return useInfiniteQuery({
    queryKey: ['box-graph', backend.actorId, workspace, root],
    enabled: backend.enabled && enabled && Boolean(backend.api),
    initialPageParam: null as string | null,
    queryFn: async () => {
      const api = backend.api!;
      let letaIds: string[] = [];
      if (root) {
        letaIds = [root];
      } else {
        const list = await api<{ items: AgentResource[] }>(`/v1/workspaces/${workspace}/letas`);
        letaIds = (list.items ?? [])
          .filter((item) => item.can_manage || item.capabilities?.can_view_activity)
          .map((item) => item.id);
      }

      const agents: BoxAgent[] = [];
      const boxes: AgentBox[] = [];
      const schedules: BoxSchedule[] = [];
      const additionalLinks: BoxGraph['additional_links'] = [];

      await Promise.all(
        letaIds.map(async (lid) => {
          const [agentsResp, schedResp] = await Promise.all([
            api<{ items: RawSubagentRow[] }>(
              `/v1/workspaces/${workspace}/letas/${lid}/agents`,
            ).catch(() => ({ items: [] })),
            api<{ items: BoxSchedule[] }>(
              `/v1/workspaces/${workspace}/letas/${lid}/schedules`,
            ).catch(() => ({ items: [] })),
          ]);

          const rows = agentsResp.items ?? [];
          const subagents = rows.filter((r) => r.parent_agent_id !== null && r.state === 'active');
          const groupBoxId = subagents.length > 0 ? `subagents:${lid}` : null;

          if (groupBoxId && subagents.length > 0) {
            boxes.push({
              id: groupBoxId,
              leta_id: lid,
              name: 'Subagents',
              description: 'Active subagents delegated by this Leta',
              leader_agent_id: subagents[0].id,
              state: 'active',
            });
          }

          for (const row of rows) {
            const isSub = row.parent_agent_id !== null;
            const status: BoxAgent['status'] =
              row.state !== 'active' ? 'inactive' : row.running ? 'working' : 'idle';
            agents.push({
              id: row.id,
              leta_id: row.leta_id,
              parent_agent_id: row.parent_agent_id,
              depth: row.depth,
              box_id: isSub && row.state === 'active' ? groupBoxId : null,
              name: row.name,
              handle: row.handle,
              title: row.title,
              appearance: row.appearance,
              description: row.description,
              model_id: row.model_id,
              reasoning_effort: row.reasoning_effort,
              status,
            });
            if (isSub && groupBoxId && row.parent_agent_id && row.parent_agent_id !== lid) {
              additionalLinks.push({
                box_id: groupBoxId,
                agent_low_id: row.parent_agent_id,
                agent_high_id: row.id,
              });
            }
          }

          for (const sc of schedResp.items ?? []) {
            schedules.push(sc);
          }
        }),
      );

      return {
        agents,
        boxes,
        schedules,
        additional_links: additionalLinks,
        letas: letaIds,
        next_cursor: null,
      } satisfies BoxGraph;
    },
    getNextPageParam: () => null,
    refetchInterval: enabled ? 10000 : false,
  });
}
