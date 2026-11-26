import {
  ApiError,
  type ActivityEntry,
  type AgentResource,
  type ChatMessage,
  type HumanRequest,
  type InboxItem,
  type InputItem,
  type Json,
  type RunRecord,
} from '@/lib/agent-api';
import type { Backend } from '@/lib/backend';
import type { AgentLayout } from '@/lib/agent-organization';
import type { BoxGraph } from '@/lib/box-api';
import type { ChatConversationDto, ChatMessageDto, SidebarLayoutDto } from '@/lib/chat-api';
import type { RealtimeContextValue, RealtimeEnvelope } from '@/lib/realtime';
import { agentAppearance } from '@/components/agent-appearance';
import { fileReferences, fileToken } from '@/lib/file-refs';
import { research, announcement, channelCSV, demoScenes } from './landing-demo-content';

const owner = 'preview-owner';
const workspace = 'preview';
const date = (offset = 0) => new Date(Date.now() - 3_600_000 + offset).toISOString();
type DemoFile = {
  id: string;
  storageId: string;
  parentId?: string;
  name: string;
  kind: 'NODE_KIND_DIRECTORY' | 'NODE_KIND_FILE';
  updatedAt: string;
  file?: {
    mediaType: string;
    sizeBytes: string;
    version: string;
    type: 'FILE_TYPE_TEXT' | 'FILE_TYPE_BLOB';
  };
  downloadUrl?: string;
  content: string;
};

/** The real app talks to this in-memory API inside /app-preview, never to a live workspace. */
export function createLandingDemo() {
  let workspaceName = 'Launch workspace';
  const epoch = Date.now() - 60_000;
  let sequence = 0;
  const timestamp = () => new Date(epoch + ++sequence).toISOString();
  let disposed = false,
    playing = false,
    selected = 'atlas',
    clock = 0,
    last = 0,
    generation = 0;
  let timer: ReturnType<typeof setInterval> | undefined;
  const played = new Set<string>();
  const channelListeners = new Map<string, Set<(event: RealtimeEnvelope) => void>>();
  const chatUserListeners = new Set<(event: RealtimeEnvelope) => void>();
  const letaUserListeners = new Set<(event: RealtimeEnvelope) => void>();
  const previewRealtime: RealtimeContextValue = {
    status: 'connected',
    subscribe(channel, _getToken, listener) {
      let set = channelListeners.get(channel);
      if (!set) {
        set = new Set();
        channelListeners.set(channel, set);
      }
      set.add(listener.onEvent);
      return () => {
        set?.delete(listener.onEvent);
        if (set && set.size === 0) channelListeners.delete(channel);
      };
    },
    onChatUserEvent(handler) {
      chatUserListeners.add(handler);
      return () => {
        chatUserListeners.delete(handler);
      };
    },
    onLetaUserEvent(handler) {
      letaUserListeners.add(handler);
      return () => {
        letaUserListeners.delete(handler);
      };
    },
  };
  function publishChannel(channel: string, type: string, data: Record<string, unknown> = {}) {
    const set = channelListeners.get(channel);
    if (!set) return;
    const envelope: RealtimeEnvelope = { type, data };
    for (const fn of [...set]) fn(envelope);
  }
  function publishChatUser(type: string, data: Record<string, unknown> = {}) {
    const envelope: RealtimeEnvelope = { type, data };
    for (const fn of [...chatUserListeners]) fn(envelope);
  }
  function publishLetaUser(type: string, data: Record<string, unknown> = {}) {
    const envelope: RealtimeEnvelope = { type, data };
    for (const fn of [...letaUserListeners]) fn(envelope);
  }
  const convIdFor = (agent: string) => `conv-${agent}`;
  const agentFromConv = (convId: string) =>
    convId.startsWith('conv-') ? convId.slice(5) : (convId.split(':').at(-1) ?? selected);
  const profiles: AgentResource[] = [
    [
      'atlas',
      'Atlas',
      'Coordinator',
      'Coordinates the team and turns shared files into a clear plan.',
    ],
    [
      'scout',
      'Scout',
      'Researcher',
      'Finds reliable sources and shares concise research with the team.',
    ],
    ['forge', 'Forge', 'Writer', 'Turns research into briefs, documents and launch copy.'],
  ].map(([id, name, title, description]) => ({
    id,
    name,
    title,
    handle: id,
    description,
    workspace_id: workspace,
    appearance: agentAppearance(name),
    state: 'active',
    paused: false,
    running: false,
    can_manage: true,
    can_delete: true,
    model_id: id === 'scout' ? 'google/gemini-2.5-pro' : 'openai/gpt-5',
    reasoning_effort: 'medium',
    capabilities: {
      can_chat: true,
      can_view_activity: true,
      can_edit_settings: true,
      can_delete: true,
    },
    preview: 'Ready to work with your team.',
    updated_at: date(),
    unread_count: id === 'forge' ? 1 : 0,
  }));
  let layout: AgentLayout = {
    folders: [{ id: 'launch-team', name: 'Launch team', parent_id: null }],
    assignments: { scout: 'launch-team', forge: 'launch-team' },
    pins: ['atlas'],
    order: ['atlas', 'scout', 'forge'],
    collapsed: [],
  };
  let revision = 1;
  const roots = ['Personal', 'Team', ...profiles.map((p) => p.name)].map((name, i) => ({
    id: ['personal', 'team', ...profiles.map((p) => p.id)][i],
    name,
    rootNodeId: `root-${i}`,
    capabilities: { write: true },
  }));
  const files: DemoFile[] = [];
  const addFile = (
    storageId: string,
    parentId: string,
    name: string,
    content: string,
    mediaType = 'text/markdown',
    id: string = crypto.randomUUID(),
  ) => {
    const node: DemoFile = {
      id,
      storageId,
      parentId,
      name,
      kind: 'NODE_KIND_FILE',
      updatedAt: date(),
      file: {
        mediaType,
        sizeBytes: String(new Blob([content]).size),
        version: '1',
        type: 'FILE_TYPE_TEXT',
      },
      content,
    };
    files.push(node);
    return node;
  };
  for (const root of roots) {
    files.push({
      id: root.rootNodeId,
      storageId: root.id,
      name: root.name,
      kind: 'NODE_KIND_DIRECTORY',
      updatedAt: date(),
      content: '',
    });
  }
  const team = roots.find((root) => root.id === 'team')!;
  const image = addFile('team', team.rootNodeId, 'Launch mark.png', '', 'image/png', 'team-mark');
  image.downloadUrl =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1kAAAAASUVORK5CYII=';
  image.file = { ...image.file!, sizeBytes: '68', type: 'FILE_TYPE_BLOB' };
  addFile(
    'team',
    team.rootNodeId,
    'Launch brief.md',
    '# Morrow · Friday launch\n\nLaunch: Friday 10:00 UTC. Thursday review with Maya at 16:00 UTC.\n\nDeliverables: channel recommendation, newsletter draft and a shareable report.\n\nDo not publish without channel approval. Use the last campaign as the baseline; keep all source values intact.\n',
    'text/markdown',
    'team-brief',
  );
  addFile(
    'team',
    team.rootNodeId,
    'Customer interviews.md',
    research,
    'text/markdown',
    'team-research',
  );
  addFile(
    'team',
    team.rootNodeId,
    'Channel performance.csv',
    channelCSV,
    'text/csv',
    'team-channels',
  );
  addFile(
    'team',
    team.rootNodeId,
    'Brand voice.md',
    '# Morrow · writing guidelines\n\nOur customers run small studios. Say what they can do, without slogans.\n\n- Start with a familiar client problem.\n- One CTA: create your first client project.\n- No “revolutionary”, “seamless” or claims about saving hours.\n- Keep the newsletter below 180 words.\n',
    'text/markdown',
    'team-voice',
  );
  for (const root of roots.filter((root) => root.id !== 'team')) {
    addFile(
      root.id,
      root.rootNodeId,
      root.id === 'personal' ? 'Thursday review.md' : 'Working notes.md',
      root.id === 'personal'
        ? '# Thursday review\n\nAsk Atlas for the launch recommendation. Maya needs a visual report before 16:00. Keep the source CSV beside the results.\n'
        : `# ${root.name}\n\nCurrent project: Morrow client portal launch. Keep source evidence and drafts separate.\n`,
    );
  }
  const chats: Record<string, ChatMessage[]> = {};
  const activity: Record<string, ActivityEntry[]> = {};
  const runs: Record<string, RunRecord[]> = {};
  const requests: HumanRequest[] = [];
  let channelSelection: string | null = null;
  const instructions: Record<string, string> = {};
  const inbox: Record<string, InboxItem[]> = {};
  const graph: BoxGraph = {
    agents: profiles.map((p) => ({
      ...p,
      leta_id: p.id,
      box_id: null,
      title: p.title ?? '',
      status: 'idle',
    })),
    boxes: [
      {
        id: 'launch',
        leta_id: 'atlas',
        name: 'Friday launch',
        description: 'Prepare the research and launch brief.',
        leader_agent_id: 'researcher',
        state: 'active',
      },
    ],
    additional_links: [],
    schedules: [
      {
        id: 'weekly',
        leta_id: 'atlas',
        creator_agent_id: 'atlas',
        target_agent_id: 'atlas',
        title: 'Weekly launch check',
        content: 'Review the launch plan and flag decisions for the team.',
        type: 'cron',
        spec: { calendar: { day_of_week: [1], hour: [9], minute: [0] }, timezone: 'UTC' },
        paused: false,
      },
    ],
    letas: profiles.map((p) => p.id),
  };
  for (const [id, name, title, color] of [
    ['researcher', 'Nova', 'Market researcher', 'vert'],
    ['writer', 'Quill', 'Report designer', 'ambre'],
  ])
    graph.agents.push({
      id,
      name,
      title,
      appearance: { shape: id === 'researcher' ? 'galet' : 'triangle', color },
      leta_id: 'atlas',
      box_id: 'launch',
      description: `Helps Atlas with ${title.toLowerCase()}.`,
      model_id: 'openai/gpt-5',
      status: 'idle',
    });
  const steps: { at: number; run: () => void }[] = [];
  function rootOf(agent: string) {
    return graph.agents.find((node) => node.id === agent)?.leta_id ?? agent;
  }
  function toChatMessageDto(agent: string, item: ChatMessage, seq: number): ChatMessageDto {
    const refs = item.file_refs ?? fileReferences(item.content);
    return {
      id: item.id,
      conversationId: item.conversation_id ?? convIdFor(agent),
      seq,
      senderType: item.role === 'user' ? 'user' : 'agent',
      senderId: item.role === 'user' ? owner : agent,
      content: item.content,
      ...(item.reply_to_id || item.reply?.id
        ? { replyToId: item.reply_to_id ?? item.reply?.id }
        : {}),
      ...(refs.length
        ? {
            attachments: refs.map((r) => ({
              storageId: r.storage_id,
              nodeId: r.node_id,
              kind: r.kind ?? 'file',
              name: r.label,
            })),
          }
        : {}),
      reactions: (item.reactions ?? []).map((r) => ({
        actorType: r.actor_kind,
        actorId: r.actor_id,
        emoji: r.emoji,
      })),
      createdAt: item.created_at,
    };
  }
  function buildDmConversation(agent: string): ChatConversationDto {
    const p = profiles.find((item) => item.id === agent);
    const list = chats[agent] ?? [];
    const lastMsg = list.at(-1);
    const convId = convIdFor(agent);
    return {
      id: convId,
      workspaceId: workspace,
      type: 'dm',
      title: p?.name ?? agent,
      handle: p?.handle ?? agent,
      lastSeq: list.length,
      lastMsgAt: lastMsg?.created_at ?? p?.updated_at ?? date(),
      unreadCount: p?.unread_count ?? 0,
      members: [
        { actorType: 'user', actorId: owner, role: 'member', lastReadSeq: list.length },
        { actorType: 'agent', actorId: agent, role: 'member', lastReadSeq: list.length },
      ],
      ...(lastMsg
        ? {
            lastMessagePreview: {
              id: lastMsg.id,
              seq: list.length,
              senderType: lastMsg.role === 'user' ? 'user' : 'agent',
              senderId: lastMsg.role === 'user' ? owner : agent,
              snippet: p?.preview ?? lastMsg.content.slice(0, 180),
              hasAttachments: Boolean(lastMsg.file_refs?.length),
            },
          }
        : {}),
      createdAt: date(),
    };
  }
  function toSidebarDto(src: AgentLayout): SidebarLayoutDto {
    return {
      folders: src.folders.map((f) => ({
        id: f.id,
        name: f.name,
        ...(f.parent_id ? { parentId: f.parent_id } : {}),
      })),
      assignments: src.assignments,
      pins: src.pins,
      order: src.order,
      collapsed: src.collapsed,
    };
  }
  function fromSidebarDto(dto?: SidebarLayoutDto): AgentLayout {
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
  function ensureRun(agent: string): RunRecord {
    const list = (runs[agent] ??= []);
    const active = list[0];
    if (active && active.status === 'running') return active;
    const rec: RunRecord = {
      id: `scene-${agent}`,
      agent_id: agent,
      status: 'running',
      input_tokens: 18400,
      cached_input_tokens: 15200,
      output_tokens: 640,
      reasoning_tokens: 420,
      cost_usd: 0.0124,
      llm_calls: 1,
      started_at: timestamp(),
      heartbeat_at: timestamp(),
      finished_at: null,
    };
    list.unshift(rec);
    return rec;
  }
  function emitActivity(agent: string, type: string, data: Record<string, unknown> = {}) {
    publishChannel(`leta:activity:${rootOf(agent)}`, type, {
      agent_id: agent,
      run_id: `scene-${agent}`,
      ...data,
    });
  }
  function changed(agent: string) {
    const p = profiles.find((p) => p.id === agent);
    if (p) p.updated_at = new Date().toISOString();
    emitActivity(agent, 'activity.updated', {});
  }
  function entry(
    agent: string,
    kind: ActivityEntry['kind'],
    payload: ActivityEntry['payload'],
    run = `scene-${agent}`,
    id: string = crypto.randomUUID(),
  ) {
    const items = (activity[agent] ??= []);
    items.push({
      id,
      agent_id: agent,
      run_id: run,
      seq: items.length + 1,
      created_at: timestamp(),
      kind,
      payload,
    });
    const rec = runs[agent]?.[0];
    if (rec && rec.status === 'running') {
      rec.input_tokens += 4200;
      rec.cached_input_tokens += 3900;
      rec.output_tokens += 310;
      rec.llm_calls += kind === 'tool_call' ? 1 : 0;
      rec.cost_usd = Number((rec.cost_usd + 0.0042).toFixed(4));
      rec.heartbeat_at = timestamp();
    }
    const eventType =
      kind === 'tool_call'
        ? 'activity.tool_call'
        : kind === 'tool_result'
          ? 'activity.tool_result'
          : kind === 'inbox_input'
            ? 'activity.inbox_received'
            : 'activity.message';
    emitActivity(agent, eventType, { seq: items.length });
  }
  function message(
    agent: string,
    role: ChatMessage['role'],
    content: string,
    id: string = crypto.randomUUID(),
  ) {
    const list = (chats[agent] ??= []);
    const seq = list.length + 1;
    const item: ChatMessage = {
      id,
      seq,
      role,
      sender_type: role === 'user' ? 'user' : 'agent',
      sender_id: role === 'user' ? owner : agent,
      content,
      created_at: timestamp(),
      conversation_id: convIdFor(agent),
      file_refs: fileReferences(content),
      reactions: [],
    };
    list.push(item);
    const p = profiles.find((p) => p.id === agent);
    if (p && role === 'assistant') {
      p.latest_reply_id = item.id;
      p.latest_reply_at = item.created_at;
    }
    if (p)
      p.preview = content
        .replace(/@\[[^\]]*\]\([^)]*\)/g, 'file')
        .replace(/:file\[([^\]]+)\]\{[^}]+\}/g, '$1')
        .replace(/[#*`]/g, '')
        .replace(/\s+/g, ' ')
        .slice(0, 180);
    const convId = convIdFor(agent);
    publishChannel(`chat:conv:${convId}`, 'message.created', {
      conversation_id: convId,
      message_id: item.id,
      seq,
    });
    publishChatUser('message.created', { conversation_id: convId, message_id: item.id, seq });
    changed(agent);
    return item;
  }
  function tool(
    agent: string,
    name: string,
    args: Record<string, Json>,
    result: Json,
    duration = 900,
  ) {
    const id = crypto.randomUUID();
    emitActivity(agent, 'stream.tool_args_delta', {
      tool_call_id: id,
      name,
      delta: JSON.stringify(args),
    });
    entry(agent, 'tool_call', { name, args, tool_call_id: id });
    working(agent, true, name);
    schedule(duration, () => {
      let data = result;
      const source = files.find(
        (node) => node.storageId === 'team' && node.name === String(args.path).split('/').at(-1),
      );
      if (
        name === 'file_read' &&
        source &&
        data &&
        typeof data === 'object' &&
        !Array.isArray(data)
      )
        data = {
          ...data,
          content: source.content,
          path: args.path,
          storage_id: source.storageId,
          node_id: source.id,
        };
      if (name === 'file_list')
        data = {
          items: files
            .filter((node) => node.storageId === 'team' && node.parentId === team.rootNodeId)
            .map((node) => ({
              name: node.name,
              path: `/mnt/team/${node.name}`,
              kind: 'file',
              storage_id: node.storageId,
              node_id: node.id,
            })),
        };
      if (
        name === 'file_write' &&
        typeof args.path === 'string' &&
        typeof args.content === 'string'
      ) {
        const fileName = args.path.split('/').at(-1)!;
        let file = files.find((node) => node.storageId === 'team' && node.name === fileName);
        if (file) {
          file.content =
            file.id === 'team-brief' && channelSelection
              ? args.content.replace(
                  '- [ ] You: choose launch channels',
                  `- [x] You: ${channelSelection}`,
                )
              : args.content;
          file.file!.version = String(Number(file.file!.version) + 1);
          file.file!.sizeBytes = String(new Blob([file.content]).size);
          file.updatedAt = timestamp();
        } else {
          const supplied =
            result && typeof result === 'object' && !Array.isArray(result)
              ? result.node_id
              : undefined;
          file = addFile(
            'team',
            team.rootNodeId,
            fileName,
            args.content,
            fileName.endsWith('.html') ? 'text/html' : 'text/markdown',
            typeof supplied === 'string' ? supplied : undefined,
          );
        }
        data = { storage_id: 'team', node_id: file.id, path: args.path, content: file.content };
      }
      if (name === 'schedule_create' && data && typeof data === 'object' && !Array.isArray(data)) {
        const next = new Date();
        next.setUTCDate(next.getUTCDate() + ((8 - next.getUTCDay()) % 7 || 7));
        next.setUTCHours(9, 0, 0, 0);
        data = {
          ...data,
          upcoming: [next.toISOString(), new Date(next.getTime() + 7 * 86400000).toISOString()],
        };
        graph.schedules.push({
          id,
          leta_id: agent,
          creator_agent_id: agent,
          target_agent_id: agent,
          title: String(data.title),
          content: String(data.content),
          type: 'cron',
          spec: data.spec as Record<string, Json>,
          paused: false,
        });
      }
      entry(agent, 'tool_result', {
        tool_call_id: id,
        name,
        text: typeof data === 'object' && data && 'content' in data ? String(data.content) : '',
        status: 'success',
        ui: { version: 1, kind: name, data },
      });
      const node = graph.agents.find((node) => node.id === agent);
      if (node) node.tool_name = null;
    });
  }
  function narrate(agent: string, text: string, kind: 'reasoning' | 'text' = 'reasoning') {
    const id = crypto.randomUUID();
    const streamType = kind === 'reasoning' ? 'stream.thinking_delta' : 'stream.text_delta';
    for (let offset = 0; offset < text.length; offset += 24) {
      schedule(45 * (offset / 24 + 1), () =>
        emitActivity(agent, streamType, { delta: text.slice(offset, offset + 24) }),
      );
    }
    schedule(Math.ceil(text.length / 24) * 45 + 50, () => {
      entry(agent, 'assistant', { [kind]: text }, `scene-${agent}`, id);
      if (kind === 'text') {
        message(agent, 'assistant', text);
        working(agent, false);
      }
    });
  }
  function incoming(agent: string, item: InputItem) {
    const id = crypto.randomUUID();
    (inbox[agent] ??= []).push({
      id,
      conversation_id: item.conversation_id ?? `${item.source_id}:${agent}`,
      source_kind: item.source_kind,
      source_id: item.source_id ?? '',
      source_name: item.source_name ?? null,
      content: item.content,
      created_at: timestamp(),
      direction: 'in',
      unread_count: 0,
      read_at: timestamp(),
      schedule_title: item.schedule_title,
    });
    entry(agent, 'inbox_input', { ui: { version: 1, kind: 'inbox', items: [{ ...item, id }] } });
  }
  function completeScene() {
    while (steps.length) {
      steps.sort((a, b) => a.at - b.at);
      const step = steps.shift()!;
      clock = Math.max(clock, step.at);
      step.run();
    }
  }
  function schedule(at: number, run: () => void) {
    steps.push({ at: clock + at, run });
  }
  function working(agent: string, value: boolean, toolName?: string) {
    const node = graph.agents.find((a) => a.id === agent);
    if (node) {
      node.status = value ? 'working' : 'idle';
      node.tool_name = toolName ?? null;
      node.heartbeat_at = timestamp();
    }
    const profile = profiles.find((p) => p.id === agent);
    if (profile) profile.running = value;
    if (value) {
      ensureRun(agent);
      emitActivity(agent, 'run.started', {});
    } else {
      const rec = runs[agent]?.[0];
      if (rec && rec.status === 'running') {
        rec.status = 'completed';
        rec.finished_at = timestamp();
      }
      emitActivity(agent, 'run.finished', { status: 'completed' });
    }
    publishChannel(`chat:conv:${convIdFor(agent)}`, 'typing', {
      actor_type: 'agent',
      actor_id: agent,
      active: value,
    });
    changed(agent);
  }
  function begin(agent: string, typed?: string) {
    generation++;
    const run = generation;
    steps.length = 0;
    const name = profiles.find((p) => p.id === agent)?.name ?? agent;
    const intent = typed?.toLowerCase() ?? '';
    const scene =
      typed && /budget|cost|data|csv|channel|evidence/.test(intent)
        ? demoScenes.scout
        : typed && /write|draft|copy|newsletter|subject/.test(intent)
          ? demoScenes.forge
          : (demoScenes[agent] ?? demoScenes.atlas);
    const launch = scene === demoScenes.atlas;
    const input = typed ?? scene.input;
    if (!typed) message(agent, 'user', input);
    const received = chats[agent]?.findLast((m) => m.role === 'user' && m.content === input);
    if (received) received.read_at = timestamp();
    (inbox[agent] ??= []).push({
      id: crypto.randomUUID(),
      conversation_id: `${owner}:${agent}`,
      source_kind: 'user',
      source_id: owner,
      source_name: 'You',
      content: input,
      created_at: timestamp(),
      direction: 'in',
      unread_count: 0,
      read_at: date(),
    });
    entry(
      agent,
      'inbox_input',
      {
        ui: {
          version: 1,
          kind: 'inbox',
          items: [
            {
              source_kind: 'user',
              source_id: owner,
              source_name: 'You',
              conversation_id: `${owner}:${agent}`,
              content: input,
            },
          ],
        },
      },
      `scene-${agent}`,
    );
    working(agent, true);
    schedule(400, () => narrate(agent, scene.reasoning));
    for (const step of scene.tools)
      schedule(step.at, () => tool(agent, step.name, step.args, step.data, step.duration));
    schedule(1600, () => {
      const text =
        agent === 'atlas'
          ? 'On it. I’ll check the numbers with Scout, get Forge started on the newsletter, and put the decision into a report Maya can review.'
          : agent === 'scout'
            ? 'I’ll check the source rows first, then separate the interview evidence from the assumptions.'
            : 'I’ll use the brief and the customer language. I’ll leave you an editable draft, not publish anything.';
      message(agent, 'assistant', text);
      entry(agent, 'assistant', { text });
    });
    schedule(5800, () => {
      if (!launch) return;
      working('scout', true);
      working('forge', true);
      incoming('scout', {
        source_kind: 'agent',
        source_id: 'atlas',
        source_name: 'Atlas',
        content:
          'Validate the recommendation against interviews and the CSV. Keep the caveats. Maya needs the evidence for Thursday’s review.',
      });
      incoming('forge', {
        source_kind: 'agent',
        source_id: 'atlas',
        source_name: 'Atlas',
        content:
          'Draft the Morrow newsletter. Use Brand voice.md; keep it below 180 words with one CTA.',
      });
      narrate('scout', demoScenes.scout.reasoning);
      narrate('forge', demoScenes.forge.reasoning);
      tool(
        'scout',
        'file_read',
        { path: '/mnt/team/Customer interviews.md' },
        { content: research, start_line: 1, storage_id: 'team', node_id: 'team-research' },
        1700,
      );
      tool(
        'forge',
        'file_read',
        { path: '/mnt/team/Brand voice.md' },
        { content: files.find((f) => f.id === 'team-voice')!.content, start_line: 1 },
        1200,
      );
      working('researcher', true);
      working('writer', true);
      entry('researcher', 'inbox_input', {
        ui: {
          version: 1,
          kind: 'inbox',
          items: [
            {
              source_kind: 'agent',
              source_name: 'Atlas',
              source_id: 'atlas',
              content: 'Verify channel activation and cost per activated user.',
            },
          ],
        },
      });
      entry('researcher', 'assistant', {
        reasoning:
          'I’ll calculate from the source CSV, preserving the original values and rounding only the final percentages.',
      });
      tool(
        'researcher',
        'file_read',
        { path: '/mnt/team/Channel performance.csv' },
        { content: channelCSV },
      );
      incoming('writer', {
        source_kind: 'agent',
        source_id: 'atlas',
        source_name: 'Atlas',
        content:
          'Build a shareable HTML report from the verified figures. Include activation bars, spend and the evidence limit. Maya needs this before the review.',
      });
      narrate(
        'writer',
        'The visual hierarchy should lead with the allocation decision, then the three metrics, then a channel chart. Preserve the source CSV numbers and show the limitation instead of implying a causal result.',
      );
      tool(
        'writer',
        'file_read',
        { path: '/mnt/team/Channel performance.csv' },
        { content: channelCSV },
        1300,
      );
    });
    schedule(launch ? 13800 : 6900, () => {
      message(agent, 'assistant', scene.progress);
      if (!launch) return;
      incoming('atlas', {
        source_kind: 'agent',
        source_id: 'scout',
        source_name: 'Scout',
        content:
          'Newsletter + blog is supported. One caveat: only three interviews. Social’s drop-off is real, but the CSV doesn’t tell us why it happens.',
      });
      entry('scout', 'assistant', { text: demoScenes.scout.answer });
      working('scout', false);
      narrate(
        'atlas',
        'Scout agrees on the recommendation, but the causal claim needs to go. I should say “investigate the signup-to-first-project funnel”, not blame the ad creative. Maya also needs the share of spend alongside the share of activations.',
      );
      working('researcher', false);
      entry('researcher', 'assistant', {
        text: 'Verified: newsletter $1.83, blog $2.30, social $29.27 per activation. Social has 44.4% of traffic and 10.8% of activations.',
      });
    });
    schedule(17800, () => {
      if (!launch) return;
      const request: HumanRequest = {
        id: `channels-${agent}-${run}`,
        type: 'ask',
        title: 'Which channels should we prepare?',
        recipient_user_id: owner,
        requester_agent_id: agent,
        requester_name: name,
        leta_id: agent,
        workspace_id: workspace,
        payload: {
          questions: [
            {
              id: 'channels',
              text: 'Where should the launch be announced?',
              type: 'multiple_choice',
              options: [
                { id: 'blog', label: 'Blog and changelog' },
                { id: 'newsletter', label: 'Newsletter' },
                { id: 'social', label: 'Social channels' },
              ],
            },
          ],
        },
        status: 'pending',
        created_at: timestamp(),
      };
      requests.push(request);
      emitActivity(agent, 'hitl.updated', { request_id: request.id, status: 'pending' });
      publishLetaUser('hitl.updated', { request_id: request.id, status: 'pending' });
      changed(agent);
    });
    if (launch) {
      schedule(15100, () => {
        incoming('atlas', {
          source_kind: 'user',
          source_id: 'maya',
          source_name: 'Maya Chen',
          conversation_id: 'maya:atlas',
          content:
            'Small change: don’t increase the total budget yet. Can you show the spend split too? I’ll review the report at 16:00.',
        });
        entry('atlas', 'assistant', {
          text: 'Maya wants the spend split without a budget increase. I’m adding that to the report and keeping the recommendation within the existing $1,900.',
        });
      });
      schedule(16600, () => {
        incoming('atlas', {
          source_kind: 'schedule',
          source_id: 'weekly',
          source_name: 'Launch review',
          schedule_title: 'Thursday launch readiness',
          scheduled_at: timestamp(),
          content:
            'Check the launch checklist and collect anything still waiting for Thursday’s review.',
        });
        narrate(
          'atlas',
          'The channel choice can wait. While that question is open, I can finish the report, collect Forge’s draft and schedule the post-launch check. No publishing step is authorized.',
        );
      });
      schedule(18400, () => {
        tool(
          'forge',
          'file_write',
          { path: '/mnt/team/Draft announcement.md', content: announcement },
          { storage_id: 'team', node_id: 'team-announcement', content: announcement },
          1600,
        );
      });
      schedule(20700, () => {
        incoming('atlas', {
          source_kind: 'agent',
          source_id: 'forge',
          source_name: 'Forge',
          content:
            'Newsletter draft is ready: under 180 words, three subject lines, one CTA. I removed the “save hours” claim — we don’t have evidence for that. Nothing published.',
        });
        entry('forge', 'assistant', { text: demoScenes.forge.answer });
        working('forge', false);
        message(
          'atlas',
          'assistant',
          `Scout checked the evidence; Forge’s draft is ready. Maya asked to keep the budget flat, so the report now shows both spend and activation. I’m finishing the ${fileToken({ storage_id: 'team', node_id: 'team-brief', label: 'launch review' })}.`,
        );
      });
      schedule(24100, () => {
        working('writer', false);
        entry('writer', 'assistant', {
          text: 'Report complete: an executive summary, activation chart, channel table and evidence limits. All figures link back to the campaign CSV.',
        });
        narrate(
          'atlas',
          'The report and draft are ready. Keep the decision concise for the user, link the artifacts, and leave channel approval open. The monitoring schedule should follow the next campaign, not invent a publishing action.',
        );
      });
      schedule(31000, () => {
        const input = chats.atlas?.find((m) => m.role === 'user' && m.content === scene.input);
        if (input) {
          input.reactions = [{ actor_kind: 'agent', actor_id: 'atlas', emoji: '👍' }];
          publishChannel(`chat:conv:${convIdFor('atlas')}`, 'reaction.added', {
            message_id: input.id,
            emoji: '👍',
          });
          changed('atlas');
        }
      });
    }
    schedule(launch ? 28200 : 12500, () => {
      const lower = typed?.toLowerCase() ?? '';
      const answer = !typed
        ? scene.answer
        : /budget|cost|data|csv|channel/.test(lower)
          ? demoScenes.scout.answer
          : /write|draft|copy|newsletter|subject/.test(lower)
            ? demoScenes.forge.answer
            : `${scene.answer}\n\nI’ve kept the source files alongside the recommendation so you can inspect or edit them.`;
      narrate(agent, answer, 'text');
      working('writer', false);
    });
  }
  function select(agent: string) {
    if (!profiles.some((p) => p.id === agent) || selected === agent) return;
    completeScene();
    selected = agent;
    if (!played.has(agent)) {
      played.add(agent);
      begin(agent);
    }
    if (playing) play();
  }
  function play() {
    disposed = false;
    playing = true;
    if (!played.has(selected)) {
      played.add(selected);
      begin(selected);
    }
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      completeScene();
      return;
    }
    if (timer) return;
    last = performance.now();
    timer = setInterval(() => {
      const now = performance.now();
      if (playing && !document.hidden) clock += Math.min(now - last, 100);
      last = now;
      const due = steps.filter((s) => s.at <= clock);
      for (const step of due) {
        steps.splice(steps.indexOf(step), 1);
        step.run();
      }
    }, 50);
  }
  function pause() {
    playing = false;
    clearInterval(timer);
    timer = undefined;
  }
  const page = <T>(items: T[]) => ({ items, next_cursor: null });
  async function handle(raw: string, init?: RequestInit): Promise<unknown> {
    if (disposed) throw new ApiError(410, 'The preview has closed.');
    const url = new URL(raw, 'https://preview.openlet.invalid');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {};
    const agent = /\/letas\/([^/]+)/.exec(path)?.[1] ?? selected;
    if (path.endsWith('/storage-quota'))
      return {
        usedBytes: String(
          files.reduce((size, file) => size + Number(file.file?.sizeBytes ?? 0), 0),
        ),
        quotaBytes: '1073741824',
      };
    if (path.endsWith('/processing'))
      return { working: graph.agents.some((a) => a.leta_id === agent && a.status === 'working') };
    if (path.endsWith('/context')) {
      const parts = path.split('/');
      const item = chats[agent]?.find((m) => m.id === parts.at(-2) && m.role === parts.at(-3));
      if (!item) throw new ApiError(404, 'Message not found');
      return page([...(chats[agent] ?? [])].reverse());
    }
    if (path === `/v1/workspaces/${workspace}`) {
      if (method === 'PATCH') workspaceName = String(body.name);
      return { id: workspace, name: workspaceName, state: 'WORKSPACE_STATE_ACTIVE' };
    }
    if (path.endsWith('/members') && !path.includes('/conversations/'))
      return {
        members: [{ user: { id: owner, displayName: 'You' }, role: 'WORKSPACE_ROLE_OWNER' }],
      };
    if (path.endsWith('/invitations') && method === 'GET') return { invitations: [] };
    if (path.endsWith('/access') && path.includes('/letas/'))
      return {
        owners: [{ id: owner, display_name: 'You', handle: 'you' }],
        operators: [],
        items: [{ user_id: owner, role: 'owner', display_name: 'You' }],
      };
    if (path === '/v1/workspaces') {
      if (method !== 'GET')
        throw new ApiError(
          400,
          'Creating a workspace is unavailable in the public demo. Sign in to create your own workspace.',
        );
      return {
        workspaces: [
          {
            id: workspace,
            name: workspaceName,
            state: 'WORKSPACE_STATE_ACTIVE',
            role: 'WORKSPACE_ROLE_OWNER',
          },
        ],
      };
    }
    if (path.endsWith('/chat/sidebar')) {
      if (method === 'PUT') {
        layout = fromSidebarDto(body.layout as SidebarLayoutDto | undefined);
        revision++;
        publishChatUser('sidebar.updated', { revision });
      }
      return { revision, layout: toSidebarDto(layout) };
    }
    if (path.endsWith('/letas/sidebar')) {
      if (method === 'PUT') {
        layout = body.layout;
        revision++;
      }
      return { revision, layout, can_create_agent: false };
    }
    if (path.endsWith('/chat:realtimeToken') && method === 'POST') {
      return { channel: String(body.channel ?? ''), token: 'preview' };
    }
    if (path.endsWith('/conversations:dm') && method === 'POST') {
      const targetId = String(body.target?.id ?? selected);
      return buildDmConversation(targetId);
    }
    if (/\/agents\/([^/]+)\/conversations$/.test(path) && method === 'GET') {
      const aid = /\/agents\/([^/]+)\/conversations$/.exec(path)![1];
      const byConv = new Map<string, ChatConversationDto>();
      if (profiles.some((p) => p.id === aid)) {
        byConv.set(convIdFor(aid), buildDmConversation(aid));
      }
      for (const item of inbox[aid] ?? []) {
        if (item.conversation_id === `${owner}:${aid}` || item.conversation_id === convIdFor(aid)) {
          continue;
        }
        byConv.set(item.conversation_id, {
          id: item.conversation_id,
          workspaceId: workspace,
          type: 'dm',
          title: item.source_name ?? item.source_id,
          lastSeq: 1,
          lastMsgAt: item.created_at,
          unreadCount: item.unread_count,
          members: [
            {
              actorType: item.source_kind === 'agent' ? 'agent' : 'user',
              actorId: item.source_id,
              role: 'member',
            },
            { actorType: 'agent', actorId: aid, role: 'member' },
          ],
          lastMessagePreview: {
            id: item.id,
            seq: 1,
            senderType: item.source_kind === 'agent' ? 'agent' : 'user',
            senderId: item.source_id,
            snippet: item.content.slice(0, 180),
          },
          createdAt: item.created_at,
        });
      }
      return { conversations: [...byConv.values()], nextPageToken: '' };
    }
    if (/\/conversations$/.test(path) && method === 'GET') {
      return {
        conversations: profiles.map((p) => buildDmConversation(p.id)),
        nextPageToken: '',
      };
    }
    if (/\/conversations\/([^/]+):ensureStorage$/.test(path) && method === 'POST') {
      const convId = /\/conversations\/([^/]+):ensureStorage$/.exec(path)![1];
      const targetAgent = agentFromConv(convId);
      const targetProfile = profiles.find((p) => p.id === targetAgent);
      const id = `conversation-${targetAgent}`;
      if (!roots.some((r) => r.id === id)) {
        roots.push({
          id,
          name: `${targetProfile?.name ?? targetAgent} conversation`,
          rootNodeId: `root-${id}`,
          capabilities: { write: true },
        });
        files.push({
          id: `root-${id}`,
          storageId: id,
          name: 'Conversation',
          kind: 'NODE_KIND_DIRECTORY',
          content: '',
          updatedAt: date(),
        });
      }
      return { storageId: id, rootNodeId: `root-${id}` };
    }
    if (/\/conversations\/([^/]+):markRead$/.test(path) && method === 'POST') {
      const convId = /\/conversations\/([^/]+):markRead$/.exec(path)![1];
      const targetAgent = agentFromConv(convId);
      const targetProfile = profiles.find((p) => p.id === targetAgent);
      if (targetProfile) targetProfile.unread_count = 0;
      const seq = Number(body.seq ?? chats[targetAgent]?.length ?? 0);
      publishChannel(`chat:conv:${convId}`, 'read_receipt', { conversation_id: convId, seq });
      publishChatUser('read_receipt', { conversation_id: convId, seq });
      return { lastReadSeq: seq };
    }
    if (/\/conversations\/([^/]+):typing$/.test(path) && method === 'POST') {
      return {};
    }
    if (/\/conversations\/([^/]+)\/messages\/([^/]+)\/reactions\/([^/]+)$/.test(path)) {
      const [, convId, messageId, rawEmoji] =
        /\/conversations\/([^/]+)\/messages\/([^/]+)\/reactions\/([^/]+)$/.exec(path)!;
      const targetAgent = agentFromConv(convId);
      const emoji = decodeURIComponent(rawEmoji);
      const item = chats[targetAgent]?.find((m) => m.id === messageId);
      if (item) {
        const rest = (item.reactions ?? []).filter(
          (r) => !(r.actor_kind === 'user' && r.actor_id === owner && r.emoji === emoji),
        );
        item.reactions =
          method === 'DELETE' ? rest : [...rest, { actor_kind: 'user', actor_id: owner, emoji }];
      }
      publishChannel(
        `chat:conv:${convId}`,
        method === 'DELETE' ? 'reaction.removed' : 'reaction.added',
        { message_id: messageId, emoji },
      );
      changed(targetAgent);
      return {};
    }
    if (/\/conversations\/([^/]+)\/messages$/.test(path)) {
      const convId = /\/conversations\/([^/]+)\/messages$/.exec(path)![1];
      const targetAgent = agentFromConv(convId);
      if (method === 'POST') {
        const messageId = String(body.idempotencyKey ?? body.message_id ?? crypto.randomUUID());
        const existing = chats[targetAgent]?.find((m) => m.id === messageId);
        if (existing) {
          const idx = chats[targetAgent]!.indexOf(existing) + 1;
          return toChatMessageDto(targetAgent, existing, idx);
        }
        completeScene();
        const m = message(targetAgent, 'user', String(body.content ?? ''), messageId);
        if (body.replyToId) {
          m.reply_to_id = String(body.replyToId);
          const parent = chats[targetAgent]?.find((msg) => msg.id === body.replyToId);
          if (parent) {
            m.reply = { id: parent.id, role: parent.role, content: parent.content };
          }
        }
        begin(targetAgent, String(body.content ?? ''));
        play();
        return toChatMessageDto(targetAgent, m, chats[targetAgent]?.length ?? 1);
      }
      if (convId.startsWith('conv-')) {
        const list = chats[targetAgent] ?? [];
        const beforeSeq = Number(url.searchParams.get('beforeSeq') ?? 0);
        const filtered = beforeSeq > 0 ? list.filter((_, i) => i + 1 < beforeSeq) : list;
        return {
          messages: filtered.map((m, i) => toChatMessageDto(targetAgent, m, i + 1)),
          hasBefore: false,
          hasAfter: false,
        };
      }
      const inboxMatches = Object.values(inbox)
        .flat()
        .filter((it) => it.conversation_id === convId);
      return {
        messages: inboxMatches.map((it, idx): ChatMessageDto => ({
          id: it.id,
          conversationId: convId,
          seq: idx + 1,
          senderType: it.source_kind === 'agent' ? 'agent' : 'user',
          senderId: it.source_id,
          content: it.content,
          createdAt: it.created_at,
        })),
        hasBefore: false,
        hasAfter: false,
      };
    }
    if (/\/conversations\/([^/]+)$/.test(path) && method === 'GET') {
      const convId = /\/conversations\/([^/]+)$/.exec(path)![1];
      return buildDmConversation(agentFromConv(convId));
    }
    if (path.endsWith('/models')) {
      const models = [
        { model_id: 'openai/gpt-5', reasoning_efforts: ['low', 'medium', 'high'] },
        { model_id: 'google/gemini-2.5-pro', reasoning_efforts: ['medium', 'high'] },
      ];
      return { items: models, models };
    }
    if (path.endsWith('/letas/box-view')) {
      const root = url.searchParams.get('leta_id');
      return {
        ...graph,
        agents: root ? graph.agents.filter((a) => a.leta_id === root) : graph.agents,
        boxes: root ? graph.boxes.filter((b) => b.leta_id === root) : graph.boxes,
        next_cursor: null,
      };
    }
    if (path.endsWith('/letas')) return { ...page(profiles), can_create_agent: false };
    if (/\/letas\/[^/]+\/realtime-token$/.test(path) && method === 'POST') {
      return { channel: `leta:activity:${agent}`, token: 'preview' };
    }
    if (/\/letas\/[^/]+\/agents$/.test(path) && method === 'GET') {
      const rows = graph.agents
        .filter((node) => node.leta_id === agent)
        .map((node) => ({
          id: node.id,
          leta_id: node.leta_id,
          parent_agent_id: node.id === agent ? null : agent,
          depth: node.id === agent ? 0 : 1,
          name: node.name,
          title: node.title,
          handle: node.handle ?? node.id,
          description: node.description,
          appearance: node.appearance,
          model_id: node.model_id,
          reasoning_effort: node.reasoning_effort ?? 'medium',
          state: 'active',
          running: node.status === 'working',
        }));
      return { items: rows };
    }
    if (/\/letas\/[^/]+\/agents\/([^/]+)\/runs$/.test(path) && method === 'GET') {
      const aid = /\/agents\/([^/]+)\/runs$/.exec(path)![1];
      return { items: runs[aid] ?? [] };
    }
    if (/\/letas\/[^/]+\/agents\/([^/]+)\/cancel$/.test(path) && method === 'POST') {
      const aid = /\/agents\/([^/]+)\/cancel$/.exec(path)![1];
      steps.length = 0;
      working(aid, false);
      return { accepted: true };
    }
    if (path.endsWith('/settings'))
      return {
        system_prompt:
          instructions[agent] ??
          'Work with the team. Use shared files, cite your sources and ask before making decisions.',
        model_id: profiles.find((p) => p.id === agent)?.model_id,
        reasoning_effort: 'medium',
      };
    if (/\/letas\/[^/]+\/(pause|resume)$/.test(path) && method === 'POST') {
      const current = profiles.find((profile) => profile.id === agent);
      if (!current) throw new ApiError(404, 'Agent not found');
      current.paused = path.endsWith('/pause');
      return current;
    }
    const profile = profiles.find((p) => p.id === agent);
    if (/\/letas\/[^/]+$/.test(path) || /\/letas\/[^/]+\/agents\/[^/]+$/.test(path)) {
      const childId = /\/agents\/([^/]+)$/.exec(path)?.[1];
      const defaultPrompt =
        instructions[agent] ??
        'Work with the team. Use shared files, cite your sources and ask before making decisions.';
      if (childId && childId !== agent) {
        const child = graph.agents.find((node) => node.id === childId);
        if (child)
          return {
            ...profile,
            ...child,
            custom_instructions: instructions[childId] ?? child.description,
            running: child.status === 'working',
            capabilities: { can_chat: false, can_view_activity: true, can_edit_settings: false },
          };
      }
      if (!profile) throw new ApiError(404, 'Agent not found');
      if (method === 'DELETE') {
        profiles.splice(profiles.indexOf(profile), 1);
        graph.agents = graph.agents.filter((item) => item.leta_id !== agent);
        graph.boxes = graph.boxes.filter((item) => item.leta_id !== agent);
        return {};
      }
      if (method === 'PATCH') {
        Object.assign(profile, body);
        if (typeof body.custom_instructions === 'string') {
          instructions[agent] = body.custom_instructions;
        } else if (typeof body.system_prompt === 'string') {
          instructions[agent] = body.system_prompt;
        }
      }
      return { ...profile, custom_instructions: defaultPrompt };
    }
    if (path.endsWith('/messages/read')) return {};
    if (path.endsWith('/reaction')) {
      const parts = path.split('/');
      const item = chats[agent]?.find((m) => m.id === parts.at(-2));
      if (item)
        item.reactions = body.emoji
          ? [{ actor_kind: 'user', actor_id: owner, emoji: body.emoji }]
          : [];
      changed(agent);
      return {};
    }
    const inboxAgent = url.searchParams.get('agent_id') ?? agent;
    if (path.includes('/inbox/')) {
      const conversation = decodeURIComponent(/\/inbox\/([^/]+)/.exec(path)![1]);
      return page(
        [...(inbox[inboxAgent] ?? [])]
          .filter((item) => item.conversation_id === conversation)
          .reverse(),
      );
    }
    if (path.endsWith('/messages')) {
      if (method === 'POST') {
        const messageId = body.message_id;
        if (!chats[agent]?.some((m) => m.id === messageId)) {
          completeScene();
          const m = message(agent, 'user', body.content, messageId);
          if (body.in_reply_to)
            m.reply = {
              id: body.in_reply_to,
              role: body.in_reply_to_role,
              content: chats[agent].find((m) => m.id === body.in_reply_to)?.content ?? '',
            };
          begin(agent, body.content);
          play();
        }
        return {};
      }
      return page([...(chats[agent] ?? [])].reverse());
    }
    if (path.endsWith('/inbox')) {
      const conversations = new Map<string, InboxItem>();
      for (const item of inbox[inboxAgent] ?? []) conversations.set(item.conversation_id, item);
      return page(
        [...conversations.values()]
          .reverse()
          .filter(
            (item) =>
              (!url.searchParams.get('kind') ||
                item.source_kind === url.searchParams.get('kind')) &&
              (url.searchParams.get('unread') !== 'true' || item.unread_count > 0) &&
              `${item.source_name ?? ''} ${item.content}`
                .toLowerCase()
                .includes((url.searchParams.get('query') ?? '').toLowerCase()),
          ),
      );
    }
    const scheduleId = /\/schedules\/([^/]+)$/.exec(path)?.[1];
    if (scheduleId) {
      const item = graph.schedules.find((item) => item.id === scheduleId && item.leta_id === agent);
      if (!item) throw new ApiError(404, 'Schedule not found');
      return {
        ...item,
        created_at: date(),
        deleted_at: null,
        upcoming: item.paused ? [] : [date(86_400_000)],
      };
    }
    if (path.endsWith('/schedules'))
      return page(
        graph.schedules
          .filter((item) => item.leta_id === agent)
          .map((item) => ({
            ...item,
            created_at: date(),
            deleted_at: null,
            next_run_at: date(86_400_000),
          })),
      );
    if (path.endsWith('/hitl-requests')) {
      const id =
        url.searchParams.get('leta_id') ??
        /\/letas\/([^/]+)\/hitl-requests$/.exec(path)?.[1] ??
        null;
      const items = requests.filter(
        (r) =>
          (!id || r.leta_id === id) &&
          (!url.searchParams.get('status') || r.status === url.searchParams.get('status')),
      );
      return {
        ...page(
          items.map((r) => ({
            ...r,
            workspace_id: workspace,
            requester_name: profiles.find((p) => p.id === r.leta_id)?.name,
          })),
        ),
        pending_count: items.filter((r) => r.status === 'pending').length,
      };
    }
    if (/\/hitl-requests\/([^/]+)$/.test(path) && method === 'GET') {
      const rid = /\/hitl-requests\/([^/]+)$/.exec(path)![1];
      const req = requests.find((r) => r.id === rid);
      if (!req) throw new ApiError(404, 'Question not found');
      return req;
    }
    if (/\/hitl-requests\/([^/]+)\/cancel$/.test(path) && method === 'POST') {
      const rid = /\/hitl-requests\/([^/]+)\/cancel$/.exec(path)![1];
      const req = requests.find((r) => r.id === rid);
      if (!req) throw new ApiError(404, 'Question not found');
      req.status = 'cancelled';
      req.resolved_at = new Date().toISOString();
      emitActivity(req.leta_id!, 'hitl.updated', { request_id: req.id, status: 'cancelled' });
      publishLetaUser('hitl.updated', { request_id: req.id, status: 'cancelled' });
      return { cancelled: true };
    }
    if (path.endsWith('/decide') || path.endsWith('/answer')) {
      const request = requests.find((r) => r.id === path.split('/').at(-2));
      if (!request) throw new ApiError(404, 'Question not found');
      Object.assign(request, {
        status: body.status,
        response: body.response,
        resolved_at: new Date().toISOString(),
      });
      const channels =
        request.payload.questions?.[0]?.options
          ?.filter((option) => request.response?.answers?.channels?.option_ids?.includes(option.id))
          .map((option) => option.label)
          .join(', ') || 'No channels selected';
      channelSelection = channels;
      const review = files.find((file) => file.id === 'team-brief')!;
      review.content = review.content.replace(
        '- [ ] You: choose launch channels',
        `- [x] You: ${channels}`,
      );
      review.file!.version = String(Number(review.file!.version) + 1);
      review.file!.sizeBytes = String(new Blob([review.content]).size);
      message(
        request.leta_id!,
        'assistant',
        `Confirmed: ${channels}. I’ve updated the ${fileToken({ storage_id: 'team', node_id: 'team-brief', label: 'launch review' })}. ${files.some((file) => file.id === 'team-announcement') ? 'The announcement is ready for Thursday’s review' : 'I’m continuing with the draft and report'}; nothing has been published.`,
      );
      emitActivity(request.leta_id!, 'hitl.updated', {
        request_id: request.id,
        status: request.status,
      });
      publishLetaUser('hitl.updated', { request_id: request.id, status: request.status });
      changed(request.leta_id!);
      return request;
    }
    if (path.includes('/activity/')) {
      const activityAgent = /\/agents\/([^/]+)/.exec(path)?.[1] ?? agent;
      const key = path.split('/').at(-1);
      return activity[activityAgent]?.find((e) => e.id === key || String(e.seq) === key) ?? {};
    }
    if (path.endsWith('/activity')) {
      const activityAgent = /\/agents\/([^/]+)/.exec(path)?.[1] ?? agent;
      return page([...(activity[activityAgent] ?? [])].reverse());
    }
    if (path.endsWith('/conversation-storage')) {
      const id = `conversation-${agent}`;
      if (!roots.some((r) => r.id === id)) {
        roots.push({
          id,
          name: `${profile?.name} conversation`,
          rootNodeId: `root-${id}`,
          capabilities: { write: true },
        });
        files.push({
          id: `root-${id}`,
          storageId: id,
          name: 'Conversation',
          kind: 'NODE_KIND_DIRECTORY',
          content: '',
          updatedAt: date(),
        });
      }
      return {
        id: `${owner}:${agent}`,
        storage_id: id,
        root_node_id: `root-${id}`,
        workspace_id: workspace,
        ready: true,
      };
    }
    if (path.endsWith('/file-reference')) {
      const node = files.find((n) => n.id === body.node_id);
      if (!node) throw new ApiError(404, 'File not found');
      return {
        storage_id: node.storageId,
        node_id: node.id,
        label: body.label ?? node.name,
        name: node.name,
        mime: node.file?.mediaType,
        size: Number(node.file?.sizeBytes),
        version: Number(node.file?.version),
      };
    }
    if (path.endsWith('/storages')) return { storages: roots };
    if (path.includes('/storages/')) {
      const storage = /\/storages\/([^/]+)/.exec(path)![1];
      const nodeId = /\/nodes\/([^/:]+)/.exec(path)?.[1];
      const node = files.find((n) => n.id === nodeId && n.storageId === storage);
      if (path.endsWith('/children'))
        return { nodes: files.filter((n) => n.storageId === storage && n.parentId === nodeId) };
      if (path.endsWith('/files:glob')) {
        const needle = String(body.pattern ?? '')
          .replace(/\*/g, '')
          .toLowerCase();
        return {
          hits: files
            .filter((n) => n.storageId === storage && n.name.toLowerCase().includes(needle))
            .map((n) => ({
              nodeId: n.id,
              path: n.name,
              kind: n.kind === 'NODE_KIND_DIRECTORY' ? 'directory' : 'file',
              sizeBytes: n.file?.sizeBytes ?? '0',
              updatedAt: n.updatedAt,
            })),
        };
      }
      if (path.endsWith('/files:grep')) {
        const needle = String(body.pattern ?? '').toLowerCase();
        return {
          hits: files
            .filter(
              (n) => n.storageId === storage && n.file && n.content.toLowerCase().includes(needle),
            )
            .map((node) => ({
              fileId: node.id,
              path: node.name,
              lineText: node.content.slice(0, 240),
              lineNumber: node.content
                .slice(0, node.content.toLowerCase().indexOf(needle))
                .split('\n').length,
            })),
        };
      }
      if (path.endsWith('/files:semanticSearch'))
        throw new ApiError(
          503,
          'Meaning search is unavailable in the public demo. Try Exact text.',
        );
      if (path.endsWith('/trash') && method === 'GET') return { entries: [] };
      if (path.endsWith(':download') && node?.downloadUrl)
        return { blob: { url: node.downloadUrl } };
      if (path.endsWith(':download') && node)
        return { text: { content: node.content, mediaType: node.file?.mediaType ?? 'text/plain' } };
      if (path.endsWith('/text') && node?.file) {
        if (String(body.expectedVersion) !== node.file.version)
          throw new ApiError(409, 'The file changed. Reload it and try again.');
        node.content = body.replace;
        node.updatedAt = new Date().toISOString();
        node.file.version = String(Number(node.file.version) + 1);
        node.file.sizeBytes = String(new Blob([node.content]).size);
        return node;
      }
      if (path.endsWith('/nodes') && method === 'POST') {
        if (body.text)
          return addFile(
            storage,
            body.parent.nodeId,
            body.name,
            body.text.content,
            body.text.mediaType,
          );
        const folder: DemoFile = {
          id: crypto.randomUUID(),
          storageId: storage,
          parentId: body.parent.nodeId,
          name: body.name,
          kind: 'NODE_KIND_DIRECTORY',
          content: '',
          updatedAt: date(),
        };
        files.push(folder);
        return folder;
      }
      if (node && method === 'GET') return node;
      throw new ApiError(400, 'This action is unavailable in the public demo.');
    }
    throw new ApiError(404, 'This action is unavailable in the public demo.');
  }
  const backend: Backend = {
    preview: true,
    previewRealtime,
    enabled: true,
    ready: true,
    actorId: owner,
    api: async <T>(path: string, init?: RequestInit) =>
      structuredClone(await handle(path, init)) as T,
    request: async (path, init) => {
      if (path.includes('/image?')) {
        const id = /\/nodes\/([^/]+)\/image/.exec(path)?.[1];
        const image = files.find((file) => file.id === id);
        if (image?.downloadUrl) return fetch(image.downloadUrl);
      }
      return Response.json(await handle(path, init));
    },
  };
  message(
    'atlas',
    'user',
    'Maya’s review is Thursday at 16:00. Please keep anything we can share in Team storage.',
  );
  message(
    'atlas',
    'assistant',
    'Got it. I’ll keep the source files intact, put drafts in Team storage, and hold publishing until you choose the channels.',
  );
  message(
    'atlas',
    'user',
    `The campaign export is in ${fileToken({ storage_id: 'team', node_id: 'team-channels', label: 'last campaign’s CSV' })}. Social had the most traffic, but I’m not convinced we should spend more there.`,
  );
  message(
    'atlas',
    'assistant',
    'I’ll compare activated users and cost per activation. Traffic alone won’t be the recommendation.',
  );
  message(
    'scout',
    'user',
    'For the launch review, please keep interview quotes traceable to the original notes.',
  );
  message(
    'scout',
    'assistant',
    `I have INT-014, INT-019 and INT-023 in the ${fileToken({ storage_id: 'team', node_id: 'team-research', label: 'interview notes' })}. I’ll separate direct quotes from our interpretation; three interviews are not a survey.`,
  );
  message(
    'forge',
    'user',
    'The newsletter should sound like us. Plain language, one CTA, no claims we can’t support.',
  );
  message(
    'forge',
    'assistant',
    'I’ve read the Morrow voice guide. I’ll lead with the client handoff problem and leave three subject lines so you can choose.',
  );
  incoming('atlas', {
    source_kind: 'user',
    source_id: 'maya',
    source_name: 'Maya Chen',
    conversation_id: 'maya:atlas',
    content:
      'For Thursday: bring the channel evidence and a report I can share with the team. No increase in total spend without review.',
  });
  for (const [i, p] of profiles.entries())
    p.updated_at = new Date(epoch - (i + 1) * 12 * 60_000).toISOString();
  return {
    backend,
    activate() {
      disposed = false;
    },
    select,
    play,
    pause,
    dispose() {
      pause();
      disposed = true;
      channelListeners.clear();
      chatUserListeners.clear();
      letaUserListeners.clear();
      steps.length = 0;
    },
  };
}
