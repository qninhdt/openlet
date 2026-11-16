import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Handle,
  Position,
  MarkerType,
  useReactFlow,
  type Node,
  type NodeProps,
  type Edge,
} from '@xyflow/react';
import {
  ChevronDown,
  Box,
  Clock3,
  Search,
  Scan,
  Plus,
  Minus,
  Star,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  Pause,
  X,
  ArrowUpRight,
  Inbox,
} from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { agentAppearance } from '@/components/agent-appearance';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
} from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { scheduleTiming } from '@/lib/schedule-presentation';
import type { AgentBox, BoxAgent, BoxGraph, BoxSchedule } from '@/lib/box-api';
import { cn } from '@/lib/utils';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/agent-api';
import { useAgentPreview } from './agent-preview';
import '@xyflow/react/dist/style.css';
import './box-view.css';

const statusNames: Record<BoxAgent['status'], string> = {
  working: 'Working',
  queued: 'Queued',
  idle: 'Idle',
  paused: 'Paused',
  error: 'Error',
  unknown: 'Unknown',
  inactive: 'Inactive',
};
const actions: Record<string, string> = {
  file_read: 'Reading files',
  file_write: 'Writing a file',
  file_edit: 'Editing a file',
  file_search: 'Searching files',
  file_semantic_search: 'Searching files',
  execute: 'Running a command',
  inbox_send: 'Sending a message',
  inbox_read: 'Reading inbox',
  history_search: 'Searching history',
};
function agentActivityLabel(agent: BoxAgent) {
  return agent.status === 'working' && agent.activity_kind === 'tool_call' && agent.tool_name
    ? (actions[agent.tool_name] ?? 'Using a tool')
    : statusNames[agent.status];
}
function Status({ agent }: { agent: BoxAgent }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (agent.status !== 'working' || !agent.started_at) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [agent.status, agent.started_at]);
  const elapsed = agent.started_at
    ? Math.max(0, Math.floor((now - Date.parse(agent.started_at)) / 1000))
    : 0;
  const duration =
    elapsed >= 60
      ? `${Math.floor(elapsed / 60)}m ${String(elapsed % 60).padStart(2, '0')}s`
      : `${elapsed}s`;
  const Icon =
    agent.status === 'working'
      ? LoaderCircle
      : agent.status === 'error' || agent.status === 'unknown'
        ? CircleAlert
        : agent.status === 'paused'
          ? Pause
          : agent.status === 'queued'
            ? Inbox
            : null;
  return (
    <span
      className={cn(
        'inline-flex w-full min-w-0 items-center gap-1.5 text-caption text-muted-foreground',
        agent.status === 'error' && 'text-destructive',
      )}
    >
      {Icon && (
        <Icon
          className={cn(
            'size-3.5 shrink-0',
            agent.status === 'working' && 'motion-safe:animate-spin',
          )}
        />
      )}
      <span className="truncate">{agentActivityLabel(agent)}</span>
      {agent.status === 'working' && agent.started_at && (
        <span className="ml-auto shrink-0 tabular-nums">{duration}</span>
      )}
    </span>
  );
}
type GraphNode = Node<{
  agent?: BoxAgent;
  box?: AgentBox;
  schedule?: BoxSchedule;
  accent: string;
  representative?: boolean;
  working?: number;
  total?: number;
  onOpen?: () => void;
  onSchedule?: () => void;
  onCollapse?: () => void;
  collapsed?: boolean;
}>;
function GraphCard({ data, selected }: NodeProps<GraphNode>) {
  const a = data.agent;
  return (
    <article
      data-box-agent={a?.id}
      data-status={a?.status}
      className={cn(
        'flex h-full flex-col rounded-xl border bg-card text-card-foreground shadow-sm',
        selected && 'outline-2 outline-(--agent-color)',
        a?.status === 'error' && 'border-destructive/60',
      )}
      style={{ '--agent-color': data.accent } as CSSProperties}
    >
      <Handle type="target" id="left" position={Position.Left} className="invisible" />
      <Handle type="source" id="bottom" position={Position.Bottom} className="invisible" />
      <Handle type="target" id="top" position={Position.Top} className="invisible" />
      <Handle type="source" id="left-out" position={Position.Left} className="invisible" />
      <Handle type="source" id="right" position={Position.Right} className="invisible" />
      {a ? (
        <>
          <button
            className="nodrag flex min-w-0 items-center gap-3 rounded-t-xl px-3.5 pt-3.5 pb-3 text-left outline-ring focus-visible:outline-2"
            onClick={data.onOpen}
            aria-label={`Open ${a.name} activity`}
          >
            <AgentAvatar
              name={a.name}
              appearance={a.appearance}
              working={a.status === 'working'}
              className="size-11"
            />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="flex min-w-0 items-center gap-1.5 text-sm font-medium">
                <span className="truncate">{a.name}</span>
                {data.representative && (
                  <Star
                    className="size-3 shrink-0 text-muted-foreground"
                    aria-label="Representative"
                  />
                )}
              </span>
              <span className="truncate text-caption text-muted-foreground">{a.title}</span>
            </span>
            <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground" />
          </button>
          <div className="flex min-w-0 flex-1 items-center border-t px-3.5 py-3">
            <Status agent={a} />
          </div>
        </>
      ) : data.schedule ? (
        <>
          <button
            className="nodrag flex min-w-0 items-center gap-2.5 rounded-t-xl px-3.5 pt-3.5 pb-3 text-left outline-ring focus-visible:outline-2"
            onClick={data.onSchedule}
            aria-label={`Inspect ${data.schedule.title}`}
          >
            <Clock3 className="size-5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {data.schedule.title || 'Scheduled instruction'}
            </span>
            {data.schedule.paused && <Pause className="size-3.5 text-muted-foreground" />}
          </button>
          <div className="flex flex-col gap-1.5 border-t px-3.5 py-3 text-caption">
            <span className="line-clamp-2">{scheduleTiming(data.schedule.spec)}</span>
            <span className="truncate text-muted-foreground">
              {data.schedule.paused ? 'Paused' : String(data.schedule.spec.timezone ?? 'UTC')}
            </span>
          </div>
        </>
      ) : null}
    </article>
  );
}
function BoxFrame({ data }: NodeProps<GraphNode>) {
  return (
    <section
      aria-label={`Box ${data.box!.name}`}
      className="h-full rounded-2xl border border-(--box-border) bg-(--box-surface)"
      style={
        {
          '--box-border': `color-mix(in oklab, ${data.accent} 35%, var(--border))`,
          '--box-surface': `color-mix(in oklab, ${data.accent} 3%, var(--background))`,
        } as CSSProperties
      }
    >
      <Handle type="target" id="left" position={Position.Left} className="invisible" />
      <Handle type="source" id="left-out" position={Position.Left} className="invisible" />
      <Handle type="source" id="right" position={Position.Right} className="invisible" />
      <Handle type="source" id="bottom" position={Position.Bottom} className="invisible" />
      <Handle type="target" id="top" position={Position.Top} className="invisible" />
      <button
        type="button"
        aria-label={`${data.collapsed ? 'Expand' : 'Collapse'} box ${data.box!.name}`}
        aria-expanded={!data.collapsed}
        onClick={data.onCollapse}
        className="nodrag flex w-full items-center gap-2.5 rounded-t-2xl px-5 py-4 text-left outline-ring focus-visible:outline-2"
      >
        <Box className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{data.box!.name}</span>
        <span className="text-caption text-muted-foreground">
          {data.working
            ? `${data.working} working`
            : `${data.total} ${data.total === 1 ? 'agent' : 'agents'}`}
        </span>
        <ChevronDown
          className={cn('size-3.5 text-muted-foreground', data.collapsed && '-rotate-90')}
        />
      </button>
    </section>
  );
}
const nodeTypes = { agent: GraphCard, box: BoxFrame, schedule: GraphCard };

function diagram(
  graph: BoxGraph,
  open: (agent: BoxAgent) => void,
  inspect: (schedule: BoxSchedule) => void,
  collapsed: string[],
  toggle: (id: string) => void,
  mobile: boolean,
) {
  const nodes: GraphNode[] = [],
    edges: Edge[] = [];
  let top = 24;
  for (const rootId of graph.roots) {
    const root = graph.agents.find((a) => a.id === rootId);
    if (!root) continue;
    const accent = agentAppearance(root.name, root.appearance).background;
    nodes.push({
      id: root.id,
      type: 'agent',
      position: { x: mobile ? 48 : 32, y: mobile ? top : top + 72 },
      style: { width: 236, height: 126 },
      data: { agent: root, accent, onOpen: () => open(root) },
    });
    const schedules = graph.schedules.filter((s) => s.leta_id === rootId);
    let boxTop = mobile ? top + 188 : top;
    for (const box of graph.boxes.filter((b) => b.leta_id === rootId)) {
      const members = graph.agents.filter((a) => a.box_id === box.id);
      const columns = mobile ? 1 : Math.min(2, Math.max(1, members.length));
      const closed = collapsed.includes(box.id);
      const height = closed ? 56 : 80 + Math.ceil(members.length / columns) * 154;
      nodes.push({
        id: box.id,
        type: 'box',
        position: { x: mobile ? 24 : 388, y: boxTop },
        style: { width: columns * 260 + 24, height },
        selectable: false,
        data: {
          box,
          accent,
          collapsed: closed,
          onCollapse: () => toggle(box.id),
          working: members.filter((a) => a.status === 'working').length,
          total: members.length,
        },
      });
      members.forEach((agent, index) => {
        nodes.push({
          id: agent.id,
          hidden: closed,
          type: 'agent',
          parentId: box.id,
          extent: 'parent',
          position: { x: 24 + (index % columns) * 260, y: 64 + Math.floor(index / columns) * 154 },
          style: { width: 236, height: 126 },
          data: {
            agent,
            accent,
            representative: agent.id === box.representative_agent_id,
            onOpen: () => open(agent),
          },
        });
      });
      edges.push({
        id: `representative:${box.id}`,
        source: root.id,
        target: closed ? box.id : box.representative_agent_id,
        type: 'smoothstep',
        sourceHandle: mobile ? 'left-out' : 'right',
        targetHandle: 'left',
        style: { stroke: accent, strokeWidth: 1.5 },
      });
      boxTop += height + 40;
    }
    schedules.forEach((schedule, index) => {
      const target = graph.agents.find((a) => a.id === schedule.target_agent_id);
      nodes.push({
        id: schedule.id,
        type: 'schedule',
        position: { x: mobile ? 48 : 32, y: (mobile ? boxTop : top + 260) + index * 164 },
        style: { width: 236, height: 140 },
        data: { schedule, accent, onSchedule: () => inspect(schedule) },
      });
      edges.push({
        id: `schedule:${schedule.id}`,
        source: schedule.id,
        target:
          target?.box_id && collapsed.includes(target.box_id)
            ? target.box_id
            : schedule.target_agent_id,
        sourceHandle: 'right',
        targetHandle: 'left',
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed, color: accent },
        style: { stroke: accent, strokeDasharray: '4 5', opacity: schedule.paused ? 0.35 : 0.75 },
      });
    });
    top = Math.max((mobile ? boxTop : top + 260) + schedules.length * 164, boxTop) + 80;
  }
  graph.edges
    .filter((edge) => !collapsed.includes(edge.box_id))
    .forEach((edge) =>
      edges.push({
        id: `communication:${edge.agent_low_id}:${edge.agent_high_id}`,
        source: edge.agent_low_id,
        target: edge.agent_high_id,
        sourceHandle:
          nodes.find((n) => n.id === edge.agent_low_id)?.position.x ===
          nodes.find((n) => n.id === edge.agent_high_id)?.position.x
            ? 'bottom'
            : 'right',
        targetHandle:
          nodes.find((n) => n.id === edge.agent_low_id)?.position.x ===
          nodes.find((n) => n.id === edge.agent_high_id)?.position.x
            ? 'top'
            : 'left',
        type: 'smoothstep',
        style: { stroke: 'var(--muted-foreground)', opacity: 0.55 },
      }),
    );
  const present = new Set(nodes.map((n) => n.id));
  return { nodes, edges: edges.filter((e) => present.has(e.source) && present.has(e.target)) };
}

function ScheduleDetail({ schedule, onClose }: { schedule: BoxSchedule; onClose: () => void }) {
  const p = useAgentPreview();
  const detail = useQuery({
    queryKey: ['box-schedule', p.actorId, p.workspace.id, schedule.leta_id, schedule.id],
    enabled: p.live.enabled,
    queryFn: () =>
      p.live.api!<{ upcoming?: string[] }>(
        `/v1/workspaces/${p.workspace.id}/letas/${schedule.leta_id}/schedules/${schedule.id}`,
      ),
  });
  const target = p.graph.agents.find((a) => a.id === schedule.target_agent_id);
  return (
    <aside
      aria-label="Schedule details"
      className="nowheel nodrag absolute right-3 bottom-16 left-3 flex max-h-[65%] flex-col gap-4 overflow-y-auto rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg sm:left-auto sm:w-80"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">{schedule.title}</h3>
          <p className="mt-1 text-caption text-muted-foreground">
            {schedule.paused ? 'Paused' : 'Active'} · {String(schedule.spec.timezone ?? 'UTC')}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Close schedule details"
          onClick={onClose}
        >
          <X />
        </Button>
      </div>
      <p className="text-sm">{scheduleTiming(schedule.spec)}</p>
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{schedule.content}</p>
      {target && (
        <div className="flex items-center gap-2 border-t pt-3 text-caption">
          <AgentAvatar name={target.name} appearance={target.appearance} className="size-5" />
          <span className="truncate">
            {target.name} · {target.title}
          </span>
        </div>
      )}
      {detail.isFetching && (
        <p className="text-caption text-muted-foreground">Loading upcoming runs…</p>
      )}
      {detail.error && (
        <p role="alert" className="text-caption text-destructive">
          {detail.error.message}
        </p>
      )}
      {!!detail.data?.upcoming?.length && (
        <ol className="flex flex-col gap-2 border-t pt-3 text-caption tabular-nums">
          {detail.data.upcoming.slice(0, 3).map((at) => (
            <li key={at}>{new Date(at).toLocaleString()}</li>
          ))}
        </ol>
      )}
      {schedule.last_delivered_at && (
        <p className="text-caption text-muted-foreground">
          Last delivered {new Date(schedule.last_delivered_at).toLocaleString()}
        </p>
      )}
    </aside>
  );
}
function Canvas({ graph, viewKey }: { graph: BoxGraph; viewKey: string }) {
  const p = useAgentPreview();
  const { openLeti, openRootActivity } = p;
  const flow = useReactFlow<GraphNode>();
  const mobile = useIsMobile(1120);
  const [saved] = useState(() => p.boxViews.get(viewKey));
  const [schedule, setSchedule] = useState<BoxSchedule | null>(
    () => graph.schedules.find((s) => s.id === saved?.schedule) ?? null,
  );
  const [collapsed, setCollapsed] = useState<string[]>(() => saved?.collapsed ?? []);
  useEffect(() => {
    p.boxViews.set(viewKey, { ...p.boxViews.get(viewKey), collapsed, schedule: schedule?.id });
  }, [p.boxViews, viewKey, collapsed, schedule?.id]);
  const data = useMemo(
    () =>
      diagram(
        graph,
        (agent) => (agent.box_id ? openLeti(agent) : openRootActivity(agent.id)),
        setSchedule,
        collapsed,
        (id) =>
          setCollapsed((current) =>
            current.includes(id) ? current.filter((b) => b !== id) : [...current, id],
          ),
        mobile,
      ),
    [graph, openLeti, openRootActivity, collapsed, mobile],
  );
  const working = graph.agents.filter((a) => a.status === 'working');
  return (
    <div className="box-canvas relative h-full min-h-0 bg-background">
      <ReactFlow<GraphNode>
        key={mobile ? 'mobile' : 'desktop'}
        nodes={data.nodes}
        edges={data.edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        edgesFocusable={false}
        defaultEdgeOptions={{ selectable: false, focusable: false, interactionWidth: 0 }}
        fitView={!mobile && !saved?.viewport}
        defaultViewport={saved?.viewport ?? { x: 12, y: 60, zoom: 1 }}
        onMoveEnd={(_, viewport) =>
          p.boxViews.set(viewKey, { ...p.boxViews.get(viewKey), viewport })
        }
        fitViewOptions={{
          padding: 0.15,
          maxZoom: 1,
          nodes: data.nodes.filter(
            (node) =>
              (node.data.agent?.leta_id ??
                node.data.box?.leta_id ??
                node.data.schedule?.leta_id) === graph.roots[0],
          ),
        }}
        minZoom={0.18}
        maxZoom={1.5}
        onlyRenderVisibleElements
        onPaneClick={() => setSchedule(null)}
        aria-label="Box canvas"
      >
        <Background gap={24} size={1.25} color="var(--muted-foreground)" className="opacity-35" />
      </ReactFlow>
      <div className="absolute top-3 right-3 left-3 flex items-center justify-end gap-2 pointer-events-none">
        {working.length > 0 && (
          <div className="pointer-events-auto flex max-w-full items-center gap-2 rounded-lg border bg-background px-2.5 py-1.5 shadow-sm">
            <span className="shrink-0 text-caption text-muted-foreground">
              {working.length} working
            </span>
            <div className="flex min-w-0 items-center -space-x-1">
              {working.slice(0, 5).map((a) => (
                <button
                  key={a.id}
                  title={`${a.name} · ${a.title} · ${agentActivityLabel(a)}`}
                  aria-label={`Locate ${a.name}`}
                  className="rounded-full bg-background outline-ring hover:bg-muted focus-visible:outline-2"
                  onClick={() =>
                    void flow.fitView({
                      nodes: [{ id: a.box_id && collapsed.includes(a.box_id) ? a.box_id : a.id }],
                      maxZoom: 1,
                      duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 250,
                    })
                  }
                >
                  <AgentAvatar
                    name={a.name}
                    agentId={a.id}
                    appearance={a.appearance}
                    className="size-8"
                  />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="absolute bottom-3 left-3 flex items-center gap-0.5 rounded-lg border bg-background p-1 shadow-sm">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Zoom out"
          onClick={() => void flow.zoomOut()}
        >
          <Minus />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Zoom in"
          onClick={() => void flow.zoomIn()}
        >
          <Plus />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Fit boxes"
          onClick={() => void flow.fitView({ padding: 0.15, maxZoom: 1 })}
        >
          <Scan />
        </Button>
      </div>
      {!p.live.enabled && (
        <span className="pointer-events-none absolute right-3 bottom-4 rounded-md bg-background px-2 py-1 text-caption text-muted-foreground">
          Preview
        </span>
      )}
      {schedule && <ScheduleDetail schedule={schedule} onClose={() => setSchedule(null)} />}
    </div>
  );
}
export function BoxView({ root = '' }: { root?: string }) {
  const p = useAgentPreview();
  const graph = useMemo(
    () => ({
      ...p.graph,
      roots: p.graph.roots.filter((id) => !root || id === root),
      agents: p.graph.agents
        .filter((a) => !root || a.leta_id === root)
        .map((a) =>
          p.live.enabled && p.graphQuery.isError && a.status === 'working'
            ? { ...a, status: 'unknown' as const }
            : a,
        ),
      boxes: p.graph.boxes.filter((b) => !root || b.leta_id === root),
      schedules: p.graph.schedules.filter((s) => !root || s.leta_id === root),
      edges: p.graph.edges.filter(
        (e) => !root || p.graph.boxes.some((b) => b.id === e.box_id && b.leta_id === root),
      ),
    }),
    [p.graph, root, p.live.enabled, p.graphQuery.isError],
  );
  if (p.live.enabled && p.graphQuery.isPending)
    return (
      <div className="flex h-full items-center justify-center gap-8 p-6">
        <Skeleton className="h-32 w-52" />
        <Skeleton className="hidden h-64 w-80 sm:block" />
      </div>
    );
  if (
    p.live.enabled &&
    p.graphQuery.error &&
    (!graph.roots.length ||
      (p.graphQuery.error instanceof ApiError &&
        [401, 403, 404].includes(p.graphQuery.error.status)))
  )
    return (
      <div
        role="alert"
        className="flex h-full flex-col items-center justify-center gap-3 p-6 text-sm"
      >
        <p>{p.graphQuery.error.message}</p>
        <Button variant="outline" onClick={() => void p.graphQuery.refetch()}>
          Retry
        </Button>
      </div>
    );
  if (!graph.roots.length)
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Box />
          </EmptyMedia>
          <EmptyTitle>No boxes to show</EmptyTitle>
          <EmptyDescription>
            Agents you can manage will appear here with their teams and schedules.
          </EmptyDescription>
        </EmptyHeader>
        {p.graphQuery.hasNextPage && (
          <Button
            variant="outline"
            disabled={p.graphQuery.isFetchingNextPage}
            onClick={() => void p.graphQuery.fetchNextPage()}
          >
            Load more agents
          </Button>
        )}
      </Empty>
    );
  return (
    <div className="flex h-full min-h-0 flex-col">
      {p.live.enabled && p.graphQuery.error && (
        <div
          role="status"
          className="flex items-center justify-between gap-3 border-b px-4 py-2 text-caption text-muted-foreground"
        >
          Connection lost. Activity may be out of date.
          <Button variant="ghost" size="sm" onClick={() => void p.graphQuery.refetch()}>
            Retry
          </Button>
        </div>
      )}
      <div className="min-h-0 flex-1">
        <ReactFlowProvider key={root || 'all'}>
          <Canvas graph={graph} viewKey={root || 'all'} />
        </ReactFlowProvider>
      </div>
      {p.graphQuery.hasNextPage && (
        <Button
          variant="ghost"
          disabled={p.graphQuery.isFetchingNextPage}
          onClick={() => void p.graphQuery.fetchNextPage()}
        >
          Load more agents
          <ChevronRight />
        </Button>
      )}
    </div>
  );
}
export function BoxSidebar({
  selected,
  onSelect,
}: {
  selected: string;
  onSelect: (id: string) => void;
}) {
  const p = useAgentPreview();
  const [filter, setFilter] = useState('');
  const roots = p.workspace.agents.filter(
    (a) =>
      (!p.live.enabled || a.can_view_activity) &&
      `${a.name} ${a.role}`.toLowerCase().includes(filter.toLowerCase()),
  );
  return (
    <div className="flex h-full min-h-0 flex-col bg-sidebar px-3 pt-2">
      <InputGroup>
        <InputGroupAddon>
          <Search />
        </InputGroupAddon>
        <InputGroupInput
          aria-label="Search box agents"
          placeholder="Search agents…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </InputGroup>
      <nav
        aria-label="Box agents"
        className="mt-3 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pb-3"
      >
        <Button
          variant={!selected ? 'secondary' : 'ghost'}
          className="justify-start"
          aria-current={!selected ? 'page' : undefined}
          onClick={() => onSelect('')}
        >
          <Box />
          All
        </Button>
        <div className="my-2 border-t" />
        {roots.map((a) => (
          <button
            key={a.id}
            aria-label={`Boxes for ${a.name}`}
            aria-current={selected === a.id ? 'page' : undefined}
            onClick={() => onSelect(a.id)}
            className="flex min-h-15.5 shrink-0 items-center gap-2 rounded-lg p-2 text-left hover:bg-sidebar-accent focus-visible:outline-2 focus-visible:outline-ring aria-[current=page]:bg-sidebar-accent"
          >
            <AgentAvatar
              name={a.name}
              agentId={a.id}
              appearance={p.profiles[a.id]?.appearance ?? a.appearance}
              className="size-11.5"
            />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="truncate text-sm font-medium">
                {p.profiles[a.id]?.name ?? a.name}
              </span>
              <span className="truncate text-caption text-muted-foreground">
                {p.profiles[a.id]?.title ?? a.role}
              </span>
            </span>
          </button>
        ))}
      </nav>
    </div>
  );
}
