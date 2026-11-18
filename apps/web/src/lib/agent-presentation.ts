import type { ActivityEntry, HumanRequest, InputItem, Json } from './agent-api.js';
import { scheduleTiming } from './schedule-presentation.js';
import type { FileRef } from './file-refs.js';

// Tool presentation contract for versioned runtime snapshots.
export type ToolItem = {
  title: string;
  detail: string;
  file?: FileRef;
  kind?: 'folder' | 'file';
  meta?: string;
  status?: string;
  sender?: string;
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
  fileRefs?: FileRef[];
  title?: string;
  content?: string;
  timing?: string;
  when?: { day: string; time: string };
  previousTiming?: string;
  timezone?: string;
  upcoming?: string[];
  target?: string;
  status?: string;
  duration?: string;
  home?: string;
  representative?: string;
  edges?: [string, string][];
  lineRange?: string;
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

// Adapts versioned snapshots, never clipped model-facing English/JSON previews.
export function activityToolResult(entry: ActivityEntry): ToolResult | string {
  const { payload } = entry;
  const ui = payload.ui;
  if (!ui && payload.name !== 'execute') return payload.text ?? '';
  const data = object(ui?.data);
  const items = rows(
    data.items ?? data.members ?? data.recipients ?? data.boxes ?? data.letis ?? data.entries,
  );
  const name = payload.name ?? '';
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
      meta: string(item.role ?? item.target_name ?? item.source_kind),
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
  if (name === 'history_search')
    result.items = items.map((item) => ({
      title: `#${item.seq} · ${string(item.kind).replaceAll('_', ' ')}`,
      detail: string(item.text_preview),
      meta: string(item.created_at),
    }));
  if (name.startsWith('box_')) {
    const members = rows(data.letis);
    const names = new Map(members.map((member) => [string(member.id), string(member.name)]));
    result.title = string(data.name ?? data.box);
    result.home = string(data.home) || (data.name ? `~/.boxes/${string(data.name)}/` : '');
    result.representative =
      string(data.representative) || names.get(string(data.representative_agent_id));
    result.edges = Array.isArray(data.edges)
      ? data.edges.map((edge) =>
          Array.isArray(edge)
            ? [string(edge[0]), string(edge[1])]
            : [
                names.get(string(object(edge).agent_low_id)) ?? '',
                names.get(string(object(edge).agent_high_id)) ?? '',
              ],
        )
      : [];
  }
  if (name === 'execute') result.exitCode = payload.status === 'error' ? 1 : 0;
  if (name === 'inbox_send') {
    result.content = typeof data.content === 'string' ? data.content : undefined;
    result.fileRefs = rows(data.file_refs).flatMap((ref) => {
      const reference = file(ref);
      return reference
        ? [{ ...reference, label: string(ref.label ?? ref.name), mime: string(ref.mime) }]
        : [];
    });
  }
  if (name === 'inbox_react')
    result.reaction = {
      emoji: typeof data.emoji === 'string' ? data.emoji : null,
      content: string(data.content),
    };
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
      meta: string(item.target),
      time: scheduleTiming(object(item.spec)),
      status: item.deleted_at ? 'Deleted' : item.paused ? 'Paused' : 'Active',
    }));
  return result;
}
