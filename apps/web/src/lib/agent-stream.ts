import type { LiveEvent } from './agent-api.js';

export type StreamingItem = {
  id: string;
  agent: string;
  run: string;
  kind: 'text' | 'tool' | 'reasoning';
  name?: string;
  text: string;
};

export function reduceActivityStream(
  items: StreamingItem[],
  event: LiveEvent,
  root: string,
): StreamingItem[] {
  if (event.type === 'run.finished') {
    const data = event.data ?? {};
    const agent = typeof data.agent_id === 'string' ? data.agent_id : '';
    const run = typeof data.run_id === 'string' ? data.run_id : '';
    if (agent !== root || !run) return items;
    return items.filter((item) => item.run !== run);
  }
  if (
    event.type === 'stream.thinking_delta' ||
    event.type === 'stream.text_delta' ||
    event.type === 'stream.tool_args_delta'
  ) {
    const data = event.data ?? {};
    const agent = typeof data.agent_id === 'string' ? data.agent_id : '';
    const run = typeof data.run_id === 'string' ? data.run_id : '';
    const delta = typeof data.delta === 'string' ? data.delta : '';
    if (agent !== root || !run || !delta) return items;
    const kind: StreamingItem['kind'] =
      event.type === 'stream.thinking_delta'
        ? 'reasoning'
        : event.type === 'stream.text_delta'
          ? 'text'
          : 'tool';
    const id =
      kind === 'tool'
        ? typeof data.tool_call_id === 'string' && data.tool_call_id
          ? data.tool_call_id
          : `tool:${run}`
        : `${kind}:${run}`;
    const exists = items.some((item) => item.id === id && item.run === run && item.kind === kind);
    if (!exists) {
      return [
        ...items,
        {
          id,
          agent,
          run,
          kind,
          name: typeof data.name === 'string' ? data.name : undefined,
          text: delta.slice(0, 262144),
        },
      ].slice(-40);
    }
    return items.map((item) =>
      item.id === id && item.run === run && item.kind === kind
        ? { ...item, text: (item.text + delta).slice(0, 262144) }
        : item,
    );
  }
  return items;
}
