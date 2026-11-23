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
  appearance?: { shape: string; color: string };
  description: string;
  workspace_id: string;
  state: string;
  paused: boolean;
  model_id: string | null;
  reasoning_effort: string | null;
  capabilities: Capabilities;
  preview?: string | null;
  updated_at?: string | null;
  unread_count?: number;
  latest_reply_id?: string | null;
  latest_reply_at?: string | null;
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
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  conversation_id?: string;
  message_group_id?: string | null;
  read_at?: string | null;
  reply?: ReplyRef | null;
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
