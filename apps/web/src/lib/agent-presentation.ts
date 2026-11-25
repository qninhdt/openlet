import type { ActivityEntry, HumanRequest, InputItem, Json } from './agent-api.js';
import { scheduleTiming } from './schedule-presentation.js';
import type { FileRef, MessageSource } from './file-refs.js';

// Tool presentation contract for versioned runtime snapshots.
export type ToolItem = {
  title: string;
  detail: string;
  file?: FileRef;
  fileRefs?: FileRef[];
  sources?: MessageSource[];
  kind?: 'folder' | 'file';
  meta?: string;
  status?: string;
  sender?: string;
  address?: string;
  time?: string;
};
export type ToolResult = {
  reaction?: { emoji: string | null; content: string };
  inputItems?: InputItem[];
  request?: Pick<HumanRequest, 'title' | 'status' | 'payload'> &
    Partial<Pick<HumanRequest, 'response'>>;
  summary?: string;
  output?: string;
  exitCode?: number;
  file?: FileRef;
  items?: ToolItem[];
  messages?: { content: string; fileRefs: FileRef[]; sources?: MessageSource[] }[];
  title?: string;
  content?: string;
  timing?: string;
  when?: { day: string; time: string };
  previousTiming?: string;
  timezone?: string;
  upcoming?: string[];
  target?: string;
  recipient?: { kind: 'user' | 'agent'; id: string };
  agentStatus?: {
    title: string;
    leader: boolean;
    assignments: { sender: string; label: string; preview: string; message: string }[];
    activity: { tool: string; status: string; at: string }[];
  };
  status?: string;
  duration?: string;
  home?: string;
  leader?: string;
  edges?: [string, string][];
  lineRange?: string;
  webSources?: { url: string; title: string; snippet: string; publishedAt: string }[];
  webFormat?: string;
  truncated?: boolean;
};

function object(value: Json | undefined): Record<string, Json> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}
function rows(value: Json | undefined): Record<string, Json>[] {
  return Array.isArray(value) ? value.map(object) : [];
}
function string(value: Json | undefined) {
  return value == null ? '' : typeof value === 'string' ? value : String(value);
}
function file(value: Record<string, Json>): FileRef | undefined {
  if (
    typeof value.storage_id !== 'string' ||
    !value.storage_id ||
    typeof value.node_id !== 'string' ||
    !value.node_id
  )
    return;
  return {
    storage_id: value.storage_id,
    node_id: value.node_id,
    label: string(value.path ?? value.name),
  };
}
function fileRefsOf(value: Json | undefined): FileRef[] {
  return rows(value).flatMap((ref) => {
    const reference = file(ref);
    return reference
      ? [
          {
            ...reference,
            label: string(ref.label ?? ref.name),
            mime: string(ref.mime),
            ...(ref.kind === 'folder' ? { kind: 'folder' as const } : {}),
          },
        ]
      : [];
  });
}

// Adapts versioned snapshots, never clipped model-facing English/JSON previews.
export function activityToolResult(entry: ActivityEntry): ToolResult | string {
  const { payload } = entry;
  const ui = payload.ui;
  const name = payload.name ?? '';
  if (name === 'websearch' || name === 'webfetch') {
    if (payload.status === 'error') return { output: payload.text ?? '' };
    const data = object(ui?.data);
    return {
      webSources: (name === 'websearch' ? rows(data.results) : [data]).flatMap((source) => {
        const href = source.final_url ?? source.url;
        if (typeof href !== 'string') return [];
        let url: URL;
        try {
          url = new URL(href);
        } catch {
          return [];
        }
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return [];
        return [
          {
            url: url.href,
            title: string(source.title) || url.href,
            snippet: string(source.snippet),
            publishedAt: string(source.published_at),
          },
        ];
      }),
      webFormat: string(data.format),
      truncated: data.truncated === true,
    };
  }
  if (!ui && name === 'agent_status' && entry.has_details && payload.status !== 'error') return {};
  if (!ui && name !== 'execute') return payload.text ?? '';
  const data = object(ui?.data);
  const items = rows(data.items ?? data.members ?? data.boxes ?? data.letis ?? data.entries);
  const result: ToolResult = {
    output: payload.text ?? '',
    content: payload.text ?? '',
    title: string(data.title ?? data.name),
    status: string(data.status ?? data.state),
    home: string(data.home ?? data.workdir),
    target: string(data.target_name),
    summary: '',
    file: file(data),
  };
  if (ui?.kind === 'messages' || ui?.kind === 'inbox_batch') {
    result.inputItems = ui.items;
    result.items = ui.items?.map((item) => ({
      title: item.source_name ?? item.source_kind,
      sender: item.source_name ?? item.source_kind,
      detail: item.content,
      meta: item.preview ? 'Notification' : undefined,
    }));
  } else
    result.items = items.map((item) => ({
      title: string(item.name ?? item.title ?? item.path ?? item.displayName ?? item.id),
      detail: string(item.description ?? item.content ?? item.preview),
      meta: string(item.title ?? item.role ?? item.target_name ?? item.source_kind),
      address: string(item.recipient_user_id ?? item.handle),
      status: string(item.status ?? item.state ?? (item.paused ? 'Paused' : undefined)),
      kind: item.kind === 'directory' ? 'folder' : 'file',
      file: item.kind === 'directory' && !item.artifacts ? undefined : file(item),
    }));
  if (name === 'file_semantic_search')
    result.items = rows(data.groups).flatMap((group) =>
      rows(group.hits).map((hit) => ({
        title: string(hit.path),
        detail: string(hit.text),
        meta: string(group.path),
        file: file(hit),
      })),
    );
  if (name === 'activity_search')
    result.items = items.map((item) => ({
      title: [
        `#${item.seq}`,
        string(item.kind).replaceAll('_', ' '),
        string(item.tool),
        string(item.status),
      ]
        .filter(Boolean)
        .join(' · '),
      detail: string(item.text_preview),
      meta: string(item.created_at),
    }));
  if (name === 'activity_read') {
    result.title = [
      `Entry #${string(data.entry)}`,
      string(data.kind).replaceAll('_', ' '),
      string(data.tool),
      string(data.status),
    ]
      .filter(Boolean)
      .join(' · ');
    result.summary = data.paired_entry ? `Paired with entry #${string(data.paired_entry)}` : '';
    result.lineRange = data.start_line ? `From line ${string(data.start_line)}` : '';
    result.content = string(data.content) || payload.text || '';
  }
  if (ui?.kind === 'inbox_history')
    result.items = items.map((item) => {
      const reply = object(item.reply);
      const reactionBadges = rows(item.reactions)
        .map((r) => string(r.emoji))
        .filter(Boolean)
        .join(' ');
      const fileRefs = fileRefsOf(item.file_refs);
      return {
        title: reply.content ? `Replying to “${string(reply.content)}”` : '',
        sender: string(item.sender_name),
        detail: string(item.content),
        meta: [string(item.created_at), reactionBadges].filter(Boolean).join(' · '),
        ...(fileRefs.length ? { fileRefs } : {}),
        ...(Array.isArray(item.sources) && item.sources.length
          ? { sources: item.sources as MessageSource[] }
          : {}),
      };
    });
  if (name === 'get_context') {
    const workspace = object(data.workspace);
    result.title = string(workspace.name);
    result.home = string(workspace.shared_path);
  }
  if (name === 'agent_status') {
    result.target = string(data.handle);
    result.agentStatus = {
      title: string(data.title),
      leader: data.is_leader === true,
      assignments: rows(data.assignment_inputs).map((item) => ({
        sender: string(item.sender),
        label: string(item.task_label),
        preview: string(item.preview),
        message: string(item.message),
      })),
      activity: rows(data.recent_activity)
        .filter((item) => typeof item.tool === 'string' && item.tool)
        .map((item) => ({
          tool: string(item.tool),
          status: string(item.status),
          at: string(item.created_at),
        })),
    };
  }
  if (name.startsWith('box_')) {
    result.title = string(data.name ?? data.box);
    result.home = string(data.home);
    result.leader = string(object(data.leader).name);
    result.edges = Array.isArray(data.additional_links)
      ? data.additional_links.flatMap((link) =>
          Array.isArray(link) ? [[string(link[0]), string(link[1])]] : [],
        )
      : [];
  }
  if (name === 'execute') result.exitCode = payload.status === 'error' ? 1 : 0;
  if (name === 'inbox_send') {
    const recipient = object(data.recipient);
    if (
      (recipient.kind === 'user' || recipient.kind === 'agent') &&
      typeof recipient.id === 'string'
    )
      result.recipient = { kind: recipient.kind, id: recipient.id };
    result.messages = rows(data.messages).map((message) => ({
      content: string(message.content),
      ...(Array.isArray(message.sources) && message.sources.length
        ? { sources: message.sources as MessageSource[] }
        : {}),
      fileRefs: fileRefsOf(message.file_refs),
    }));
  }
  if (name === 'inbox_react')
    result.reaction = {
      emoji: typeof data.emoji === 'string' ? data.emoji : null,
      content: string(data.content),
    };
  if (name === 'hitl_ask' || name === 'hitl_request' || name === 'hitl_get')
    result.target = string(data.recipient_user_id);
  if (name === 'hitl_ask' || name === 'hitl_request')
    result.request = {
      title: string(data.title),
      status: string(data.status) as HumanRequest['status'],
      payload: object(data.payload) as HumanRequest['payload'],
    };
  if (name === 'file_read') {
    result.content = string(data.content) || payload.text || '';
    result.lineRange = data.start_line ? `From line ${data.start_line}` : '';
  }
  if (name.startsWith('schedule_')) {
    const spec = object(data.spec);
    result.timing = scheduleTiming(spec);
    result.timezone = string(spec.timezone);
    result.target = string(data.target);
    result.upcoming = Array.isArray(data.upcoming)
      ? data.upcoming.map((value) => new Date(string(value)).toLocaleString())
      : undefined;
    result.previousTiming = data.previous_spec
      ? scheduleTiming(object(data.previous_spec))
      : undefined;
    result.content = string(data.content);
    result.status =
      data.deleted_at || data.deleted
        ? 'Deleted'
        : data.paused
          ? 'Paused'
          : string(data.status) || 'Active';
  }
  if (name === 'schedule_list')
    result.items = items.map((item) => ({
      title: string(item.title) || 'Scheduled instruction',
      detail: string(item.content),
      meta: string(item.target_name),
      time: scheduleTiming(object(item.spec)),
      status: item.deleted_at ? 'Deleted' : item.paused ? 'Paused' : 'Active',
    }));
  return result;
}
