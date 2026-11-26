export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
export type Cursor = Record<string, string>;
export type Page<T> = { items: T[]; next_cursor: Cursor | string | null; pending_count?: number };
export type Capabilities = {
  can_chat: boolean;
  can_view_activity: boolean;
  can_edit_settings: boolean;
  can_delete?: boolean;
};
export type AgentResource = {
  id: string;
  name: string;
  title?: string;
  handle?: string;
  appearance?: { shape: string; color: string };
  description: string;
  custom_instructions?: string;
  workspace_id: string;
  storage_id?: string;
  state: string;
  paused: boolean;
  running?: boolean;
  model_id: string | null;
  reasoning_effort: string | null;
  can_manage?: boolean;
  can_delete?: boolean;
  capabilities?: Capabilities;
  preview?: string | null;
  updated_at?: string | null;
  unread_count?: number;
  latest_reply_id?: string | null;
  latest_reply_at?: string | null;
};

export function agentCapabilities(agent?: AgentResource | null): Capabilities {
  if (!agent) {
    return { can_chat: false, can_view_activity: false, can_edit_settings: false };
  }
  if (agent.capabilities) return agent.capabilities;
  const manage = Boolean(agent.can_manage);
  return {
    can_chat: true,
    can_view_activity: manage,
    can_edit_settings: manage,
    can_delete: Boolean(agent.can_delete),
  };
}

export type RunRecord = {
  id: string;
  agent_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  error_code?: string | null;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cost_usd: number;
  llm_calls: number;
  started_at: string;
  heartbeat_at?: string | null;
  finished_at?: string | null;
};

export type MessageReaction = { actor_kind: 'user' | 'agent'; actor_id: string; emoji: string };
export type ReactionInput = {
  actor: { kind: 'user' | 'agent'; id: string };
  target: { message_id: string; kind: 'incoming' | 'outgoing'; content: string };
  previous_emoji: string | null;
  emoji: string | null;
};
export type ReplyRef = { id: string; role: 'user' | 'assistant'; content: string };
export type ChatMessage = {
  id: string;
  seq?: number;
  role: 'user' | 'assistant';
  sender_type?: 'user' | 'agent';
  sender_id?: string;
  content: string;
  created_at: string;
  edited_at?: string | null;
  deleted_at?: string | null;
  conversation_id?: string;
  message_group_id?: string | null;
  read_at?: string | null;
  reply?: ReplyRef | null;
  reply_to_id?: string | null;
  status?: 'sending' | 'failed';
  file_refs?: import('./file-refs.js').FileRef[];
  sources?: import('./file-refs.js').MessageSource[];
  reactions?: MessageReaction[];
};
export type Question = {
  id: string;
  text: string;
  type: 'text' | 'single_choice' | 'multiple_choice';
  options?: { id: string; label: string }[];
};
export type HumanRequest = {
  id: string;
  type: 'ask' | 'approval';
  title: string;
  recipient_user_id: string;
  requester_agent_id: string;
  requester_name?: string;
  leta_id?: string;
  workspace_id?: string;
  payload: { questions?: Question[]; role?: string; reason?: string; storage_id?: string };
  status: 'pending' | 'answered' | 'accepted' | 'denied' | 'cancelled' | 'expired';
  response?: {
    answers?: Record<
      string,
      { text?: string; option_id?: string | null; option_ids?: string[]; note?: string }
    >;
  } | null;
  outcome?: { status: string; reason?: string } | null;
  created_at: string;
  resolved_at?: string | null;
};
export type InputItem = {
  file_refs?: import('./file-refs.js').FileRef[];
  sources?: import('./file-refs.js').MessageSource[];
  input_type?: 'message' | 'reaction';
  silent?: boolean;
  input_payload?: ReactionInput;
  reactions?: MessageReaction[];
  id?: string;
  seq?: number;
  source_kind: string;
  source_id?: string;
  source_name?: string;
  source_handle?: string;
  conversation_id?: string;
  content: string;
  preview?: boolean;
  presented?: boolean;
  scheduled_at?: string | null;
  schedule_title?: string;
  request_title?: string;
  request_type?: string;
  request_payload?: HumanRequest['payload'];
  decision?: Record<string, Json>;
};
export type ActivityEntry = {
  id: string;
  agent_id: string;
  run_id: string;
  seq: number;
  created_at: string;
  kind: 'inbox_input' | 'assistant' | 'tool_call' | 'tool_result' | 'final_note' | 'compaction';
  has_details?: boolean;
  payload: {
    text?: string | null;
    reasoning?: string | null;
    name?: string;
    args?: Record<string, Json>;
    tool_call_id?: string;
    status?: string;
    ui?: { version: number; kind: string; items?: InputItem[]; data?: Json };
  };
};

export type RawActivityRow = {
  agent_id: string;
  seq: number;
  run_id?: string | null;
  type: string;
  data: Record<string, Json>;
  created_at: string;
};

/** Normalize new apps/leta activity_events rows into the UI ActivityEntry contract. */
export function normalizeActivityEntry(raw: RawActivityRow | ActivityEntry): ActivityEntry | null {
  if ('kind' in raw && 'payload' in raw) return raw;
  const data = raw.data ?? {};
  const id = `${raw.agent_id}:${raw.seq}`;
  const runId = raw.run_id ?? 'run';
  switch (raw.type) {
    case 'activity.inbox_received': {
      const items = Array.isArray(data.items) ? (data.items as Record<string, Json>[]) : [];
      const mapped: InputItem[] = items.map((it) => {
        const sender =
          it.sender && typeof it.sender === 'object' && !Array.isArray(it.sender)
            ? (it.sender as Record<string, Json>)
            : {};
        const meta =
          it.metadata && typeof it.metadata === 'object' && !Array.isArray(it.metadata)
            ? (it.metadata as Record<string, Json>)
            : {};
        const rawKind = String(it.kind ?? 'channel');
        const senderType = typeof sender.type === 'string' ? sender.type : '';
        const sourceKind =
          rawKind === 'schedule' || rawKind === 'hitl'
            ? rawKind
            : senderType === 'user' || senderType === 'agent'
              ? senderType
              : rawKind === 'agent'
                ? 'agent'
                : 'user';
        const rawAtts = Array.isArray(it.attachments)
          ? (it.attachments as Record<string, Json>[])
          : [];
        const fileRefs = rawAtts.flatMap((a) =>
          typeof a.storage_id === 'string' && typeof a.node_id === 'string'
            ? [
                {
                  storage_id: a.storage_id,
                  node_id: a.node_id,
                  label: typeof a.name === 'string' && a.name ? a.name : 'Attachment',
                  kind: (a.kind === 'folder' ? 'folder' : 'file') as 'file' | 'folder',
                  name: typeof a.name === 'string' ? a.name : undefined,
                  mime: typeof a.media_type === 'string' ? a.media_type : undefined,
                  size: typeof a.size_bytes === 'number' ? a.size_bytes : undefined,
                },
              ]
            : [],
        );
        const isReaction =
          meta.event === 'reaction' ||
          (rawKind === 'notification' && typeof meta.emoji === 'string');
        const reactionPayload = isReaction
          ? {
              actor: {
                kind: (senderType === 'agent' ? 'agent' : 'user') as 'user' | 'agent',
                id: typeof sender.id === 'string' ? sender.id : '',
              },
              target: {
                message_id: typeof meta.message_id === 'string' ? meta.message_id : '',
                kind: 'incoming' as const,
                content: String(it.content ?? it.preview ?? ''),
              },
              previous_emoji: null,
              emoji:
                meta.action === 'removed'
                  ? null
                  : typeof meta.emoji === 'string'
                    ? meta.emoji
                    : null,
            }
          : undefined;
        return {
          seq: typeof it.seq === 'number' ? it.seq : undefined,
          source_kind: sourceKind,
          source_id: typeof sender.id === 'string' ? sender.id : undefined,
          source_name:
            (typeof sender.name === 'string' && sender.name) ||
            (typeof sender.handle === 'string' && sender.handle) ||
            undefined,
          source_handle: typeof sender.handle === 'string' ? sender.handle : undefined,
          content: String(it.content ?? it.preview ?? ''),
          preview: it.delivery_state === 'previewed',
          ...(fileRefs.length ? { file_refs: fileRefs } : {}),
          ...(isReaction && reactionPayload
            ? { input_type: 'reaction' as const, input_payload: reactionPayload }
            : {}),
          ...(rawKind === 'schedule'
            ? {
                schedule_title: typeof meta.title === 'string' ? meta.title : undefined,
                scheduled_at:
                  typeof meta.scheduled_for === 'string' ? meta.scheduled_for : undefined,
              }
            : {}),
          ...(rawKind === 'hitl'
            ? {
                request_title: typeof meta.title === 'string' ? meta.title : undefined,
                request_type: typeof meta.type === 'string' ? meta.type : undefined,
                decision: {
                  status: typeof meta.status === 'string' ? meta.status : '',
                  ...(meta.outcome ? { outcome: { status: String(meta.outcome) } } : {}),
                },
              }
            : {}),
        };
      });
      return {
        id,
        agent_id: raw.agent_id,
        run_id: runId,
        seq: raw.seq,
        created_at: raw.created_at,
        kind: 'inbox_input',
        payload: {
          text: mapped.map((m) => m.content).join('\n'),
          ui: { version: 1, kind: 'inbox_batch', items: mapped },
        },
      };
    }
    case 'activity.message':
      if (data.synthetic) return null;
      return {
        id,
        agent_id: raw.agent_id,
        run_id: runId,
        seq: raw.seq,
        created_at: raw.created_at,
        kind: 'assistant',
        payload: {
          text: typeof data.text === 'string' ? data.text : '',
          reasoning: typeof data.reasoning === 'string' ? data.reasoning : null,
        },
      };
    case 'activity.tool_call':
      return {
        id,
        agent_id: raw.agent_id,
        run_id: runId,
        seq: raw.seq,
        created_at: raw.created_at,
        kind: 'tool_call',
        payload: {
          tool_call_id: String(data.tool_call_id ?? id),
          name: String(data.name ?? 'tool'),
          args:
            data.args && typeof data.args === 'object' && !Array.isArray(data.args)
              ? (data.args as Record<string, Json>)
              : {},
        },
      };
    case 'activity.tool_result': {
      const artifact =
        data.artifact && typeof data.artifact === 'object' && !Array.isArray(data.artifact)
          ? (data.artifact as Record<string, Json>)
          : undefined;
      const text =
        typeof data.content === 'string'
          ? data.content
          : typeof data.preview === 'string'
            ? data.preview
            : '';
      return {
        id,
        agent_id: raw.agent_id,
        run_id: runId,
        seq: raw.seq,
        created_at: raw.created_at,
        kind: 'tool_result',
        has_details: Boolean(data.has_more_content && typeof data.content !== 'string'),
        payload: {
          tool_call_id: String(data.tool_call_id ?? ''),
          name: String(data.name ?? 'tool'),
          status: String(data.status ?? 'success'),
          text,
          ...(artifact
            ? { ui: { version: 1, kind: String(data.name ?? 'tool'), data: artifact } }
            : {}),
        },
      };
    }
    case 'activity.compacted':
      return {
        id,
        agent_id: raw.agent_id,
        run_id: runId,
        seq: raw.seq,
        created_at: raw.created_at,
        kind: 'compaction',
        payload: {
          text: `Compacted (${String(data.reason ?? 'auto')}): ${String(data.before_tokens ?? '?')} → ${String(data.after_tokens ?? '?')} tokens.\n${String(data.summary_preview ?? '')}`,
        },
      };
    case 'activity.agent_message':
      return {
        id,
        agent_id: raw.agent_id,
        run_id: runId,
        seq: raw.seq,
        created_at: raw.created_at,
        kind: 'inbox_input',
        payload: {
          text: String(data.content ?? ''),
          ui: {
            version: 1,
            kind: 'inbox_batch',
            items: [
              {
                source_kind: 'agent',
                source_name: String(data.from_handle ?? 'agent'),
                content: String(data.content ?? ''),
              },
            ],
          },
        },
      };
    default:
      return null;
  }
}

export type InboxItem = {
  file_refs?: import('./file-refs.js').FileRef[];
  sources?: import('./file-refs.js').MessageSource[];
  input_type?: 'message' | 'reaction';
  silent?: boolean;
  input_payload?: ReactionInput;
  reactions?: MessageReaction[];
  id: string;
  conversation_id: string;
  source_kind: string;
  source_id: string;
  source_name: string | null;
  content: string;
  created_at: string;
  direction: 'in' | 'out';
  unread_count: number;
  read_at?: string | null;
  request_type?: string;
  request_payload?: HumanRequest['payload'];
  schedule_title?: string;
  scheduled_at?: string | null;
};
export type LiveEvent = {
  type: string;
  name?: string;
  value?: Record<string, Json>;
  messageId?: string;
  delta?: string;
  toolCallId?: string;
  toolCallName?: string;
  data?: Record<string, Json>;
  metadata?: { openlet?: { agentId?: string; runId?: string } };
};
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
export function queryString(value: Cursor | string | null | undefined, field = 'before') {
  return new URLSearchParams(
    typeof value === 'string' ? { [field]: value } : (value ?? {}),
  ).toString();
}
export const messageKey = (message: Pick<ChatMessage, 'role' | 'id'>) =>
  `${message.role}:${message.id}`;
